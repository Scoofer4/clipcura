"""Local HTTP API used by the GUI, MCP and later n8n. Same actions as the CLI, nothing more (CLAUDE.md §2).

Bound to 127.0.0.1 only, bearer token on every route except /api/health, Host header pinned to loopback
names (DNS rebinding), no CORS: the GUI is served from this same origin.

No `from __future__ import annotations` here: FastAPI must evaluate the route signatures at definition
time to resolve dependencies that are local to create_app().
"""
import asyncio
import logging
import os
import secrets
import time
from collections.abc import Callable
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
from pydantic import BaseModel, Field

from clipcura import __version__, rules
from clipcura.assistant import Assistant, AssistantBusy, OllamaError, explain_prompt
from clipcura.core import (
    config,
    events,
    licenses,
    logs,
    paths,
    previews,
    profiles,
    security,
    service,
    updates,
)
from clipcura.core.config import Concurrency
from clipcura.core.models import Paths
from clipcura.core.paths import REPO_ROOT
from clipcura.core.worker import Worker

Actor = Literal["human", "ai", "n8n"]
request_log = logging.getLogger("clipcura.api")
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


class UpdateSettings(BaseModel):
    check: bool


class QueueState(BaseModel):
    paused: bool


Lang = Literal["en", "cs"]


class AssistantSettings(BaseModel):
    enabled: bool
    url: str = ""
    model: str = ""
    key: str | None = None      # None keeps the stored key, "" removes it


class AssistantTest(BaseModel):
    url: str | None = None      # the values typed in Settings, before they are saved
    key: str | None = None


