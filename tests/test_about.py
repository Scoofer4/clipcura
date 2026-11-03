"""About screen data (owner request 2026-11-03): who makes Clipcura, under which licence, and what it is built from."""
import pytest
from fastapi.testclient import TestClient

from clipcura.api.app import create_app
from clipcura.core import config

BASE = "http://127.0.0.1"


@pytest.fixture
def api():
    cfg = config.load_config()
    with TestClient(create_app(), base_url=BASE) as client:
        client.headers["Authorization"] = f"Bearer {cfg.token}"
        yield client


def test_about_names_the_owner_licence_and_source(api):
    about = api.get("/api/about").json()
    assert about["name"] == "Clipcura" and about["version"]
    assert about["owner"] == {"name": "Metaverse Media s.r.o.", "url": "https://www.metaversemedia.cz"}
    assert about["licence"] == "Apache-2.0"
    assert about["source"] == "https://github.com/Scoofer4/clipcura"


def test_about_lists_ffmpeg_first_and_every_python_package_with_its_licence(api):
    components = api.get("/api/about").json()["components"]
    names = [c["name"].lower() for c in components]
    assert names[0] == "ffmpeg" and components[0]["licence"].startswith("GPL")
    for expected in ("fastapi", "uvicorn", "pydantic", "pywebview", "pillow", "mcp", "starlette"):
        assert expected in names, expected  # starlette comes in through fastapi: the walk follows requirements
    assert all(c["licence"] and c["version"] for c in components)
    assert "pytest" not in names and "ruff" not in names  # development tools are not shipped


def test_licence_texts_travel_with_the_program(api):
    r = api.get("/api/about/notices")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "FFmpeg" in r.text and "Corresponding source code" in r.text
    assert "==== fastapi" in r.text.lower() or "==== FastAPI" in r.text
    assert "def " not in r.text  # licence files only, no source modules named license.py
