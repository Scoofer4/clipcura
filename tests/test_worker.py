"""Worker slots: concurrency changes in Settings apply at once, without a restart (#8)."""
import threading
import time

import pytest

from clipcura.core import service
from clipcura.core.worker import Worker


@pytest.fixture
def fake_jobs(monkeypatch):
    """run_job replaced by a job that blocks until released, recording how many run at the same time."""
    state = {"running": 0, "peak": 0, "done": 0}
    lock = threading.Lock()
    release = threading.Event()

    def run_job(job_id):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        release.wait(10)
        with lock:
            state["running"] -= 1
            state["done"] += 1

    monkeypatch.setattr(service, "run_job", run_job)
    return state, release


def wait_until(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.02)


def test_growing_the_cpu_slots_runs_more_jobs_at_once(fake_jobs):
    state, release = fake_jobs
    worker = Worker(gpu_slots=1, cpu_slots=1)
    worker.start()
    try:
        for i in range(3):
            worker.submit(f"j{i}", "cpu")
        wait_until(lambda: state["running"] == 1)
        worker.resize(gpu=1, cpu=3)
        wait_until(lambda: state["running"] == 3)
    finally:
        release.set()
        worker.stop()
    assert state["done"] == 3


def test_shrinking_lets_running_jobs_finish_then_runs_fewer(fake_jobs):
    state, release = fake_jobs
    worker = Worker(gpu_slots=1, cpu_slots=2)
    worker.start()
    try:
        worker.submit("a", "cpu")
        worker.submit("b", "cpu")
        wait_until(lambda: state["running"] == 2)
        worker.resize(gpu=1, cpu=1)
        assert state["running"] == 2  # nobody is interrupted
        release.set()
        wait_until(lambda: state["done"] == 2)
        release.clear()
        state["peak"] = 0
        for i in range(3):
            worker.submit(f"c{i}", "cpu")
        wait_until(lambda: state["running"] == 1)
        time.sleep(0.3)
        assert state["peak"] == 1
        release.set()
        wait_until(lambda: state["done"] == 5)
    finally:
        release.set()
        worker.stop()


def test_stop_ends_every_slot_thread(fake_jobs):
    _, release = fake_jobs
    release.set()
    worker = Worker(gpu_slots=2, cpu_slots=1)
    worker.start()
    worker.resize(gpu=1, cpu=3)
    worker.stop()
    assert not [t for t in worker._threads if t.is_alive()]


def test_jobs_still_queued_at_shutdown_are_left_for_the_next_start(fake_jobs):
    # They stay "queued" in the database, owned by this (soon dead) process; service.recover() resumes them.
    state, release = fake_jobs
    worker = Worker(gpu_slots=1, cpu_slots=1)
    worker.start()
    for i in range(4):
        worker.submit(f"q{i}", "cpu")
    wait_until(lambda: state["running"] == 1)
    threading.Timer(0.2, release.set).start()
    worker.stop()
    assert state["done"] == 1
