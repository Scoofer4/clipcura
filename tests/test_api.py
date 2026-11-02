"""Local API: auth, whitelist, the scan -> plan -> apply cycle with live events, approvals and cancel."""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipsana.api.app import create_app
from clipsana.core import config
from tests.conftest import needs_ffmpeg

BASE = "http://127.0.0.1"


@pytest.fixture
def api(tmp_path):
    cfg = config.load_config()
    config.allow_root(tmp_path)
    app = create_app()
    with TestClient(app, base_url=BASE) as client:
        client.headers["Authorization"] = f"Bearer {cfg.token}"
        yield client


def wait_for(client, job_ids: list[str], states=("done", "failed", "cancelled", "rejected"), timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = client.get("/api/jobs", params={"ids": ",".join(job_ids)}).json()
        if all(j["status"] in states for j in jobs):
            return jobs
        time.sleep(0.2)
    raise TimeoutError(jobs)


def test_health_needs_no_token():
    with TestClient(create_app(), base_url=BASE) as client:
        assert client.get("/api/health").json()["status"] == "ok"


def test_requests_without_valid_token_are_rejected():
    with TestClient(create_app(), base_url=BASE) as client:
        assert client.get("/api/profiles").status_code == 401
        assert client.get("/api/profiles", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_foreign_host_header_is_rejected(api):
    # DNS rebinding: a web page resolving its own domain to 127.0.0.1 must not reach the API.
    assert api.get("/api/profiles", headers={"Host": "evil.example"}).status_code == 400


def test_event_stream_rejects_wrong_token_and_foreign_host(api):
    from starlette.websockets import WebSocketDisconnect
    token = api.headers["Authorization"].split()[1]
    for url, host in ((f"/api/events?token={token}", "evil.example"), ("/api/events?token=nope", "127.0.0.1")):
        with pytest.raises(WebSocketDisconnect), api.websocket_connect(url, headers={"Host": host}) as ws:
            ws.receive_json()


def test_profiles_and_rules_are_listed(api):
    assert "social-30" in {p["name"] for p in api.get("/api/profiles").json()}
    assert "vfr" in {r["id"] for r in api.get("/api/rules").json()}


def test_scan_outside_allowed_roots_is_forbidden(api, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    r = api.post("/api/scans", json={"path": str(outside)})
    assert r.status_code == 403


@needs_ffmpeg
def test_full_cycle_with_live_progress_events(api, raw_folder):
    raw = raw_folder("a44k.mp4")
    token = api.headers["Authorization"].split()[1]
    # TestClient ignores base_url for WebSockets and sends "testserver", which the API rightly refuses.
    with api.websocket_connect(f"/api/events?token={token}", headers={"Host": "127.0.0.1"}) as ws:
        scan = api.post("/api/scans", json={"path": str(raw)}).json()
        plan = api.post("/api/plans", json={"scan_id": scan["scan_id"], "paths": {"decode": "cpu"}}).json()
        jobs = api.post(f"/api/plans/{plan['plan_id']}/apply").json()["jobs"]
        assert [j["status"] for j in jobs] == ["queued"]
        seen = []
        while not any(e["type"] == "job.status" and e["status"] == "done" for e in seen):
            seen.append(ws.receive_json())
    types = {e["type"] for e in seen}
    assert {"scan.file", "job.status", "job.progress"} <= types
    assert all(e.get("actor") == "human" for e in seen if e["type"] == "job.status")
    (job,) = wait_for(api, [jobs[0]["id"]])
    assert job["status"] == "done" and Path(job["output"]).is_file()


@needs_ffmpeg
def test_ai_jobs_wait_for_human_approval(api, raw_folder):
    raw = raw_folder("a44k.mp4", "fps25.mp4")
    ai = {"X-Clipsana-Actor": "ai"}
    scan = api.post("/api/scans", json={"path": str(raw)}, headers=ai).json()
    plan = api.post("/api/plans", json={"scan_id": scan["scan_id"], "paths": {"decode": "cpu"}}, headers=ai).json()
    a, b = api.post(f"/api/plans/{plan['plan_id']}/apply", headers=ai).json()["jobs"]
    assert a["status"] == b["status"] == "awaiting_approval"
    # The AI can never approve its own request.
    assert api.post(f"/api/jobs/{a['id']}/approve", headers=ai).status_code == 403
    assert api.post(f"/api/jobs/{a['id']}/approve").json()["status"] == "queued"
    assert api.post(f"/api/jobs/{b['id']}/reject").json()["status"] == "rejected"
    done, rejected = wait_for(api, [a["id"], b["id"]])
    assert {done["status"], rejected["status"]} == {"done", "rejected"}


@needs_ffmpeg
def test_running_job_can_be_cancelled(api, raw_folder):
    raw = raw_folder("big6k.mp4")
    scan = api.post("/api/scans", json={"path": str(raw)}).json()
    plan = api.post("/api/plans", json={"scan_id": scan["scan_id"], "paths": {"decode": "cpu"}}).json()
    (job,) = api.post(f"/api/plans/{plan['plan_id']}/apply").json()["jobs"]
    wait_for(api, [job["id"]], states=("running", "done"))
    api.post(f"/api/jobs/{job['id']}/cancel")
    (final,) = wait_for(api, [job["id"]])
    assert final["status"] in {"cancelled", "done"}  # tiny clip may finish before the cancel lands
    if final["status"] == "cancelled":
        assert not Path(final["output"]).exists()
