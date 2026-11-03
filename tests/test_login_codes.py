"""Opening the GUI in a browser (#23): the URL carries a one-time code, never the access key itself, so browser
history, the process list and logs hold nothing reusable."""
import pytest
from fastapi.testclient import TestClient

from clipcura.api import app as api_app
from clipcura.api.app import create_app
from clipcura.core import config

BASE = "http://127.0.0.1"


@pytest.fixture
def api():
    cfg = config.load_config()
    with TestClient(create_app(), base_url=BASE) as client:
        client.token = cfg.token
        yield client


def new_code(api) -> str:
    r = api.post("/api/login-codes", headers={"Authorization": f"Bearer {api.token}"})
    assert r.status_code == 200
    return r.json()["code"]


def test_code_is_exchanged_for_the_key_once(api):
    code = new_code(api)
    assert code != api.token
    r = api.post("/api/login", json={"code": code})
    assert r.status_code == 200 and r.json()["token"] == api.token
    assert api.post("/api/login", json={"code": code}).status_code == 401   # used up


def test_only_a_client_with_the_key_can_issue_codes(api):
    assert api.post("/api/login-codes").status_code == 401


def test_unknown_and_expired_codes_are_refused(api, monkeypatch):
    assert api.post("/api/login", json={"code": "guess"}).status_code == 401
    code = new_code(api)
    now = api_app.time.monotonic()
    monkeypatch.setattr(api_app.time, "monotonic", lambda: now + api_app.LOGIN_CODE_TTL_S + 1)
    assert api.post("/api/login", json={"code": code}).status_code == 401


def test_login_url_holds_the_code_in_the_fragment():
    from clipcura.api.server import login_url
    assert login_url("http://127.0.0.1:5000", "abc") == "http://127.0.0.1:5000/#code=abc"
