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
    monkeypatch.setenv("CLIPSANA_BENCH_FAST", "1")
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["backend"] in {"cuda", "qsv", "cpu"}
    assert "libx264" in report["ffmpeg"]["encoders"]
    # CPU encoding must always work: the app has to be fully usable without a GPU.
    assert any(p["name"] == "libx264" and p["ok"] for p in report["ffmpeg"]["probes"])
    assert json.loads(Path(tmp_path / "doctor.json").read_text(encoding="utf-8"))["backend"] == report["backend"]
    # Measurements for issue #5: the CPU paths always work, so they always have a speed.
    bench = report["ffmpeg"]["benchmarks"]
    assert bench["decode"]["cpu"] > 0 and bench["scale"]["cpu"] > 0 and bench["tonemap"]["zscale"] > 0
    assert report["paths"]["scale"] in {"cpu", "scale_cuda", "libplacebo"}


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not installed (run tools/fetch_ffmpeg.py)")
def test_quality_calibration_compares_each_working_gpu_encoder_with_its_cpu_equivalent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPSANA_BENCH_FAST", "1")
    from clipsana.core import planner

    info = backends.inspect_ffmpeg(run_probes=True)
    quality = backends.calibrate_encoders(info, tmp_path)
    gpu = {e for e in planner.GPU_QUALITY if info.works(e)}
    assert set(quality) == gpu  # empty on a machine without a GPU encoder (CI)
    for result in quality.values():
        assert result.cpu_encoder in {"libx264", "libx265"}
        assert result.quality is None or result.delta >= -backends.QUALITY_MARGIN[result.metric]
