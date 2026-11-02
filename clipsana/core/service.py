"""Public core API: scan() -> plan() -> apply(), plus status() and cancel().

GUI (via the local API), MCP and CLI all call these same functions, so an AI can never do more than a
human can (CLAUDE.md §2). `actor` records who asked, for the audit log.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel

from clipsana import rules
from clipsana.core import backends, events, executor, planner, probe, profiles
from clipsana.core.db import Database
from clipsana.core.models import Backend, DecodePath, FileStatus, Issue, MediaInfo, Paths, PlanItem, Profile
from clipsana.core.worker import Slot, Worker

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".mkv", ".avi", ".mxf", ".insv", ".insp"}
_NOT_PROBED = {".insv", ".insp"}  # reported by the insv rule only; reading 360° originals adds nothing

_running: dict[str, threading.Event] = {}
_paths_cache: dict[str, Paths] = {}


class FileReport(BaseModel):
    id: int
    path: str
    status: FileStatus
    media: MediaInfo
    issues: list[Issue]


class ScanResult(BaseModel):
    scan_id: str
    root: str
    profile: str
    files: list[FileReport]
    summary: dict[str, int]


class PlanEntry(BaseModel):
    id: int
    file_id: int
    # pending | done (finished earlier) | exists (output not made by us) | unsupported (see reason)
    status: str
    item: PlanItem | None
    reason: str = ""


class PlanResult(BaseModel):
    plan_id: str
    scan_id: str
    backend: DecodePath
    paths: Paths
    items: list[PlanEntry]
    est_bytes: int


def file_status(issues: list[Issue]) -> FileStatus:
    if any(i.rule_id == "corrupt" for i in issues):
        return "error"
    if any(not i.auto_fixable and i.severity != "info" for i in issues):
        return "needs_human"
    return "fixable" if any(i.auto_fixable and rules.is_standalone(i.rule_id) for i in issues) else "ok"


def detect_paths() -> Paths:
    """Processing paths for this machine: from the last `clipsana doctor` (with measurements) if there is
    one, otherwise from quick capability probes (once per process)."""
    from clipsana.core.doctor import load_report

    report = load_report()
    if report is not None and report.ffmpeg is not None and report.ffmpeg.probes:
        return report.paths
    if "value" not in _paths_cache:
        try:
            _paths_cache["value"] = backends.choose_paths(backends.inspect_ffmpeg(run_probes=True))
        except FileNotFoundError:
            _paths_cache["value"] = Paths()
    return _paths_cache["value"]


def _list_files(root: Path, recursive: bool, output_dir: Path) -> list[Path]:
    candidates = root.rglob("*") if recursive else root.glob("*")
    return sorted(
        p for p in candidates
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS and not p.name.startswith(".")
        # Never treat our own outputs as new originals when the output folder sits inside the scan root.
        and not p.resolve().is_relative_to(output_dir))


def scan(path: Path | str, profile: str = "social-30", recursive: bool = False, deep: bool | None = None,
         actor: str = "human", on_file: Callable[[FileReport], None] | None = None) -> ScanResult:
    root = Path(path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {root}")
    prof = profiles.load_profile(profile)
    deep = prof.rules.vfr_deep_check if deep is None else deep
    output_dir = (root / prof.output.folder).resolve()
    active_rules = rules.load_rules(prof)

    reports: list[FileReport] = []
    with Database() as db:
        scan_id = db.create_scan(str(root), prof.name, recursive, deep, actor)
        # Outputs made earlier (possibly for another scan root) are results, not new originals.
        for f in (p for p in _list_files(root, recursive, output_dir) if not db.is_known_output(str(p))):
            if f.suffix.lower() in _NOT_PROBED:
                stat = f.stat()
                media = MediaInfo(path=str(f), size=stat.st_size, mtime=stat.st_mtime)
            else:
                media = probe.probe(f, deep=deep)
            issues = [i for r in active_rules if (i := r.detect(media, prof)) is not None]
            status = file_status(issues)
            file_id = db.add_file(scan_id, str(f), status, media.model_dump(), [asdict(i) for i in issues])
            report = FileReport(id=file_id, path=str(f), status=status, media=media, issues=issues)
            reports.append(report)
            events.publish("scan.file", scan_id=scan_id, file_id=file_id, path=str(f), status=status,
                           issues=[i.rule_id for i in issues], actor=actor)
            if on_file:
                on_file(report)
        summary = {s: sum(r.status == s for r in reports) for s in ("ok", "fixable", "needs_human", "error")}
        db.finish_scan(scan_id, summary)
        _audit(db, actor, "scan", str(root), f"{len(reports)} files")
        events.publish("scan.done", scan_id=scan_id, root=str(root), summary=summary, actor=actor)
    return ScanResult(scan_id=scan_id, root=str(root), profile=prof.name, files=reports, summary=summary)


def get_scan(scan_id: str) -> ScanResult:
    with Database() as db:
        row = db.get_scan(scan_id)
        if row is None:
            raise KeyError(f"Unknown scan {scan_id}")
        files = [FileReport(id=f["id"], path=f["path"], status=f["status"],
                            media=MediaInfo.model_validate_json(f["media"]),
                            issues=[Issue(**i) for i in json.loads(f["issues"])]) for f in db.get_files(scan_id)]
    return ScanResult(scan_id=scan_id, root=row["root"], profile=row["profile"], files=files,
                      summary=json.loads(row["summary"] or "{}"))


def plan(scan_id: str, file_ids: list[int] | None = None, backend: Backend | None = None,
         actor: str = "human", paths: Paths | None = None) -> PlanResult:
    """Build commands for the scan's fixable files. `paths` (or just a decode `backend`) overrides the
    measured choice, e.g. for tests or to force the CPU."""
    report = get_scan(scan_id)
    prof: Profile = profiles.load_profile(report.profile)
    if paths is None:
        # Intel GPUs decode through D3D11VA (see DecodePath); QSV remains their encoder.
        paths = Paths(decode="d3d11va" if backend == "qsv" else backend, encode=backend) if backend \
            else detect_paths()
    backend = paths.decode
    root = Path(report.root)
    entries: list[PlanEntry] = []
    with Database() as db:
        plan_id = db.create_plan(scan_id, backend, actor, paths.model_dump())
        for f in report.files:
            if f.status != "fixable" or (file_ids is not None and f.id not in file_ids):
                continue
            try:
                item = planner.build_item(f.media, f.issues, prof, backend, root, paths)
            except planner.UnsupportedError as e:
                entry_id = db.add_plan_item(plan_id, f.id, "unsupported", "", "", None)
                entries.append(PlanEntry(id=entry_id, file_id=f.id, status="unsupported", item=None,
                                         reason=str(e)))
                continue
            if item is None:
                continue
            if db.is_done(item.plan_hash, item.output) and Path(item.output).exists():
                status = "done"   # same input, same recipe, output still there: nothing to do
            elif Path(item.output).exists():
                status = "exists"
            else:
                status = "pending"
            entry_id = db.add_plan_item(plan_id, f.id, status, item.plan_hash, item.output, item.model_dump())
            entries.append(PlanEntry(id=entry_id, file_id=f.id, status=status, item=item))
        _audit(db, actor, "plan", scan_id, f"{len(entries)} items")
        events.publish("plan.created", plan_id=plan_id, scan_id=scan_id, items=len(entries), actor=actor)
    return PlanResult(plan_id=plan_id, scan_id=scan_id, backend=backend, paths=paths, items=entries,
                      est_bytes=sum(e.item.est_bytes for e in entries if e.status == "pending" and e.item))


def _audit(db: Database, actor: str, action: str, target: str, result: str) -> None:
    db.audit(actor, action, target, result)
    events.publish("audit", actor=actor, action=action, target=target, result=result)


def _job_event(db: Database, job_id: str) -> None:
    job = db.get_job(job_id)
    item = db.get_plan_item(job["plan_item_id"])
    source = json.loads(item["item"])["source"] if item and item["item"] != "null" else ""
    events.publish("job.status", job_id=job_id, status=job["status"], actor=job["actor"], source=source,
                   output=job["output"], error=job["error"] or "", backend=job["backend"] or "")


def _create_jobs(plan_id: str, actor: str, force: bool, awaiting: bool) -> list[tuple[str, PlanItem]]:
    created: list[tuple[str, PlanItem]] = []
    with Database() as db:
        if db.get_plan(plan_id) is None:
            raise KeyError(f"Unknown plan {plan_id}")
        for row in db.get_plan_items(plan_id):
            if row["status"] not in ("pending", "exists") or (row["status"] == "exists" and not force):
                continue
            item = PlanItem.model_validate_json(row["item"])
            job_id = db.create_job(row["id"], item.plan_hash, item.output, actor,
                                   status="awaiting_approval" if awaiting else "queued")
            _audit(db, actor, "request_apply" if awaiting else "apply", item.source,
                   "awaiting_approval" if awaiting else "queued")
            _job_event(db, job_id)
            created.append((job_id, item))
    return created


def run_job(job_id: str, on_progress: Callable[[str, executor.Progress], None] | None = None,
            ) -> executor.JobResult | None:
    """Run one queued job to the end. Returns None if the job is no longer queued (cancelled, rejected)."""
    with Database() as db:
        if not db.set_job_status_if(job_id, "queued", "running"):
            return None
        cancel_event = _running[job_id] = threading.Event()
        job = db.get_job(job_id)
        item = PlanItem.model_validate_json(db.get_plan_item(job["plan_item_id"])["item"])
        _job_event(db, job_id)
        last = [-1.0]

        def progress(p: executor.Progress) -> None:
            if p.percent - last[0] >= 1 or p.percent == 100:   # throttle DB writes and events
                last[0] = p.percent
                db.update_job(job_id, progress=p.percent)
                events.publish("job.progress", job_id=job_id, percent=p.percent, fps=p.fps, speed=p.speed,
                               eta_s=p.eta_s)
            if on_progress:
                on_progress(job_id, p)

        try:
            result = executor.run_item(item, on_progress=progress, cancel=cancel_event)
        except Exception as e:  # noqa: BLE001 - whatever happens, a job must not stay "running" forever
            result = executor.JobResult(status="failed", source=item.source, output=item.output,
                                        backend_used=item.backend, error=f"internal error: {e}")
        finally:
            _running.pop(job_id, None)
        result.job_id = job_id
        db.update_job(job_id, status=result.status, backend=result.backend_used, error=result.error,
                      **({"progress": 100.0} if result.status == "done" else {}))
        _audit(db, job["actor"], "job_finished", item.source, result.status)
        _job_event(db, job_id)
    return result


def apply(plan_id: str, actor: str = "human", force: bool = False,
          on_progress: Callable[[str, executor.Progress], None] | None = None) -> list[executor.JobResult]:
    """Run the plan's pending items now, one after another (CLI). The API queues them via enqueue()."""
    results = []
    for job_id, _ in _create_jobs(plan_id, actor, force, awaiting=False):
        if (result := run_job(job_id, on_progress)) is not None:
            results.append(result)
    return results


