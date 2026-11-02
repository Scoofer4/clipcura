"""Run one plan item with ffmpeg: live progress, atomic output, cleanup on failure/cancel, CPU fallback."""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from clipsana.core.backends import find_ffmpeg
from clipsana.core.models import DecodePath, PlanItem

SPACE_MARGIN = 1.1  # size estimates are rough; keep headroom so a disk never fills up mid-encode


@dataclass
class Progress:
    percent: float
    fps: float
    speed: float
    eta_s: float | None
    out_time_s: float


class JobResult(BaseModel):
    job_id: str = ""
    status: Literal["done", "failed", "cancelled"]
    source: str
    output: str
    backend_used: DecodePath  # "cpu" also when a GPU recipe failed and the CPU fallback produced the file
    error: str = ""
    seconds: float = 0.0


def _num(value: str | None) -> float:
    try:
        return float((value or "0").rstrip("x"))
    except ValueError:  # ffmpeg prints "N/A" before the first frame
        return 0.0


def parse_progress(block: dict[str, str], duration: float) -> Progress:
    out_time = _num(block.get("out_time_us")) / 1e6
    speed = _num(block.get("speed"))
    percent = min(100.0, out_time / duration * 100) if duration > 0 else 0.0
    eta = (duration - out_time) / speed if speed > 0 and duration > 0 else None
    return Progress(round(percent, 1), _num(block.get("fps")), speed, eta, out_time)


def _partial_path(out: Path) -> Path:
    # Hidden name in the output folder: same volume, so the final rename is atomic.
    return out.with_name(f".{out.stem}.partial{out.suffix}")


def _free_bytes(path: Path) -> int:
    existing = next(p for p in [path, *path.parents] if p.exists())
    return shutil.disk_usage(existing).free


def _run_once(args: list[str], duration: float, on_progress: Callable[[Progress], None] | None,
              cancel: threading.Event | None) -> tuple[int, str, bool]:
    ffmpeg, _ = find_ffmpeg()
    proc = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error", "-nostats", "-progress", "pipe:1", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    stderr: list[str] = []
    cancelled = threading.Event()

    def drain_stderr() -> None:
        stderr.extend(proc.stderr)

    def watch_cancel() -> None:
        while proc.poll() is None:
            if cancel.wait(0.2):
                cancelled.set()
                proc.kill()
                return

    threading.Thread(target=drain_stderr, daemon=True).start()
    if cancel is not None:
        threading.Thread(target=watch_cancel, daemon=True).start()

    block: dict[str, str] = {}
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        block[key] = value
        if key == "progress":
            if on_progress and value == "continue":
                on_progress(parse_progress(block, duration))
            block = {}
    rc = proc.wait()
    return rc, "".join(stderr).strip(), cancelled.is_set()


def run_item(item: PlanItem, on_progress: Callable[[Progress], None] | None = None,
             cancel: threading.Event | None = None) -> JobResult:
    started = time.perf_counter()
    out = Path(item.output)

    def result(status, backend: DecodePath, error: str = "") -> JobResult:
        return JobResult(status=status, source=item.source, output=item.output, backend_used=backend,
                         error=error, seconds=round(time.perf_counter() - started, 2))

    needed = int(item.est_bytes * SPACE_MARGIN)
    if _free_bytes(out.parent) < needed:
        return result("failed", item.backend, f"Not enough free space: need ~{needed / 2**30:.1f} GB")

    out.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(out)
    attempts: list[tuple[DecodePath, list[str]]] = [(item.backend, item.args)]
    if item.fallback_args != item.args:  # any GPU decode, filter or encoder in the recipe
        attempts.append(("cpu", item.fallback_args))

    error = ""
    for backend, args in attempts:
        if args[-1] != item.output:
            raise ValueError("plan item arguments must end with the output path")
        rc, error, was_cancelled = _run_once([*args[:-1], str(partial)], item.duration, on_progress, cancel)
        if was_cancelled:
            partial.unlink(missing_ok=True)
            return result("cancelled", backend)
        if rc == 0:
            partial.replace(out)
            if on_progress:
                on_progress(Progress(100.0, 0.0, 0.0, 0.0, item.duration))
            return result("done", backend)
        partial.unlink(missing_ok=True)  # never leave a half-written file that looks finished
    return result("failed", attempts[-1][0], error[-500:] or f"ffmpeg exited with code {rc}")
