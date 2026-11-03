"""Clipcura's log (#26): what every process does, from start to shutdown, in one place people and assistants read.

Each process writes its own file in `<app data>/logs/` (app.log, service.log, mcp.log, cli.log), one JSON object per
line, rotated at 5 MB. Separate files because several processes run at once (the window, an assistant's MCP server,
a CLI command) and Windows cannot rotate a file another process holds open. `read()` merges them, newest first.

The access key never reaches a log: it is masked together with any `Bearer …`, `token=…` and `code=…` value.
Hard crashes that bypass Python (a native library going down) land in `crash.log` through faulthandler.
"""
from __future__ import annotations

import atexit
import contextlib
import faulthandler
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clipcura import __version__
from clipcura.core import events, paths

MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 4
CRASH_FILE = "crash.log"
LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}

_MASKS = [(re.compile(r"(Bearer\s+)[^\s\"']+"), r"\1***"),
          (re.compile(r"((?:token|code)=)[^&\s\"']+"), r"\1***")]

log = logging.getLogger("clipcura")


def folder() -> Path:
    return paths.app_data_dir() / "logs"


def mask(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


def _entry(record: logging.LogRecord, process: str, secrets: tuple[str, ...]) -> dict[str, Any]:
    entry = {"ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
             "level": record.levelname, "process": process, "pid": record.process, "thread": record.threadName,
             "source": record.name, "message": mask(record.getMessage(), secrets)}
    if record.exc_info:
        entry["exc"] = mask(logging.Formatter().formatException(record.exc_info), secrets)
    return entry


class _JsonLines(logging.Formatter):
    def __init__(self, state: _State) -> None:
        super().__init__()
        self.state = state

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_entry(record, self.state.process, self.state.secrets), ensure_ascii=False)


class _Live(logging.Handler):
    """Every line also goes out as a `log` event, so the GUI's Log screen updates live."""

    def __init__(self, state: _State) -> None:
        super().__init__(logging.INFO)
        self.state = state
        self._busy = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._busy, "on", False):   # a subscriber that logs while handling a log event
            return
        self._busy.on = True
        try:
            events.publish("log", entry=_entry(record, self.state.process, self.state.secrets))
        finally:
            self._busy.on = False


@dataclass
class _State:
    process: str
    path: Path
    secrets: tuple[str, ...] = ()
    handlers: list[logging.Handler] = field(default_factory=list)
    undo: list = field(default_factory=list)


_state: _State | None = None
_lock = threading.Lock()


def setup(process: str) -> Path:
    """Start logging for this process ("app", "service", "mcp" or "cli"). Safe to call more than once."""
    global _state
    with _lock:
        if _state is not None:
            return _state.path
        logs = folder()
        logs.mkdir(parents=True, exist_ok=True)
        state = _State(process, logs / f"{process}.log")
        try:
            from clipcura.core.config import load_config
            state.secrets = (load_config().token,)
        except (OSError, ValueError):
            pass

        file = logging.handlers.RotatingFileHandler(state.path, maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                                    encoding="utf-8")
        file.setFormatter(_JsonLines(state))
        state.handlers = [file, _Live(state)]
        root = logging.getLogger()
        previous_level = root.level
        root.setLevel(logging.INFO)
        for h in state.handlers:
            root.addHandler(h)
        # Request-by-request lines would drown everything else (the tray asks for the queue every second);
        # failed requests are logged by the API itself.
        quiet = {name: logging.getLogger(name).level for name in ("uvicorn.access", "httpx", "httpcore")}
        for name in quiet:
            logging.getLogger(name).setLevel(logging.WARNING)
        logging.captureWarnings(True)

        previous_hook, previous_thread_hook = sys.excepthook, threading.excepthook

        def excepthook(kind, value, tb):
            log.critical("Unhandled error", exc_info=(kind, value, tb))
            previous_hook(kind, value, tb)

        sys.excepthook, threading.excepthook = excepthook, _thread_hook
        crash = None
        if not faulthandler.is_enabled():
            crash = (logs / CRASH_FILE).open("a", encoding="utf-8")
            faulthandler.enable(crash)
        unsubscribe = events.subscribe(_log_event)

        def undo() -> None:
            sys.excepthook, threading.excepthook = previous_hook, previous_thread_hook
            unsubscribe()
            if crash:
                faulthandler.disable()
                crash.close()
            for h in state.handlers:
                root.removeHandler(h)
                h.close()
            root.setLevel(previous_level)
            for name, level in quiet.items():
                logging.getLogger(name).setLevel(level)
            logging.captureWarnings(False)

        state.undo.append(undo)
        _state = state

    log.info("Clipcura %s started: %s copy, data in %s, pid %d, arguments %s", __version__, paths.install_kind(),
             paths.app_data_dir(), os.getpid(), " ".join(sys.argv[1:]) or "(none)")
    _report_unfinished_runs()
    marker = session_marker()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"process": process, "pid": os.getpid(),
                                  "started": datetime.now(UTC).isoformat(timespec="seconds")}), encoding="utf-8")
    atexit.register(stopped)
    return state.path


