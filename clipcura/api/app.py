"""Local HTTP API used by the GUI, MCP and later n8n. Same actions as the CLI, nothing more (CLAUDE.md §2).

Bound to 127.0.0.1 only, bearer token on every route except /api/health, Host header pinned to loopback
names (DNS rebinding), no CORS: the GUI is served from this same origin.

No `from __future__ import annotations` here: FastAPI must evaluate the route signatures at definition
time to resolve dependencies that are local to create_app().
"""
import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from clipcura import __version__, rules
from clipcura.core import config, events, licenses, previews, profiles, security, service
from clipcura.core.config import Concurrency
from clipcura.core.models import Paths
from clipcura.core.paths import REPO_ROOT
from clipcura.core.worker import Worker

Actor = Literal["human", "ai", "n8n"]
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}


class ScanRequest(BaseModel):
    path: str
    profile: str = "social-30"
    recursive: bool = False
    deep: bool | None = None


class ConfigPatch(BaseModel):
    approval_mode: bool | None = None
    concurrency: Concurrency | None = None
    interface: Literal["window", "browser"] | None = None


class RootRequest(BaseModel):
    path: str


class PlanRequest(BaseModel):
    scan_id: str
    file_ids: list[int] | None = None
    paths: dict | None = None      # override measured paths, e.g. {"decode": "cpu"}


LOGIN_CODE_TTL_S = 120  # long enough for a cold browser start


class LoginRequest(BaseModel):
    code: str


class QueueState(BaseModel):
    paused: bool


def _host_ok(host: str | None) -> bool:
    if not host:
        return False
    name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    return name.lower() in _LOOPBACK


