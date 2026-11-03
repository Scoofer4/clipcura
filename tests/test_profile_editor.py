"""Profile editor (#7): people create and change profiles in Settings; invalid ones never reach the planner."""
import pytest
from fastapi.testclient import TestClient

from clipcura.api.app import create_app
from clipcura.core import config, profiles

BASE = "http://127.0.0.1"


@pytest.fixture
def api(tmp_path):
    cfg = config.load_config()
    config.allow_root(tmp_path)
    with TestClient(create_app(), base_url=BASE) as client:
        client.headers["Authorization"] = f"Bearer {cfg.token}"
        yield client


def social(**changes) -> dict:
    data = profiles.load_profile("social-30").model_dump()
    for key, value in changes.items():
        target = data
        *path, last = key.split(".")
        for p in path:
            target = target[p]
        target[last] = value
    return data


def test_list_says_where_each_profile_comes_from(api):
    listed = {p["name"]: p["source"] for p in api.get("/api/profiles").json()}
    assert listed["social-30"] == "builtin"


def test_new_profile_is_saved_and_used_for_scans(api, tmp_path):
    body = social(name="reels-25", label="Reels · 25 fps", fps=25)
    saved = api.put("/api/profiles/reels-25", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["source"] == "user"
    assert profiles.load_profile("reels-25").fps == 25
    (tmp_path / "raw").mkdir()
    assert api.post("/api/scans", json={"path": str(tmp_path / "raw"), "profile": "reels-25"}).status_code == 200


def test_editing_a_builtin_makes_an_override_that_can_be_reset(api):
    assert api.put("/api/profiles/social-30", json=social(fps=60)).json()["source"] == "edited"
    assert profiles.load_profile("social-30").fps == 60
    assert api.delete("/api/profiles/social-30").status_code == 200
    assert profiles.load_profile("social-30").fps == 30  # the bundled file was never touched


def test_builtin_profiles_cannot_be_deleted(api):
    assert api.delete("/api/profiles/hero-10bit").status_code == 400


@pytest.mark.parametrize(("change", "message"), [
    ({"output.codec": "h266_magic"}, "codec"),
    ({"output.codec": "dnxhr_hq", "output.container": "mp4"}, "container"),
    ({"output.folder": ".", "output.suffix": ""}, "overwrite"),
    ({"output.folder": "C:\\Windows\\Temp"}, "allowed"),
    ({"rules.disabled": ["no_such_rule"]}, "rule"),
    ({"fps": 0}, "fps"),
])
def test_invalid_profiles_are_refused_with_a_reason(api, change, message):
    r = api.put("/api/profiles/social-30", json=social(**change))
    assert r.status_code == 422
    assert message in r.json()["detail"].lower()
    assert profiles.load_profile("social-30").fps == 30


def test_name_must_be_a_plain_file_name_and_match_the_url(api):
    assert api.put("/api/profiles/..%5Cevil", json=social(name="..\\evil")).status_code in (404, 422)
    assert api.put("/api/profiles/a-b", json=social(name="other")).status_code == 422


def test_only_a_human_edits_profiles(api):
    ai = {"X-Clipcura-Actor": "ai"}
    assert api.put("/api/profiles/social-30", json=social(fps=60), headers=ai).status_code == 403
    assert api.delete("/api/profiles/social-30", headers=ai).status_code == 403
