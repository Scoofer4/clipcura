"""Local HTTP API used by the GUI, MCP and later n8n. Same actions as the CLI, nothing more (CLAUDE.md §2).

Bound to 127.0.0.1 only, bearer token on every route except /api/health, Host header pinned to loopback
names (DNS rebinding), no CORS: the GUI is served from this same origin.

No `from __future__ import annotations` here: FastAPI must evaluate the route signatures at definition
time to resolve dependencies that are local to create_app().
"""
import asyncio
import secrets
from contextlib import asynccontextmanager
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
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from clipsana import __version__, rules
from clipsana.core import config, events, profiles, security, service
from clipsana.core.models import Paths
from clipsana.core.worker import Worker

Actor = Literal["human", "ai", "n8n"]
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}


class ScanRequest(BaseModel):
    path: str
    profile: str = "social-30"
    recursive: bool = False
    deep: bool | None = None


class PlanRequest(BaseModel):
    scan_id: str
    file_ids: list[int] | None = None
    paths: dict | None = None      # override measured paths, e.g. {"decode": "cpu"}


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
        yield
        worker.stop()

    app = FastAPI(title="Clipsana", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def loopback_only(request: Request, call_next):
        if not _host_ok(request.headers.get("host")):
            return JSONResponse({"detail": "Invalid Host header"}, status_code=400)
        return await call_next(request)

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if not authorization or not secrets.compare_digest(authorization, f"Bearer {cfg.token}"):
            raise HTTPException(401, "Missing or invalid token")

    def actor(x_clipsana_actor: Annotated[Actor, Header()] = "human") -> Actor:
        return x_clipsana_actor

    def allowed(path: str) -> str:
        try:
            return str(security.ensure_allowed(path, config.load_config().allowed_roots))
        except security.PathNotAllowed as e:
            raise HTTPException(403, str(e)) from e

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @api.get("/system")
    def system() -> dict:
        from clipsana.core.doctor import load_report, run_doctor
        report = load_report() or run_doctor(run_probes=False)
        return report.model_dump()

    @api.get("/profiles")
    def list_profiles() -> list[dict]:
        return [p.model_dump() for p in profiles.list_profiles()]

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
    def get_jobs(ids: str) -> list[dict]:
        return service.status([i for i in ids.split(",") if i])

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
        # Approval is the human checkpoint over AI actions; letting the requester approve would void it.
        if who != "human":
            raise HTTPException(403, "Only a human can approve or reject jobs")

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
        try:
            while True:
                await ws.send_json(await queue.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            unsubscribe()

    return app
