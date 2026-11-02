"""Executor: runs one plan item with progress, atomic output and cleanup on failure or cancel."""
import threading
from pathlib import Path

from clipsana.core import executor
from clipsana.core.models import PlanItem
from tests.conftest import needs_ffmpeg


def _item(src: Path, out: Path, vf: str = "format=yuv420p", **over) -> PlanItem:
    args = ["-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            "-f", "mp4", str(out)]
    data = {"source": str(src), "output": str(out), "args": args, "fallback_args": args, "backend": "cpu",
            "rule_ids": ["vfr"], "plan_hash": "h", "est_bytes": 1000, "duration": 2.0}
    return PlanItem(**(data | over))


def test_parse_progress_block():
    p = executor.parse_progress({"out_time_us": "1000000", "fps": "120.5", "speed": "4.1x"}, duration=4.0)
    assert (p.percent, p.fps, p.speed) == (25.0, 120.5, 4.1)
    assert round(p.eta_s, 2) == round(3.0 / 4.1, 2)


@needs_ffmpeg
def test_successful_run_reports_progress_and_leaves_only_final_output(raw_folder, tmp_path):
    src = raw_folder("ok.mp4") / "ok.mp4"
    out = tmp_path / "02_edit" / "ok_edit.mp4"
    seen = []
    result = executor.run_item(_item(src, out), on_progress=seen.append)
    assert result.status == "done", result.error
    assert out.is_file()
    assert seen and seen[-1].percent == 100.0
    assert [p.name for p in out.parent.iterdir()] == ["ok_edit.mp4"]  # no partial file left behind


@needs_ffmpeg
def test_failed_gpu_run_falls_back_to_cpu(raw_folder, tmp_path):
    src = raw_folder("ok.mp4") / "ok.mp4"
    out = tmp_path / "02_edit" / "ok_edit.mp4"
    good = _item(src, out)
    broken_gpu = good.model_copy(update={"backend": "cuda", "args": ["-hwaccel", "nonexistent", *good.args]})
    result = executor.run_item(broken_gpu)
    assert result.status == "done" and result.backend_used == "cpu"


@needs_ffmpeg
def test_failure_removes_partial_output(raw_folder, tmp_path):
    src = raw_folder("ok.mp4") / "ok.mp4"
    out = tmp_path / "02_edit" / "ok_edit.mp4"
    result = executor.run_item(_item(src, out, vf="nosuchfilter"))
    assert result.status == "failed" and "nosuchfilter" in result.error
    assert list(out.parent.iterdir()) == []


@needs_ffmpeg
def test_cancel_stops_job_and_removes_partial_output(raw_folder, tmp_path):
    src = raw_folder("big6k.mp4") / "big6k.mp4"
    out = tmp_path / "02_edit" / "big_edit.mp4"
    cancel = threading.Event()
    cancel.set()  # cancelled before the first progress report
    result = executor.run_item(_item(src, out, vf="scale=6144:3072,format=yuv420p"), cancel=cancel)
    assert result.status == "cancelled"
    assert not out.exists() and list(out.parent.iterdir()) == []


def test_not_enough_space_fails_before_starting(tmp_path):
    item = _item(tmp_path / "src.mp4", tmp_path / "out" / "o.mp4", est_bytes=10**18)
    result = executor.run_item(item)
    assert result.status == "failed" and "space" in result.error.lower()