def create_app() -> FastAPI:
    cfg = config.load_config()
    worker = Worker(cfg.concurrency.gpu, cfg.concurrency.cpu)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        service.recover(worker)  # jobs a killed earlier service left queued or half-done
        yield
        worker.stop()

    app = FastAPI(title="Clipcura", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def loopback_only(request: Request, call_next):
        if not _host_ok(request.headers.get("host")):
            return JSONResponse({"detail": "Invalid Host header"}, status_code=400)
        return await call_next(request)

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if not authorization or not secrets.compare_digest(authorization, f"Bearer {cfg.token}"):
            raise HTTPException(401, "Missing or invalid token")

    def actor(x_clipcura_actor: Annotated[Actor, Header()] = "human") -> Actor:
        return x_clipcura_actor

    def allowed(path: str) -> str:
        try:
            return str(security.ensure_allowed(path, config.load_config().allowed_roots))
        except security.PathNotAllowed as e:
            raise HTTPException(403, str(e)) from e

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    # One-time codes for opening the GUI in a browser (#23): the URL a browser is started with ends up in its
    # history and in the process list, so it carries a short-lived code instead of the access key.
    login_codes: dict[str, float] = {}

    @app.post("/api/login")
    def login(req: LoginRequest) -> dict:
        expires = login_codes.pop(req.code, None)
        if expires is None or time.monotonic() > expires:
            raise HTTPException(401, "Unknown or expired code")
        return {"token": cfg.token}

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    system_cache: dict[str, tuple[float, dict]] = {}

    @api.post("/login-codes")
    def new_login_code() -> dict:
        now = time.monotonic()
        for stale in [c for c, expires in login_codes.items() if expires < now]:
            login_codes.pop(stale, None)
        code = secrets.token_urlsafe(24)
        login_codes[code] = now + LOGIN_CODE_TTL_S
        return {"code": code, "expires_in": LOGIN_CODE_TTL_S}

    @api.get("/about")
    def about() -> dict:
        from clipcura import LICENCE, OWNER, SOURCE
        from clipcura.core.paths import app_data_dir, install_kind
        return {"name": "Clipcura", "version": __version__, "owner": OWNER, "licence": LICENCE, "source": SOURCE,
                "install": {"kind": install_kind(), "data_dir": str(app_data_dir())},
                "components": licenses.components()}

    @api.get("/about/notices", response_class=PlainTextResponse)
    def notices() -> str:
        return licenses.notices_text()

    @api.get("/system")
    def system() -> dict:
        from clipcura.core.doctor import load_report, run_doctor
        report = load_report()
        if report is not None:
            return report.model_dump()
        # No measured report yet: a quick hardware read plus the probe-based paths, cached briefly because
        # reading GPU and disk details takes a couple of seconds and the start screen asks on every visit.
        cached = system_cache.get("quick")
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        # Free space where footage and outputs live (the allowed folders), not where the server started.
        roots = [Path(r) for r in config.load_config().allowed_roots if Path(r).exists()]
        quick = run_doctor(disk_paths=roots or None, run_probes=False)
        quick.paths = service.detect_paths()
        quick.backend = quick.paths.encode
        data = quick.model_dump()
        system_cache["quick"] = (time.monotonic(), data)
        return data

    @api.get("/profiles")
    def list_profiles() -> list[dict]:
        return [p.model_dump() | {"source": profiles.source_of(p.name)} for p in profiles.list_profiles()]

    @api.put("/profiles/{name}")
    def save_profile(name: str, body: dict, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)  # a profile decides where output is written and what gets converted
        if body.get("name") != name:
            raise HTTPException(422, "The profile name in the body must match the URL")
        try:
            profile = profiles.validate(body, config.load_config().allowed_roots)
        except profiles.ProfileError as e:
            raise HTTPException(422, str(e)) from e
        profiles.save_user_profile(profile)
        return profile.model_dump() | {"source": profiles.source_of(name)}

    @api.delete("/profiles/{name}")
    def delete_profile(name: str, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        try:
            profiles.delete_user_profile(name)
        except profiles.ProfileError as e:
            raise HTTPException(400, str(e)) from e
        return {"name": name, "deleted": True}

    @api.get("/rules")
    def list_rules() -> list[dict]:
        return [{"id": r.id, "title": r.title, "standalone": getattr(r, "standalone", True)}
                for r in rules.load_rules()]

    @api.post("/scans")
    def create_scan(req: ScanRequest, who: Annotated[Actor, Depends(actor)]) -> dict:
        try:
            result = service.scan(allowed(req.path), profile=req.profile, recursive=req.recursive,
                                  deep=req.deep, actor=who)
        except (NotADirectoryError, profiles.ProfileError) as e:
            raise HTTPException(400, str(e)) from e
        return result.model_dump()

    @api.get("/scans/{scan_id}")
    def get_scan(scan_id: str) -> dict:
        try:
            return service.get_scan(scan_id).model_dump()
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    @api.post("/plans")
    def create_plan(req: PlanRequest, who: Annotated[Actor, Depends(actor)]) -> dict:
        try:
            paths = Paths.model_validate(req.paths) if req.paths else None
            return service.plan(req.scan_id, file_ids=req.file_ids, actor=who, paths=paths).model_dump()
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    @api.post("/plans/{plan_id}/apply")
    def apply_plan(plan_id: str, who: Annotated[Actor, Depends(actor)], force: bool = False) -> dict:
        cfg_now = config.load_config()
        try:
            for out in service.plan_outputs(plan_id, force):
                allowed(out)  # outputs must land inside an allowed folder too
            jobs = service.enqueue(plan_id, worker, actor=who, force=force, approval_mode=cfg_now.approval_mode)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        return {"jobs": jobs}

    @api.get("/jobs")
    def get_jobs(ids: str | None = None, limit: int = 50) -> list[dict]:
        if ids is None:
            return service.recent_jobs(limit)
        return service.status([i for i in ids.split(",") if i])

    @api.get("/scans")
    def list_scans(limit: int = 10) -> list[dict]:
        return service.recent_scans(limit)

    @api.get("/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict:
        try:
            return service.get_plan(plan_id).model_dump()
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    @api.get("/audit")
    def audit(limit: int = 100) -> list[dict]:
        return service.audit_log(limit)

    def jpeg(source: Path, at: float, filters: str = "") -> Response:
        allowed(str(source))  # re-checked on every request: removing a folder revokes its previews at once
        try:
            return Response(previews.frame_jpeg(source, at, filters), media_type="image/jpeg",
                            headers={"Cache-Control": "private, max-age=3600"})
        except (OSError, RuntimeError) as e:
            raise HTTPException(422, f"Preview not available: {e}") from e

    @api.get("/files/{file_id}/thumbnail")
    def thumbnail(file_id: int, at: float = 1.0) -> Response:
        try:
            return jpeg(service.file_source(file_id), at)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    @api.get("/plan-items/{item_id}/preview")
    def after_preview(item_id: int, at: float = 1.0) -> Response:
        try:
            source, filters = service.plan_item_preview_source(item_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        return jpeg(source, at, filters)

    @api.get("/config")
    def get_config() -> dict:
        # The token is never sent back: clients already have it, and the page must not be able to leak it.
        return config.load_config().model_dump(exclude={"token"})

    @api.patch("/config")
    def patch_config(req: ConfigPatch, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        cfg_now = config.load_config()
        if req.approval_mode is not None:
            cfg_now.approval_mode = req.approval_mode
        if req.concurrency is not None:
            cfg_now.concurrency = req.concurrency
            worker.resize(req.concurrency.gpu, req.concurrency.cpu)
        if req.interface is not None:
            cfg_now.interface = req.interface
        config.save_config(cfg_now)
        return cfg_now.model_dump(exclude={"token"})

    @api.get("/queue")
    def get_queue() -> dict:
        return {"paused": worker.paused}

    @api.post("/queue")
    def set_queue(req: QueueState, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)  # pausing is a person's call, like approving
        worker.pause() if req.paused else worker.resume()
        events.publish("queue", paused=worker.paused)
        return {"paused": worker.paused}

    @api.post("/config/roots")
    def add_root(req: RootRequest, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)  # an assistant widening its own sandbox would defeat the whitelist
        if not Path(req.path).is_dir():
            raise HTTPException(400, f"Not a folder: {req.path}")
        return config.allow_root(req.path).model_dump(exclude={"token"})

    @api.delete("/config/roots")
    def remove_root(req: RootRequest, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        return config.disallow_root(req.path).model_dump(exclude={"token"})

    @api.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        found = service.status([job_id])
        if not found:
            raise HTTPException(404, f"Unknown job {job_id}")
        return found[0]

    @api.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, who: Annotated[Actor, Depends(actor)]) -> dict:
        if not service.cancel(job_id, actor=who):
            raise HTTPException(409, f"Job {job_id} is not running or waiting")
        return {"job_id": job_id, "cancel": "requested"}

    def human_only(who: Actor) -> None:
        # Approvals and settings are the human checkpoint over AI actions; letting the requester decide voids it.
        if who != "human":
            raise HTTPException(403, "Only a human can do this")

    @api.post("/jobs/{job_id}/approve")
    def approve_job(job_id: str, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        try:
            return service.approve(job_id, worker, actor=who)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @api.post("/jobs/{job_id}/reject")
    def reject_job(job_id: str, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        try:
            return service.reject(job_id, actor=who)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    app.include_router(api)

    @app.websocket("/api/events")
    async def event_stream(ws: WebSocket) -> None:
        # Browsers cannot set headers on WebSockets, so the token comes as a query parameter.
        token = ws.query_params.get("token", "")
        if not _host_ok(ws.headers.get("host")) or not secrets.compare_digest(token, cfg.token):
            await ws.close(code=1008)
            return
        await ws.accept()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict] = asyncio.Queue()
        unsubscribe = events.subscribe(lambda e: loop.call_soon_threadsafe(queue.put_nowait, e))
        # Listen as well as send: a client leaving (or the server closing the socket on shutdown) shows up
        # only on the receiving side. Without it the handler waits for the next event forever and the
        # service cannot stop.
        closed = asyncio.create_task(ws.receive())
        try:
            while True:
                event = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({event, closed}, return_when=asyncio.FIRST_COMPLETED)
                if event in done:
                    await ws.send_json(event.result())
                else:
                    event.cancel()  # an unfinished Queue.get gives nothing up when cancelled
                if closed in done:
                    if closed.result().get("type") == "websocket.disconnect":
                        break
                    closed = asyncio.create_task(ws.receive())  # a message from the client: ignored
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            closed.cancel()
            unsubscribe()

    # ---- the GUI itself, served from this origin (registered last so /api routes always win) ----
    @app.get("/{path:path}", include_in_schema=False)
    def ui(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        root = ui_dir()
        index = root / "index.html"
        if not index.is_file():
            return PlainTextResponse("The GUI is not built yet: run `npm run build` in ui/.", status_code=404)
        target = (root / path).resolve()
        # Only files inside the UI folder; anything else (including ../ tricks) gets the app shell.
        if path and target.is_file() and target.is_relative_to(root.resolve()):
            return FileResponse(target, headers=_static_headers(target))
        return FileResponse(index, headers={**_CSP, "Cache-Control": "no-cache"})

    return app


# Same-origin only: scripts, styles, fonts and API calls come from this server; WebSocket to loopback.
_CSP = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self' data:; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _static_headers(target: Path) -> dict:
    # Vite puts a content hash in asset names, so they can be cached for good.
    immutable = target.parent.name == "assets"
    return {"X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"}


def ui_dir() -> Path:
    override = os.environ.get("CLIPCURA_UI_DIR")
    return Path(override) if override else REPO_ROOT / "ui" / "dist"