def enqueue(plan_id: str, worker: Worker, actor: str = "human", force: bool = False,
            approval_mode: bool = True) -> list[dict]:
    """Queue the plan's items on the worker. Requests from anyone but a human wait for approval when the
    approval mode is on (default), so an AI can prepare work but never start it on its own."""
    awaiting = approval_mode and actor != "human"
    created = _create_jobs(plan_id, actor, force, awaiting)
    # Snapshot before handing jobs to the worker: a fast worker may already have started one, and the answer
    # to "queue this" must describe the state at queueing time, not a race with the worker thread.
    snapshot = status([job_id for job_id, _ in created])
    if not awaiting:
        for job_id, item in created:
            worker.submit(job_id, _slot(item))
    return snapshot


def get_plan(plan_id: str) -> PlanResult:
    with Database() as db:
        row = db.get_plan(plan_id)
        if row is None:
            raise KeyError(f"Unknown plan {plan_id}")
        entries = []
        for r in db.get_plan_items(plan_id):
            item = None if r["item"] == "null" else PlanItem.model_validate_json(r["item"])
            entries.append(PlanEntry(id=r["id"], file_id=r["file_id"], status=r["status"], item=item))
    paths = Paths.model_validate(json.loads(row["paths"] or "{}"))
    return PlanResult(plan_id=plan_id, scan_id=row["scan_id"], backend=row["backend"], paths=paths, items=entries,
                      est_bytes=sum(e.item.est_bytes for e in entries if e.status == "pending" and e.item))