class AssistantMessage(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    lang: Lang = "en"
    conversation: str | None = None


class ExplainRequest(BaseModel):
    job_id: str | None = None
    log: dict | None = None
    lang: Lang = "en"


def public_config(cfg: config.Config) -> dict:
    """Settings as the GUI may see them: never the API token or the assistant's key."""
    data = cfg.model_dump(exclude={"token": True, "assistant": {"key"}})
    data["assistant"]["has_key"] = bool(cfg.assistant.key)
    return data


def _host_ok(host: str | None) -> bool:
    if not host:
        return False
    name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    return name.lower() in _LOOPBACK


def create_app(updater: updates.Updater | None = None, on_restart: Callable[[Path], None] | None = None,
               assistant: Assistant | None = None) -> FastAPI:
    """`on_restart` is given by the desktop app hosting this service: it quits and starts the given Clipcura.exe."""
    cfg = config.load_config()
    worker = Worker(cfg.concurrency.gpu, cfg.concurrency.cpu)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        service.recover(worker)  # jobs a killed earlier service left queued or half-done
        yield
        worker.stop()

    app = FastAPI(title="Clipcura", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.assistant = assistant or Assistant()

    @app.middleware("http")
    async def loopback_only(request: Request, call_next):
        if not _host_ok(request.headers.get("host")):
            return JSONResponse({"detail": "Invalid Host header"}, status_code=400)
        return await call_next(request)

    @app.middleware("http")
    async def log_failures(request: Request, call_next):
        # Only what went wrong, with who asked (#26): successful requests would drown the log. The path goes in
        # without its query, which may carry a one-time code.
        who = request.headers.get("x-clipcura-actor", "human")
        try:
            response = await call_next(request)
        except Exception:
            request_log.exception("%s %s by %s failed", request.method, request.url.path, who)
            raise
        if response.status_code >= 400:
            (request_log.error if response.status_code >= 500 else request_log.warning)(
                "%s %s by %s: %s", request.method, request.url.path, who, response.status_code)
        return response

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if not authorization or not secrets.compare_digest(authorization, f"Bearer {cfg.token}"):
            raise HTTPException(401, "Missing or invalid token")

    def actor(x_clipcura_actor: Annotated[Actor, Header()] = "human") -> Actor:
        return x_clipcura_actor

    def allowed(path: str) -> str:
        try:
            return str(security.ensure_allowed(path, config.load_config().allowed_roots))
        except security.PathNotAllowed as e:
            request_log.warning("Refused: %s", e)   # the request line alone would only say 403
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

    @api.get("/logs")
    def get_logs(limit: int = 200, level: Literal["debug", "info", "warning", "error"] = "info",
                 process: str | None = None, text: str | None = None) -> dict:
        """The log of every Clipcura process, newest first; people and assistants read the same (#26)."""
        return {"folder": str(logs.folder()),
                "entries": logs.read(limit=min(limit, 2000), level=level, process=process, text=text)}

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
        return public_config(config.load_config())

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
        return public_config(cfg_now)

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
        return public_config(config.allow_root(req.path))

    @api.delete("/config/roots")
    def remove_root(req: RootRequest, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        return public_config(config.disallow_root(req.path))

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

    # --- built-in assistant on an Ollama server (#27): only a person sets it up and gives it tasks ----------
    def assistant_status() -> dict:
        a = config.load_config().assistant
        return {"enabled": a.enabled, "url": a.url, "model": a.model, "has_key": bool(a.key),
                "conversations": [{k: v for k, v in c.public().items() if k != "transcript"}
                                  for c in sorted(app.state.assistant.conversations.values(),
                                                  key=lambda c: c.updated, reverse=True)]}

    @api.get("/assistant")
    def get_assistant() -> dict:
        return assistant_status()

    @api.put("/assistant/settings")
    def assistant_settings(req: AssistantSettings, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        cfg_now = config.load_config()
        url = req.url.strip()
        if req.enabled and not url.lower().startswith(("http://", "https://")):
            raise HTTPException(400, "The Ollama address must start with http:// or https://")
        cfg_now.assistant.enabled, cfg_now.assistant.url, cfg_now.assistant.model = req.enabled, url, req.model
        if req.key is not None:
            cfg_now.assistant.key = req.key.strip()
            logs.add_secret(cfg_now.assistant.key)
        config.save_config(cfg_now)
        request_log.info("Assistant %s (%s, model %s, %s)", "on" if req.enabled else "off", url or "no server",
                         req.model or "none", "with key" if cfg_now.assistant.key else "no key")
        return assistant_status()

    @api.post("/assistant/test")
    def assistant_test(req: AssistantTest, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        stored = config.load_config().assistant
        try:
            server = app.state.assistant.server(req.url if req.url is not None else stored.url,
                                                req.key if req.key is not None else stored.key)
            return {"version": server.version(), "models": server.models()}
        except OllamaError as e:
            raise HTTPException(502, str(e)) from e

    def start_task(text: str, lang: Lang, conversation: str | None = None, shown: str | None = None) -> dict:
        settings = config.load_config().assistant
        if not (settings.enabled and settings.url and settings.model):
            raise HTTPException(409, "Turn on the assistant and choose a model in Settings first.")
        try:
            conv = app.state.assistant.ask(text, lang, settings, conversation_id=conversation, shown=shown)
        except KeyError as e:
            raise HTTPException(404, f"Unknown conversation {conversation}") from e
        except AssistantBusy as e:
            raise HTTPException(409, "The assistant is still working on the previous message.") from e
        except OllamaError as e:
            raise HTTPException(400, str(e)) from e
        return {"conversation": conv.id}

    @api.post("/assistant/conversations", status_code=202)
    def assistant_message(req: AssistantMessage, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)   # an assistant handing tasks to another assistant would escape the person's view
        return start_task(req.text, req.lang, req.conversation)

    @api.get("/assistant/conversations/{conversation_id}")
    def assistant_conversation(conversation_id: str) -> dict:
        conv = app.state.assistant.get(conversation_id)
        if conv is None:
            raise HTTPException(404, f"Unknown conversation {conversation_id}")
        return conv.public()

    @api.post("/assistant/conversations/{conversation_id}/stop")
    def assistant_stop(conversation_id: str, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        return {"stopping": app.state.assistant.stop(conversation_id)}

    @api.post("/assistant/explain", status_code=202)
    def assistant_explain(req: ExplainRequest, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        if req.job_id:
            try:
                prompt, shown = explain_prompt("job", service.job_context(req.job_id), req.lang)
            except KeyError as e:
                raise HTTPException(404, str(e)) from e
        elif req.log:
            entry = {k: req.log.get(k) for k in ("ts", "level", "process", "source", "message", "exc")
                     if req.log.get(k)}
            prompt, shown = explain_prompt("log", entry, req.lang)
        else:
            raise HTTPException(400, "Give a job_id or a log entry.")
        return start_task(prompt, req.lang, shown=shown)

    # --- updates and missing parts (#22): anyone may look, only a person decides --------------------------
    updater = updater or updates.Updater()

    def update_status() -> dict:
        return {**updater.status(), "consent": config.load_config().update_check,
                "can_restart": on_restart is not None}

    def attempt(fn):
        try:
            return fn()
        except updates.UpdateError as e:
            raise HTTPException(409, str(e)) from e

    @api.get("/updates")
    def get_updates() -> dict:
        updater.maybe_check(config.load_config().update_check)   # daily, and only with consent
        return update_status()

    @api.post("/updates/settings")
    def update_settings(req: UpdateSettings, who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        cfg_now = config.load_config()
        cfg_now.update_check = req.check
        config.save_config(cfg_now)
        return update_status()

    @api.post("/updates/check")
    def check_updates(who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        attempt(updater.check)
        return update_status()

    @api.post("/updates/download", status_code=202)
    def download_update(who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        attempt(updater.download)
        return update_status()

    @api.post("/updates/install")
    def install_update(who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        if updater.kind == "installed":
            attempt(updater.run_installer)
            return {"action": "installer"}
        exe = attempt(updater.unpack_portable)
        if on_restart is None:   # a service without a window (clipcura serve): the person starts the new copy
            return {"action": "unpacked", "path": str(exe)}
        on_restart(exe)
        return {"action": "restart", "path": str(exe)}

    @api.post("/updates/webview2", status_code=202)
    def install_webview2(who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        attempt(updater.install_webview2)
        return update_status()

    @api.post("/updates/ffmpeg", status_code=202)
    def restore_ffmpeg(who: Annotated[Actor, Depends(actor)]) -> dict:
        human_only(who)
        attempt(updater.restore_ffmpeg)
        return update_status()

    @api.post("/restart")
    def restart(who: Annotated[Actor, Depends(actor)]) -> dict:
        """Start this copy again, e.g. to use the window once WebView2 is installed."""
        human_only(who)
        folder = paths.install_dir()
        if on_restart is None or folder is None:
            raise HTTPException(409, "Quit Clipcura from its icon and start it again.")
        on_restart(folder / "Clipcura.exe")
        return {"action": "restart"}

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
