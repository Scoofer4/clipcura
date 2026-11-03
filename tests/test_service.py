"""End-to-end through the public core API: scan -> plan -> apply, verified with ffprobe on the output.

These are the M1 acceptance checks: every rule detects and fixes its generated clip.
"""
import json
import subprocess
from pathlib import Path

import pytest

from clipcura.core import backends, service
from clipcura.core.models import Paths
from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def ffprobe(path: Path) -> dict:
    _, fp = backends.find_ffmpeg()
    out = subprocess.run([fp, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def video(info: dict) -> dict:
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def audio(info: dict) -> dict | None:
    return next((s for s in info["streams"] if s["codec_type"] == "audio"), None)


def fix_one(raw_folder, name: str, backend="cpu") -> tuple[service.ScanResult, Path]:
    raw = raw_folder(name)
    scan = service.scan(raw, profile="social-30")
    plan = service.plan(scan.scan_id, backend=backend)
    results = service.apply(plan.plan_id)
    assert [r.status for r in results] == ["done"], [r.error for r in results]
    return scan, Path(results[0].output)


@pytest.mark.parametrize("name", ["vfr.mp4", "fps24.mp4", "fps25.mp4", "fps60.mp4"])
def test_frame_rate_problems_end_as_constant_30_fps(raw_folder, name):
    _, out = fix_one(raw_folder, name)
    v = video(ffprobe(out))
    assert v["r_frame_rate"] == v["avg_frame_rate"] == "30/1"
    assert v["codec_name"] == "dnxhd"


@pytest.mark.parametrize("name", ["hlg.mp4", "pq.mp4"])
def test_hdr_is_tone_mapped_to_rec709(raw_folder, name):
    scan, out = fix_one(raw_folder, name)
    assert "hdr" in {i.rule_id for i in scan.files[0].issues}
    v = video(ffprobe(out))
    assert (v["color_transfer"], v["color_primaries"]) == ("bt709", "bt709")


def test_bt601_frames_end_with_consistent_rec709_tags_when_file_is_converted(raw_folder):
    _, out = fix_one(raw_folder, "bt601_25.mp4")
    v = video(ffprobe(out))
    assert (v["color_primaries"], v["color_transfer"], v["color_space"]) == ("bt709", "bt709", "bt709")


def test_bt601_alone_does_not_trigger_conversion(raw_folder):
    scan = service.scan(raw_folder("bt601_30.mp4"), profile="social-30")
    assert scan.files[0].status == "ok"
    assert [i.rule_id for i in scan.files[0].issues if i.rule_id != "loudness"] == ["color_space"]
    assert service.plan(scan.scan_id).items == []


def _gpu_paths_working() -> bool:
    info = backends.inspect_ffmpeg(run_probes=True)
    return info.works("cuda") and info.works("libplacebo")


@pytest.mark.parametrize(("scale", "tonemap"), [("scale_cuda", "zscale"), ("libplacebo", "libplacebo")])
def test_gpu_filter_paths_produce_the_same_result(raw_folder, scale, tonemap):
    if not _gpu_paths_working():
        pytest.skip("needs CUDA and Vulkan/libplacebo")
    for name, expected in (("big6k.mp4", (3840, 1920)), ("hlg.mp4", (320, 180))):
        raw = raw_folder(name)
        scan = service.scan(raw, profile="social-30")
        paths = Paths(decode="cuda", encode="cuda", scale=scale, tonemap=tonemap)
        results = service.apply(service.plan(scan.scan_id, paths=paths).plan_id)
        assert [r.status for r in results] == ["done"], [r.error for r in results]
        assert results[0].backend_used == "cuda"  # GPU path itself worked, no CPU fallback
        v = video(ffprobe(Path(results[0].output)))
        assert (v["width"], v["height"], v["color_transfer"]) == (*expected, "bt709")


def test_output_of_untagged_source_carries_explicit_rec709_tags(raw_folder):
    # Editors guess when tags are missing; every output must state Rec.709 explicitly.
    _, out = fix_one(raw_folder, "a44k.mp4")
    v = video(ffprobe(out))
    assert (v.get("color_primaries"), v.get("color_transfer"), v.get("color_space")) == ("bt709", "bt709", "bt709")


def test_hevc_10bit_becomes_editing_codec(raw_folder):
    _, out = fix_one(raw_folder, "hevc10.mp4")
    assert video(ffprobe(out))["codec_name"] == "dnxhd"


def test_6k_is_scaled_to_profile_limit(raw_folder):
    _, out = fix_one(raw_folder, "big6k.mp4")
    v = video(ffprobe(out))
    assert (v["width"], v["height"]) == (3840, 1920)


def test_odd_dimensions_become_even(raw_folder):
    _, out = fix_one(raw_folder, "odd.mp4")
    v = video(ffprobe(out))
    assert (v["width"] % 2, v["height"] % 2) == (0, 0)


def test_44k_audio_becomes_48k(raw_folder):
    _, out = fix_one(raw_folder, "a44k.mp4")
    assert audio(ffprobe(out))["sample_rate"] == "48000"


def test_rotation_is_applied_to_pixels_and_removed_from_metadata(raw_folder):
    _, out = fix_one(raw_folder, "rot.mp4")
    v = video(ffprobe(out))
    assert (v["width"], v["height"]) == (360, 640)
    assert not any("rotation" in sd for sd in v.get("side_data_list", []))


def test_clip_below_codec_minimum_is_reported_in_plan_not_failed_at_runtime(raw_folder):
    scan = service.scan(raw_folder("tiny25.mp4"), profile="social-30")
    plan = service.plan(scan.scan_id, backend="cpu")
    (entry,) = plan.items
    assert entry.status == "unsupported" and "256x120" in entry.reason
    assert service.apply(plan.plan_id) == []


def test_clean_clip_is_left_alone(raw_folder):
    raw = raw_folder("ok.mp4")
    scan = service.scan(raw, profile="social-30")
    assert scan.files[0].status == "ok"
    assert service.plan(scan.scan_id).items == []


def test_insv_and_broken_files_are_reported_not_fixed(raw_folder):
    raw = raw_folder("VID_0001.insv", "broken.mp4")
    scan = service.scan(raw, profile="social-30")
    status = {Path(f.path).name: f.status for f in scan.files}
    assert status == {"VID_0001.insv": "needs_human", "broken.mp4": "error"}
    assert service.plan(scan.scan_id).items == []


def test_rerun_does_not_convert_finished_files_again(raw_folder):
    _, out = fix_one(raw_folder, "a44k.mp4")
    first_mtime = out.stat().st_mtime
    scan = service.scan(out.parent.parent / "raw", profile="social-30")
    plan = service.plan(scan.scan_id)
    assert [i.status for i in plan.items] == ["done"]
    assert service.apply(plan.plan_id) == []
    assert out.stat().st_mtime == first_mtime


def test_scan_ignores_its_own_output_folder(raw_folder):
    _, out = fix_one(raw_folder, "a44k.mp4")
    # Scanning the parent recursively must not pick up 02_edit outputs as new originals.
    scan = service.scan(out.parent.parent, profile="social-30", recursive=True)
    assert all("02_edit" not in f.path for f in scan.files)


def test_originals_are_never_modified(raw_folder):
    raw = raw_folder("vfr.mp4")
    before = (raw / "vfr.mp4").read_bytes()
    service.apply(service.plan(service.scan(raw, profile="social-30").scan_id).plan_id)
    assert (raw / "vfr.mp4").read_bytes() == before


def test_status_reports_finished_job(raw_folder):
    raw = raw_folder("a44k.mp4")
    results = service.apply(service.plan(service.scan(raw, profile="social-30").scan_id).plan_id)
    (job,) = service.status([results[0].job_id])
    assert job["status"] == "done" and job["progress"] == 100.0
