"""Planner: one ffmpeg argument list per file, built from the rules' FixSteps (no ffmpeg needed)."""
from pathlib import Path

import pytest

from clipsana.core import planner
from clipsana.core.models import AudioStream, FixStep, Issue, MediaInfo, Profile, VideoStream


def profile(**over) -> Profile:
    data = {"name": "t", "label": "T", "fps": 30, "max_long_side": 3840, "audio_rate": 48000,
            "output": {"codec": "dnxhr_hq", "container": "mov"}}
    data["output"] |= over.pop("output", {})
    return Profile.model_validate(data | over)


def media(path="D:/footage/raw/clip.mp4", audio=True, **video) -> MediaInfo:
    v = {"codec": "h264", "pix_fmt": "yuv420p", "width": 1920, "height": 1080, "r_fps": 30.0, "avg_fps": 30.0} | video
    return MediaInfo(path=path, size=1000, duration=10, video=VideoStream(**v),
                     audio=AudioStream(codec="aac", sample_rate=44100, channels=2) if audio else None)


def issue(rule_id: str, **data) -> Issue:
    return Issue(rule_id, "warning", "msg", True, data)


def flag_value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_merge_filters_deduplicates_and_merges_named_options():
    assert planner.merge_filters(["fps=fps=30", "fps=fps=30"]) == ["fps=fps=30"]
    assert planner.merge_filters(["aresample=async=1:first_pts=0", "aresample=osr=48000"]) == [
        "aresample=async=1:first_pts=0:osr=48000"]


def test_merge_filters_keeps_multi_filter_chains_intact():
    chain = "zscale=t=linear,format=gbrpf32le,zscale=p=bt709"
    assert planner.merge_filters([chain, "scale=640:360"]) == [chain, "scale=640:360"]


def test_steps_are_ordered_rotation_hdr_scale_fps():
    steps = [FixStep(40, ["fps=fps=30"]), FixStep(30, ["scale=1280:720"]), FixStep(20, ["tonemap=x"])]
    args = planner.build_args(media(), steps, profile(), "cpu", Path("out.mov"))
    assert flag_value(args, "-vf") == "tonemap=x,scale=1280:720,fps=fps=30,format=yuv422p"


def test_vfr_and_audio_rate_produce_one_command_with_merged_audio_and_single_cfr_flag():
    steps = [FixStep(40, ["fps=fps=30"], ["aresample=async=1:first_pts=0"], ["-fps_mode", "cfr"]),
             FixStep(40, ["fps=fps=30"], [], ["-fps_mode", "cfr"]),
             FixStep(0, [], ["aresample=osr=48000"])]
    args = planner.build_args(media(), steps, profile(), "cpu", Path("out.mov"))
    name, _, opts = flag_value(args, "-af").partition("=")
    assert (name, set(opts.split(":"))) == ("aresample", {"async=1", "first_pts=0", "osr=48000"})
    assert args.count("-fps_mode") == 1
    assert flag_value(args, "-c:v") == "dnxhd" and flag_value(args, "-profile:v") == "dnxhr_hq"
    assert flag_value(args, "-c:a") == "pcm_s16le"
    assert flag_value(args, "-f") == "mov"
    assert args[-1] == "out.mov"


def test_gpu_backend_decodes_on_gpu_and_fallback_is_cpu_only():
    item = planner.build_item(media(), [issue("audio_rate", sample_rate=44100)], profile(), "cuda",
                              Path("D:/footage/raw"))
    assert item.args[item.args.index("-i") - 2:item.args.index("-i")] == ["-hwaccel", "cuda"]
    assert "-hwaccel" not in item.fallback_args


@pytest.mark.parametrize(("backend", "encoder"), [("cuda", "h264_nvenc"), ("qsv", "h264_qsv"), ("cpu", "libx264")])
def test_auto_h264_picks_encoder_for_backend(backend, encoder):
    p = profile(output={"codec": "auto_h264", "container": "mp4"})
    args = planner.build_args(media(), [], p, backend, Path("o.mp4"))
    assert flag_value(args, "-c:v") == encoder
    assert "+faststart" in args


def test_gpu_encoder_in_profile_falls_back_to_cpu_equivalent():
    p = profile(output={"codec": "hevc_nvenc", "container": "mp4"})
    assert flag_value(planner.build_args(media(), [], p, "cpu", Path("o.mp4")), "-c:v") == "libx265"


def test_silent_track_is_mapped_from_generated_input():
    step = FixStep(0, extra_inputs=[["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]])
    args = planner.build_args(media(audio=False), [step], profile(), "cpu", Path("o.mov"))
    assert "anullsrc=r=48000:cl=stereo" in args
    assert ["-map", "1:a:0"] == args[args.index("1:a:0") - 1:args.index("1:a:0") + 1]
    assert "-shortest" in args


def test_output_path_goes_to_profile_folder_and_mirrors_subfolders():
    root = Path("D:/footage/raw")
    assert planner.output_path(Path("D:/footage/raw/clip.mp4"), root, profile()) == Path(
        "D:/footage/02_edit/clip_edit.mov")
    assert planner.output_path(Path("D:/footage/raw/day1/a.mp4"), root, profile()) == Path(
        "D:/footage/02_edit/day1/a_edit.mov")


def test_output_may_never_overwrite_the_original():
    p = profile(output={"codec": "libx264", "container": "mp4", "folder": ".", "suffix": ""})
    with pytest.raises(planner.PlanError, match="original"):
        planner.output_path(Path("D:/footage/raw/clip.mp4"), Path("D:/footage/raw"), p)


def test_no_fixable_issue_means_no_plan_item():
    not_fixable = Issue("insv", "warning", "msg", False)
    assert planner.build_item(media(), [not_fixable], profile(), "cpu", Path("D:/footage/raw")) is None


def test_plan_item_has_size_estimate_and_stable_hash():
    issues = [issue("audio_rate", sample_rate=44100)]
    a = planner.build_item(media(), issues, profile(), "cpu", Path("D:/footage/raw"))
    b = planner.build_item(media(), issues, profile(), "cpu", Path("D:/footage/raw"))
    assert a.est_bytes > 0
    assert a.plan_hash == b.plan_hash
    assert a.rule_ids == ["audio_rate"]