# --- runs that did not end normally ------------------------------------------------------------------------------
# Each running process keeps a marker in logs/sessions/ and removes it on a regular shutdown. A marker whose process
# is gone means a crash, a forced end or a power loss: the next start says so in the log. The log itself is never
# deleted, so the crashed run's last lines stay where they were (owner, 2026-11-03).
def session_marker() -> Path:
    return folder() / "sessions" / f"{_state.process if _state else 'unknown'}-{os.getpid()}.json"


def _report_unfinished_runs() -> None:
    for marker in sorted((folder() / "sessions").glob("*.json")):
        try:
            run = json.loads(marker.read_text(encoding="utf-8"))
            if run["pid"] == os.getpid() or _alive(run["pid"]):
                continue
            marker.unlink()   # whoever removes it reports it, so two starting processes do not both
        except (OSError, ValueError, KeyError):
            continue
        started = datetime.fromisoformat(run["started"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        log.error("The previous run of %s (pid %s, started %s) did not end normally: a crash, a forced end or a "
                  "power loss. Its last entries are in this log; crashes outside Python are in %s.",
                  run.get("process", "?"), run["pid"], started, CRASH_FILE)


def _alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _thread_hook(args: threading.ExceptHookArgs) -> None:
    """Uncaught errors in threads, logged under the failing thread's name (not the hook's)."""
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread else "?"
    record = logging.LogRecord("clipcura", logging.CRITICAL, __file__, 0, "Unhandled error in thread %s", (name,),
                               (args.exc_type, args.exc_value, args.exc_traceback))
    record.threadName = name
    logging.getLogger("clipcura").handle(record)


def stopped() -> None:
    """A regular shutdown: say so, and remove this run's marker."""
    if _state is None:
        return
    log.info("Clipcura stopped")
    with contextlib.suppress(OSError):
        session_marker().unlink(missing_ok=True)


def reset() -> None:
    """Undo setup (tests, or a process that hands over to another)."""
    global _state
    with _lock:
        if _state is None:
            return
        for undo in _state.undo:
            undo()
        _state = None


# --- what the core reports as events, in plain words -------------------------------------------------------------
def _log_event(e: dict) -> None:
    kind = e.get("type")
    if kind == "scan.done":
        logging.getLogger("clipcura.scans").info("Scan of %s by %s finished: %s", e.get("root"), e.get("actor"),
                                                 _summary(e.get("summary") or {}))
    elif kind == "plan.created":
        logging.getLogger("clipcura.plans").info("Plan %s for scan %s by %s: %s conversion(s)", e.get("plan_id"),
                                                 e.get("scan_id"), e.get("actor"), e.get("items"))
    elif kind == "job.status":
        status, jobs = e.get("status"), logging.getLogger("clipcura.jobs")
        where = f"{e.get('source') or '?'}" + (f" on {e['backend']}" if e.get("backend") else "")
        if status == "failed":
            jobs.error("Job %s failed (%s, requested by %s): %s", e.get("job_id"), where, e.get("actor"),
                       e.get("error") or "no message")
        else:
            jobs.info("Job %s %s (%s, requested by %s)", e.get("job_id"), status, where, e.get("actor"))
    elif kind == "audit":
        logging.getLogger("clipcura.audit").info("%s: %s %s -> %s", e.get("actor"), e.get("action"), e.get("target"),
                                                 e.get("result"))
    elif kind == "queue":
        logging.getLogger("clipcura.jobs").info("Queue %s", "paused" if e.get("paused") else "running")


def _summary(summary: dict) -> str:
    return ", ".join(f"{v} {k}" for k, v in summary.items() if v) or "no clips"


# --- reading -----------------------------------------------------------------------------------------------------
def read(limit: int = 200, level: str | None = None, process: str | None = None, text: str | None = None) -> list[dict]:
    """Entries of all processes, newest first. `level` is the lowest level shown ("warning" includes errors)."""
    minimum = LEVELS.get(level or "info", logging.INFO)
    needle = (text or "").lower()

    def matches(entry: dict) -> bool:
        if logging.getLevelName(entry.get("level", "INFO")) < minimum:
            return False
        if process and entry.get("process") != process:
            return False
        return not needle or needle in (entry.get("message", "") + entry.get("exc", "")).lower()

    logs = folder()
    current = [p for p in logs.glob("*.log") if p.name != CRASH_FILE]
    found = _collect(current, matches)
    if len(found) < limit:   # older, rotated files only when the current ones do not have enough
        found += _collect([p for p in logs.glob("*.log.*")], matches)
    # Lines of one millisecond keep their order within a file: reversed first, the stable sort keeps the later
    # line ahead.
    found.reverse()
    found.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return found[:limit]


def _collect(files: list[Path], matches) -> list[dict]:
    out = []
    for path in files:
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue   # a line cut short by a crash
                    if matches(entry):
                        out.append(entry)
        except OSError:
            continue
    return out
