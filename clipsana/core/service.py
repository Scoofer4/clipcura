"""Public core API: scan() -> plan() -> apply(), plus status() and cancel().

GUI (via the local API), MCP and CLI all call these same functions, so an AI can never do more than a
human can (CLAUDE.md §2). `actor` records who asked, for the audit log.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel

from clipsana import rules
from clipsana.core import backends, executor, planner, probe, profiles
from clipsana.core.db import Database
from clipsana.core.models import Backend, FileStatus, Issue, MediaInfo, PlanItem, Profile

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".mkv", ".avi", ".mxf", ".insv", ".insp"}
_NOT_PROBED = {".insv", ".insp"}  # reported by the insv rule only; reading 360° originals adds nothing

_running: dict[str, threading.Event] = {}
_backend_cache: dict[str, Backend] = {}


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
    status: str            # pending | done (finished earlier) | exists (output not made by us)
    item: PlanItem


class PlanResult(BaseModel):
    plan_id: str
    scan_id: str
    backend: Backend
    items: list[PlanEntry]
    est_bytes: int


def file_status(issues: list[Issue]) -> FileStatus:
    if any(i.rule_id == "corrupt" for i in issues):
        return "error"
    if any(not i.auto_fixable and i.severity != "info" for i in issues):
        return "needs_human"
    return "fixable" if any(i.auto_fixable and rules.is_standalone(i.rule_id) for i in issues) else "ok"


def detect_backend() -> Backend:
    """Best acceleration backend on this machine (probed once per process)."""
    if "value" not in _backend_cache:
        try:
            _backend_cache["value"] = backends.choose_backend(backends.inspect_ffmpeg(run_probes=True))
        except FileNotFoundError:
            _backend_cache["value"] = "cpu"
    return _backend_cache["value"]


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
            if on_file:
                on_file(report)
        summary = {s: sum(r.status == s for r in reports) for s in ("ok", "fixable", "needs_human", "error")}
        db.finish_scan(scan_id, summary)
        db.audit(actor, "scan", str(root), f"{len(reports)} files")
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
         actor: str = "human") -> PlanResult:
    report = get_scan(scan_id)
    prof: Profile = profiles.load_profile(report.profile)
    backend = backend or detect_backend()
    root = Path(report.root)
    entries: list[PlanEntry] = []
    with Database() as db:
        plan_id = db.create_plan(scan_id, backend, actor)
        for f in report.files:
            if f.status != "fixable" or (file_ids is not None and f.id not in file_ids):
                continue
            item = planner.build_item(f.media, f.issues, prof, backend, root)
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
        db.audit(actor, "plan", scan_id, f"{len(entries)} items")
    return PlanResult(plan_id=plan_id, scan_id=scan_id, backend=backend, items=entries,
                      est_bytes=sum(e.item.est_bytes for e in entries if e.status == "pending"))


def apply(plan_id: str, actor: str = "human", force: bool = False,
          on_progress: Callable[[str, executor.Progress], None] | None = None) -> list[executor.JobResult]:
    """Run the plan's pending items (and, with force, overwrite outputs we did not create)."""
    results: list[executor.JobResult] = []
    with Database() as db:
        if db.get_plan(plan_id) is None:
            raise KeyError(f"Unknown plan {plan_id}")
        for row in db.get_plan_items(plan_id):
            if row["status"] == "done" or (row["status"] == "exists" and not force):
                continue
            item = PlanItem.model_validate_json(row["item"])
            job_id = db.create_job(row["id"], item.plan_hash, item.output, actor)
            cancel = _running[job_id] = threading.Event()
            last = [-1.0]

            def progress(p: executor.Progress, job_id=job_id, last=last) -> None:
                if p.percent - last[0] >= 1 or p.percent == 100:   # throttle DB writes
                    last[0] = p.percent
                    db.update_job(job_id, progress=p.percent)
                if on_progress:
                    on_progress(job_id, p)

            try:
                result = executor.run_item(item, on_progress=progress, cancel=cancel)
            finally:
                _running.pop(job_id, None)
            result.job_id = job_id
            db.update_job(job_id, status=result.status, backend=result.backend_used, error=result.error,
                          **({"progress": 100.0} if result.status == "done" else {}))
            db.audit(actor, "apply", item.source, result.status)
            results.append(result)
    return results


def status(job_ids: list[str]) -> list[dict]:
    with Database() as db:
        return [dict(r) for r in db.get_jobs(job_ids)]


def cancel(job_id: str, actor: str = "human") -> bool:
    event = _running.get(job_id)
    if event is None:
        return False
    event.set()
    with Database() as db:
        db.audit(actor, "cancel", job_id, "requested")
    return True
