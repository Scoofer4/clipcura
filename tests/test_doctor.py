"""App data location and the end-to-end `clipcura doctor` command."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipcura.cli import app
from clipcura.core import backends, paths


def test_app_data_dir_honors_clipcura_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPCURA_HOME", str(tmp_path / "home"))
    assert paths.app_data_dir() == tmp_path / "home"


def test_app_data_dir_defaults_to_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPCURA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.app_data_dir() == tmp_path / "Clipcura"


def test_data_of_the_old_name_moves_to_the_new_folder_once(tmp_path, monkeypatch):
    # The project was called Clipsana until 2026-11-03 (#19): settings, token, database and profiles move along.
    monkeypatch.delenv("CLIPCURA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "Clipsana" / "profiles").mkdir(parents=True)
    (tmp_path / "Clipsana" / "config.json").write_text("{}", encoding="utf-8")
    assert paths.migrate_legacy_app_data() == tmp_path / "Clipcura"
    assert (tmp_path / "Clipcura" / "config.json").is_file() and (tmp_path / "Clipcura" / "profiles").is_dir()
    assert not (tmp_path / "Clipsana").exists()
    assert paths.migrate_legacy_app_data() is None  # nothing left to move


def test_existing_new_folder_is_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPCURA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "Clipsana").mkdir()
    (tmp_path / "Clipcura").mkdir()
    assert paths.migrate_legacy_app_data() is None
    assert (tmp_path / "Clipsana").is_dir()


def _ffmpeg_available() -> bool:
    try:
        backends.find_ffmpeg()
        return True
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not installed (run tools/fetch_ffmpeg.py)")
def test_doctor_json_reports_capabilities_and_saves_report(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPCURA_HOME", str(tmp_path))
    monkeypatch.setenv("CLIPCURA_BENCH_FAST", "1")
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
    monkeypatch.setenv("CLIPCURA_BENCH_FAST", "1")
    from clipcura.core import planner

    info = backends.inspect_ffmpeg(run_probes=True)
    quality = backends.calibrate_encoders(info, tmp_path)
    gpu = {e for e in planner.GPU_QUALITY if info.works(e)}
    assert set(quality) == gpu  # empty on a machine without a GPU encoder (CI)
    for result in quality.values():
        assert result.cpu_encoder in {"libx264", "libx265"}
        assert result.quality is None or result.delta >= -backends.QUALITY_MARGIN[result.metric]


def test_doctor_output_survives_a_legacy_windows_code_page(tmp_path, monkeypatch):
    # Issue #16: Czech Windows consoles and pipes use cp1250, which has no check mark; printing must not crash.
    import io
    import sys

    from clipcura import cli
    from clipcura.core.doctor import run_doctor
    from clipcura.core.models import FfmpegInfo, Probe

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1250")
    monkeypatch.setattr(sys, "stdout", stream)
    cli.tolerant_streams()
    report = run_doctor(run_probes=False)
    report.ffmpeg = FfmpegInfo(ffmpeg="f", ffprobe="p", version="8.1", probes=[Probe(name="libx264", ok=True)])
    cli._print_doctor(report, tmp_path / "doctor.json")
    sys.stdout.flush()
    assert "works" in sys.stdout.buffer.getvalue().decode("cp1250")
