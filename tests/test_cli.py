"""CLI: scan / plan / apply / fix on generated clips."""
import json
from pathlib import Path

from typer.testing import CliRunner

from clipsana.cli import app
from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg
runner = CliRunner()


def test_scan_json_lists_files_and_summary(raw_folder):
    raw = raw_folder("ok.mp4", "a44k.mp4")
    result = runner.invoke(app, ["scan", str(raw), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["summary"] == {"ok": 1, "fixable": 1, "needs_human": 0, "error": 0}


def test_scan_plan_apply_by_ids(raw_folder):
    raw = raw_folder("a44k.mp4")
    scan_id = json.loads(runner.invoke(app, ["scan", str(raw), "--json"]).output)["scan_id"]
    plan = json.loads(runner.invoke(app, ["plan", scan_id, "--json"]).output)
    assert [i["status"] for i in plan["items"]] == ["pending"]
    result = runner.invoke(app, ["apply", plan["plan_id"]])
    assert result.exit_code == 0, result.output
    assert Path(plan["items"][0]["item"]["output"]).is_file()


def test_fix_converts_folder_in_one_command(raw_folder):
    raw = raw_folder("vfr.mp4", "ok.mp4")
    result = runner.invoke(app, ["fix", str(raw)])
    assert result.exit_code == 0, result.output
    assert (raw.parent / "02_edit" / "vfr_edit.mov").is_file()
    assert not (raw.parent / "02_edit" / "ok_edit.mov").exists()


def test_fix_dry_run_writes_nothing(raw_folder):
    raw = raw_folder("vfr.mp4")
    result = runner.invoke(app, ["fix", str(raw), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "ffmpeg" in result.output
    # The printed command must be copy-pasteable: no emoji or markup substitution of ffmpeg syntax.
    assert "-map 0:v:0" in result.output and "-map 0:a:0" in result.output
    assert not (raw.parent / "02_edit").exists()


def test_fix_exit_code_signals_failed_or_unfixable_files(raw_folder):
    raw = raw_folder("broken.mp4")
    assert runner.invoke(app, ["fix", str(raw)]).exit_code == 1
