"""App data location and the end-to-end `clipsana doctor` command."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipsana.cli import app
from clipsana.core import backends, paths


def test_app_data_dir_honors_clipsana_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPSANA_HOME", str(tmp_path / "home"))
    assert paths.app_data_dir() == tmp_path / "home"


def test_app_data_dir_defaults_to_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPSANA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.app_data_dir() == tmp_path / "Clipsana"


def _ffmpeg_available() -> bool:
    try:
        backends.find_ffmpeg()
        return True
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not installed (run tools/fetch_ffmpeg.py)")
def test_doctor_json_reports_capabilities_and_saves_report(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPSANA_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["backend"] in {"cuda", "qsv", "cpu"}
    assert "libx264" in report["ffmpeg"]["encoders"]
    # CPU encoding must always work: the app has to be fully usable without a GPU.
    assert any(p["name"] == "libx264" and p["ok"] for p in report["ffmpeg"]["probes"])
    assert json.loads(Path(tmp_path / "doctor.json").read_text(encoding="utf-8"))["backend"] == report["backend"]
