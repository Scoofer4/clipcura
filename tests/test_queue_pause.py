"""Pausing the queue (#9, tray menu): running conversions finish, queued ones wait until the queue resumes."""
import pytest
from fastapi.testclient import TestClient

from clipsana.api.app import create_app
from clipsana.core import config, events
from clipsana.core.worker import Worker
from tests.test_worker import fake_jobs, wait_until  # noqa: F401 (fixture)

BASE = "http://127.0.0.1"


def test_paused_worker_starts_nothing_new_until_resumed(fake_jobs):  # noqa: F811
    state, release = fake_jobs
    worker = Worker(gpu_slots=0, cpu_slots=1)
    worker.start()
    try:
        worker.submit("a", "cpu")
        wait_until(lambda: state["running"] == 1)
        worker.pause()
        worker.submit("b", "cpu")
        release.set()
        wait_until(lambda: state["done"] == 1)  # the running job was not interrupted
        assert worker.paused
        assert state["done"] == 1 and state["running"] == 0
        worker.resume()
        wait_until(lambda: state["done"] == 2)
    finally:
        release.set()
        worker.stop()


@pytest.fixture
def api(tmp_path):
    cfg = config.load_config()
    with TestClient(create_app(), base_url=BASE) as client:
        client.headers["Authorization"] = f"Bearer {cfg.token}"
        yield client


def test_queue_pause_over_the_api_is_announced_and_human_only(api):
    seen = []
    unsubscribe = events.subscribe(seen.append)
    try:
        assert api.get("/api/queue").json() == {"paused": False}
        assert api.post("/api/queue", json={"paused": True}).json() == {"paused": True}
        assert api.get("/api/queue").json() == {"paused": True}
        assert any(e["type"] == "queue" and e["paused"] is True for e in seen)
        assert api.post("/api/queue", json={"paused": False}, headers={"X-Clipsana-Actor": "ai"}).status_code == 403
        assert api.post("/api/queue", json={"paused": False}).json() == {"paused": False}
    finally:
        unsubscribe()
