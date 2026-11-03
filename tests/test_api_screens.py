"""API additions the GUI screens need: UI hosting, history, audit, settings, previews, job list."""
import time

import pytest
from fastapi.testclient import TestClient

from clipcura.api.app import create_app
from clipcura.core import config
from tests.conftest import needs_ffmpeg

BASE = "http://127.0.0.1"


@pytest.fixture
def ui_dir(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Clipcura</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("CLIPCURA_UI_DIR", str(dist))
    return dist


@pytest.fixture
def api(tmp_path, ui_dir):
    cfg = config.load_config()
    config.allow_root(tmp_path)
    with TestClient(create_app(), base_url=BASE) as client:
        client.headers["Authorization"] = f"Bearer {cfg.token}"
        yield client


def test_ui_is_served_from_the_same_origin_without_token(ui_dir):
    with TestClient(create_app(), base_url=BASE) as client:
        assert "Clipcura" in client.get("/").text
        assert client.get("/assets/app.js").text == "console.log(1)"
        # Client-side routes fall back to index.html so a reload on /jobs works.
        assert "Clipcura" in client.get("/jobs").text
        # ...but unknown API routes stay API errors, never HTML.
        assert client.get("/api/nope").status_code in (401, 404)


def test_ui_never_serves_files_outside_its_folder(ui_dir, tmp_path):
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    with TestClient(create_app(), base_url=BASE) as client:
        r = client.get("/..%2Fsecret.txt")
        assert "x" != r.text


def test_config_is_readable_without_token_value(api):
    data = api.get("/api/config").json()
    assert "token" not in data
    assert data["approval_mode"] is True


def test_only_a_human_changes_settings(api, tmp_path):
    folder = tmp_path / "footage"
    folder.mkdir()
    ai = {"X-Clipcura-Actor": "ai"}
    assert api.post("/api/config/roots", json={"path": str(folder)}, headers=ai).status_code == 403
    assert api.patch("/api/config", json={"approval_mode": False}, headers=ai).status_code == 403
    assert str(folder.resolve()) in api.post("/api/config/roots", json={"path": str(folder)}).json()["allowed_roots"]
    assert api.patch("/api/config", json={"approval_mode": False}).json()["approval_mode"] is False
    roots = api.request("DELETE", "/api/config/roots", json={"path": str(folder)}).json()["allowed_roots"]
    assert str(folder.resolve()) not in roots


def test_root_must_be_an_existing_folder(api, tmp_path):
    assert api.post("/api/config/roots", json={"path": str(tmp_path / "missing")}).status_code == 400


@needs_ffmpeg
def test_recent_scans_audit_and_previews(api, raw_folder):
    raw = raw_folder("a44k.mp4")
    scan = api.post("/api/scans", json={"path": str(raw)}).json()
    recent = api.get("/api/scans", params={"limit": 5}).json()
    assert recent[0]["scan_id"] == scan["scan_id"] and recent[0]["summary"]["fixable"] == 1
    # Scanning the same folder again replaces it in "recent folders" instead of listing it twice.
    again = api.post("/api/scans", json={"path": str(raw)}).json()
    recent = api.get("/api/scans", params={"limit": 5}).json()
    assert [r["scan_id"] for r in recent if r["root"] == scan["root"]] == [again["scan_id"]]

    file_id = scan["files"][0]["id"]
    before = api.get(f"/api/files/{file_id}/thumbnail", params={"at": 0.5})
    assert before.status_code == 200 and before.headers["content-type"] == "image/jpeg"
    assert before.content[:2] == b"\xff\xd8"  # JPEG magic

    plan = api.post("/api/plans", json={"scan_id": scan["scan_id"], "paths": {"decode": "cpu"}}).json()
    plan_again = api.get(f"/api/plans/{plan['plan_id']}").json()
    assert plan_again["items"][0]["item"]["args"] == plan["items"][0]["item"]["args"]
    item_id = plan["items"][0]["id"]
    after = api.get(f"/api/plan-items/{item_id}/preview", params={"at": 0.5})
    assert after.status_code == 200 and after.content[:2] == b"\xff\xd8"

    actions = [a["action"] for a in api.get("/api/audit", params={"limit": 10}).json()]
    assert {"scan", "plan"} <= set(actions)


@needs_ffmpeg
def test_jobs_list_shows_recent_jobs(api, raw_folder):
    raw = raw_folder("a44k.mp4")
    scan = api.post("/api/scans", json={"path": str(raw)}).json()
    plan = api.post("/api/plans", json={"scan_id": scan["scan_id"], "paths": {"decode": "cpu"}}).json()
    (job,) = api.post(f"/api/plans/{plan['plan_id']}/apply").json()["jobs"]
    deadline = time.monotonic() + 60
    while api.get(f"/api/jobs/{job['id']}").json()["status"] != "done" and time.monotonic() < deadline:
        time.sleep(0.2)
    listed = api.get("/api/jobs").json()
    assert listed[0]["id"] == job["id"] and listed[0]["status"] == "done"
    assert listed[0]["source"].endswith("a44k.mp4")


def test_file_outside_allowed_roots_has_no_preview(api, tmp_path_factory, raw_folder):
    # Even with a known file id, previews are refused once the folder is no longer allowed.
    raw = raw_folder("ok.mp4")
    scan = api.post("/api/scans", json={"path": str(raw)}).json()
    for root in config.load_config().allowed_roots:
        api.request("DELETE", "/api/config/roots", json={"path": root})
    r = api.get(f"/api/files/{scan['files'][0]['id']}/thumbnail")
    assert r.status_code == 403
