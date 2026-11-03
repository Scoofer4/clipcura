"""Jobs left behind by a service that was killed (power loss, crash, its MCP session closed) run again."""
import subprocess
import sys
from pathlib import Path

from clipcura.core import executor, service
from clipcura.core.db import Database
from tests.conftest import needs_ffmpeg


class RecordingWorker:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, job_id: str, slot: str) -> None:
        self.submitted.append(job_id)


def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def queue_jobs(raw: Path, actor: str = "human") -> list[str]:
    scan = service.scan(raw)
    plan = service.plan(scan.scan_id, backend="cpu")
    return [j["id"] for j in service.enqueue(plan.plan_id, RecordingWorker(), actor=actor)]


def set_job(job_id: str, **fields) -> None:
    with Database() as db:
        db.update_job(job_id, **fields)


@needs_ffmpeg
def test_interrupted_running_job_loses_its_partial_file_and_runs_again(raw_folder):
    (job_id,) = queue_jobs(raw_folder("a44k.mp4"))
    output = Path(service.status([job_id])[0]["output"])
    partial = executor.partial_path(output)
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"half a file")
    set_job(job_id, status="running", owner_pid=dead_pid())

    worker = RecordingWorker()
    assert service.recover(worker) == [job_id]
    assert worker.submitted == [job_id]
    assert not partial.exists()
    assert service.status([job_id])[0]["status"] == "queued"


@needs_ffmpeg
def test_queued_jobs_of_a_dead_service_are_picked_up(raw_folder):
    (job_id,) = queue_jobs(raw_folder("a44k.mp4"))
    set_job(job_id, owner_pid=dead_pid())
    worker = RecordingWorker()
    assert service.recover(worker) == [job_id]
    assert worker.submitted == [job_id]


@needs_ffmpeg
def test_jobs_of_a_live_process_are_left_alone(raw_folder):
    # A `clipcura apply` running in another console owns its jobs; a service starting meanwhile must not steal
    # them or delete the file its ffmpeg is writing.
    (job_id,) = queue_jobs(raw_folder("a44k.mp4"))
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        set_job(job_id, status="running", owner_pid=other.pid)
        assert service.recover(RecordingWorker()) == []
        assert service.status([job_id])[0]["status"] == "running"
    finally:
        other.kill()


@needs_ffmpeg
def test_requests_awaiting_approval_keep_waiting(raw_folder):
    (job_id,) = queue_jobs(raw_folder("a44k.mp4"), actor="ai")
    worker = RecordingWorker()
    assert service.recover(worker) == []
    assert service.status([job_id])[0]["status"] == "awaiting_approval"
