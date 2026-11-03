"""Updates through the API (#22): people decide; assistants and other clients can only look."""
import time

import pytest
from fastapi.testclient import TestClient

from clipcura.api.app import create_app
from clipcura.core import config
from tests.test_updates import FakeGitHub, make

AI = {"X-Clipcura-Actor": "ai"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    fake = FakeGitHub()
    restarts = []
    current = tmp_path / "apps" / "Clipcura"
    current.mkdir(parents=True)
    updater = make(fake, kind="portable", install_dir=current)
    with TestClient(create_app(updater=updater, on_restart=restarts.append), base_url="http://127.0.0.1") as api:
        api.headers["Authorization"] = f"Bearer {config.load_config().token}"
        yield api, fake, restarts


def test_first_start_asks_for_consent_and_checks_nothing(setup):
    api, fake, _ = setup
    status = api.get("/api/updates").json()
    assert status["consent"] is None and status["current"] and status["kind"] == "portable"
    assert fake.requests == []


def test_consent_is_a_human_setting(setup):
    api, _, _ = setup
    assert api.post("/api/updates/settings", json={"check": True}, headers=AI).status_code == 403
    assert api.post("/api/updates/settings", json={"check": False}).json()["consent"] is False
    assert config.load_config().update_check is False


def test_check_download_and_switch_to_the_new_portable_copy(setup, tmp_path):
    api, _, restarts = setup
    assert api.post("/api/updates/check").json()["latest"]["version"] == "0.2.0"
    assert api.post("/api/updates/download", headers=AI).status_code == 403
    assert api.post("/api/updates/download").status_code == 202
    for _ in range(100):
        if api.get("/api/updates").json()["download"]["state"] == "ready":
            break
        time.sleep(0.05)
    r = api.post("/api/updates/install")
    assert r.json()["action"] == "restart"
    assert restarts == [tmp_path / "apps" / "Clipcura-0.2.0" / "Clipcura.exe"]


def test_nothing_to_download_without_a_newer_version(setup):
    api, _, _ = setup
    r = api.post("/api/updates/download")
    assert r.status_code == 409 and "Check" in r.json()["detail"]


def test_assistants_cannot_install_missing_parts(setup):
    api, _, _ = setup
    assert api.post("/api/updates/webview2", headers=AI).status_code == 403
    assert api.post("/api/updates/ffmpeg", headers=AI).status_code == 403