def recent_scans(limit: int = 10) -> list[dict]:
    """Latest scans for the start screen's "recent folders" (newest first)."""
    with Database() as db:
        rows = db.recent_scans(limit * 5)
    seen: set[str] = set()
    out = []
    for r in rows:  # newest first: keep only the latest scan of each folder
        key = r["root"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"scan_id": r["id"], "root": r["root"], "profile": r["profile"], "created_at": r["created_at"],
                    "actor": r["actor"], "summary": json.loads(r["summary"] or "{}")})
        if len(out) == limit:
            break
    return out


def audit_log(limit: int = 100) -> list[dict]:
    with Database() as db:
        return [dict(r) for r in db.audit_log(limit)]


def recent_jobs(limit: int = 50) -> list[dict]:
    with Database() as db:
        rows = db.recent_jobs(limit)
    jobs = []
    for r in rows:
        job = {k: r[k] for k in r.keys() if k != "item"}  # noqa: SIM118 - sqlite3.Row has no dict iteration
        item = json.loads(r["item"]) if r["item"] and r["item"] != "null" else {}
        job |= {"source": item.get("source", ""), "duration": item.get("duration", 0),
                "rule_ids": item.get("rule_ids", [])}
        jobs.append(job)
    return jobs


def file_source(file_id: int) -> Path:
    with Database() as db:
        row = db.get_file(file_id)
    if row is None:
        raise KeyError(f"Unknown file {file_id}")
    return Path(row["path"])


def plan_item_preview_source(plan_item_id: int) -> tuple[Path, str]:
    """Source path and the filter chain the plan will apply, for the "after" preview."""
    from clipsana.core.previews import filters_from_args
    with Database() as db:
        row = db.get_plan_item(plan_item_id)
    if row is None or row["item"] == "null":
        raise KeyError(f"Unknown plan item {plan_item_id}")
    item = PlanItem.model_validate_json(row["item"])
    # The CPU recipe: previews must not compete with a running job for the GPU.
    return Path(item.source), filters_from_args(item.fallback_args)


def plan_outputs(plan_id: str, force: bool = False) -> list[str]:
    """Output paths that applying the plan would write (for the API's folder whitelist check)."""
    with Database() as db:
        return [r["output"] for r in db.get_plan_items(plan_id)
                if r["status"] == "pending" or (r["status"] == "exists" and force)]


def _slot(item: PlanItem) -> Slot:
    return "gpu" if item.args != item.fallback_args else "cpu"


def approve(job_id: str, worker: Worker, actor: str = "human") -> dict:
    with Database() as db:
        if not db.set_job_status_if(job_id, "awaiting_approval", "queued"):
            raise ValueError(f"Job {job_id} is not awaiting approval")
        item = PlanItem.model_validate_json(db.get_plan_item(db.get_job(job_id)["plan_item_id"])["item"])
        _audit(db, actor, "approve", item.source, "queued")
        _job_event(db, job_id)
    snapshot = status([job_id])[0]  # same reasoning as enqueue(): report the state we created
    worker.submit(job_id, _slot(item))
    return snapshot


def recover(worker: Worker) -> list[str]:
    """Take over the jobs of a Clipsana process that ended without a clean shutdown (killed, crashed, power
    loss). Its ffmpeg died with it, so a half-written output is removed and the job runs again; queued jobs
    go to this worker. Jobs of a process that still runs are left alone, and requests awaiting approval keep
    waiting. Returns the ids handed to the worker."""
    from clipsana.core.sysinfo import pid_alive
    taken = []
    with Database() as db:
        for job in db.owned_jobs():
            if job["owner_pid"] == os.getpid() or pid_alive(job["owner_pid"]):
                continue
            if not db.set_job_status_if(job["id"], job["status"], "queued"):
                continue  # changed under us
            item = PlanItem.model_validate_json(db.get_plan_item(job["plan_item_id"])["item"])
            if job["status"] == "running":
                executor.partial_path(Path(item.output)).unlink(missing_ok=True)
                db.update_job(job["id"], progress=0.0)
                _audit(db, "system", "job_recovered", item.source, "queued")
            worker.submit(job["id"], _slot(item))
            taken.append(job["id"])
    return taken


def reject(job_id: str, actor: str = "human") -> dict:
    with Database() as db:
        if not db.set_job_status_if(job_id, "awaiting_approval", "rejected"):
            raise ValueError(f"Job {job_id} is not awaiting approval")
        db.update_job(job_id, status="rejected")
        _audit(db, actor, "reject", job_id, "rejected")
        _job_event(db, job_id)
    return status([job_id])[0]


def status(job_ids: list[str]) -> list[dict]:
    with Database() as db:
        rows = {r["id"]: dict(r) for r in db.get_jobs(job_ids)}
    return [rows[j] for j in job_ids if j in rows]


def cancel(job_id: str, actor: str = "human") -> bool:
    """Stop a running job (its partial output is removed) or withdraw a queued/awaiting one."""
    with Database() as db:
        event = _running.get(job_id)
        if event is not None:
            event.set()
        elif not (db.set_job_status_if(job_id, "queued", "cancelled")
                  or db.set_job_status_if(job_id, "awaiting_approval", "cancelled")):
            return False
        else:
            _job_event(db, job_id)
        _audit(db, actor, "cancel", job_id, "requested")
    return True


def cancel_all_running() -> None:
    for event in list(_running.values()):
        event.set()
