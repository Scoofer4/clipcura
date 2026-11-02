"""Planner: one ffmpeg argument list per file, built from the rules' FixSteps (no ffmpeg needed)."""
from pathlib import Path

import pytest

from clipsana.core import planner
from clipsana.core.models import AudioStream, FixStep, Issue, MediaInfo, Paths, Profile, VideoStream


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


REC709 = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"


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
    assert flag_value(args, "-vf") == f"tonemap=x,scale=1280:720,fps=fps=30,{REC709},format=yuv422p"


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


def _scale_step(src_pix="yuv420p"):
    from clipsana import rules
    from clipsana.rules.resolution import RULE
    m = media(width=3840, height=2160, pix_fmt=src_pix)
    p = profile(max_long_side=1920)
    return m, p, RULE.fix(RULE.detect(m, p), p), rules


_CUDA = "hwupload_cuda,scale_cuda=1920:1080:interp_algo=lanczos,hwdownload"


@pytest.mark.parametrize(("pix", "chain"), [
    # Explicit format before upload: GPU-decoded frames arrive as nv12, and hwdownload must match exactly.
    ("yuv420p", f"format=yuv420p,{_CUDA},format=yuv420p"),
    ("yuv420p10le", f"format=p010le,{_CUDA},format=p010le"),
])
def test_scale_cuda_variant_keeps_bit_depth(pix, chain):
    m, p, step, _ = _scale_step(pix)
    paths = Paths(decode="cuda", encode="cuda", scale="scale_cuda")
    args = planner.build_args(m, [step], p, "cuda", Path("o.mov"), paths=paths)
    assert flag_value(args, "-vf") == f"{chain},{REC709},format=yuv422p"


def test_scale_cuda_is_not_used_for_422_sources():
    # Uploading 4:2:2 would mean subsampling chroma first: a quality loss the rule forbids.
    m, p, step, _ = _scale_step("yuv422p")
    args = planner.build_args(m, [step], p, "cuda", Path("o.mov"), paths=Paths(decode="cuda", encode="cuda",
                                                                              scale="scale_cuda"))
    assert flag_value(args, "-vf").startswith("scale=1920:1080:flags=lanczos")


def test_libplacebo_scale_variant():
    m, p, step, _ = _scale_step()
    args = planner.build_args(m, [step], p, "cpu", Path("o.mov"), paths=Paths(decode="cpu", encode="cpu",
                                                                             scale="libplacebo"))
    assert flag_value(args, "-vf").startswith("libplacebo=w=1920:h=1080:downscaler=lanczos")


def test_hdr_uses_libplacebo_tonemapping_and_keeps_cpu_scaling_after_it():
    from clipsana.rules.hdr import RULE as HDR
    m, p, scale_step, _ = _scale_step("yuv420p10le")
    m.video.color_transfer = "arib-std-b67"
    hdr_step = HDR.fix(HDR.detect(m, p), p)
    paths = Paths(decode="cuda", encode="cuda", scale="scale_cuda", tonemap="libplacebo")
    vf = flag_value(planner.build_args(m, [hdr_step, scale_step], p, "cuda", Path("o.mov"), paths=paths), "-vf")
    assert vf.startswith("libplacebo=colorspace=bt709")
    assert "scale_cuda" not in vf  # pixel format after tone-mapping is not a plain 4:2:0 upload
    assert "scale=1920:1080:flags=lanczos" in vf


def test_fallback_args_never_contain_gpu_filters():
    m, p, _, _ = _scale_step()
    paths = Paths(decode="cuda", encode="cuda", scale="scale_cuda", tonemap="libplacebo")
    item = planner.build_item(m, [Issue("resolution", "warning", "m", True, step_data(m, p))], p, "cuda",
                              Path("D:/footage/raw"), paths=paths)
    assert "scale_cuda" in " ".join(item.args)
    assert "scale_cuda" not in " ".join(item.fallback_args) and "-hwaccel" not in item.fallback_args


def step_data(m, p):
    from clipsana.rules.resolution import RULE
    return RULE.detect(m, p).data


def test_gpu_backend_decodes_on_gpu_and_fallback_is_cpu_only():
    item = planner.build_item(media(), [issue("audio_rate", sample_rate=44100)], profile(), "cuda",
                              Path("D:/footage/raw"))
    assert item.args[item.args.index("-i") - 2:item.args.index("-i")] == ["-hwaccel", "cuda"]
    assert "-hwaccel" not in item.fallback_args


@pytest.mark.parametrize(("decode", "hwaccel"), [("cuda", ["-hwaccel", "cuda"]), ("d3d11va", ["-hwaccel", "d3d11va"]),
                                                ("cpu", [])])
def test_decode_path_sets_hwaccel_that_downloads_frames(decode, hwaccel):
    args = planner.build_args(media(), [], profile(), decode, Path("o.mov"))
    assert args[:args.index("-i")] == hwaccel


@pytest.mark.parametrize(("backend", "encoder"), [("cuda", "h264_nvenc"), ("qsv", "h264_qsv"), ("cpu", "libx264")])
def test_auto_h264_picks_encoder_for_backend(backend, encoder):
    p = profile(output={"codec": "auto_h264", "container": "mp4"})
    args = planner.build_args(media(), [], p, "cpu", Path("o.mp4"), paths=Paths(encode=backend))
    assert flag_value(args, "-c:v") == encoder
    assert "+faststart" in args


def test_gpu_encoder_in_profile_falls_back_to_cpu_equivalent():
    p = profile(output={"codec": "hevc_nvenc", "container": "mp4"})
    assert flag_value(planner.build_args(media(), [], p, "cpu", Path("o.mp4")), "-c:v") == "libx265"
    gpu = planner.build_args(media(), [], p, "cpu", Path("o.mp4"), paths=Paths(encode="cuda"))
    assert flag_value(gpu, "-c:v") == "hevc_nvenc"


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


@pytest.mark.parametrize(("w", "h", "ok"), [(256, 120, True), (254, 120, False), (256, 118, False)])
def test_dnxhr_minimum_frame_size_is_checked_before_running(w, h, ok):
    m = media(width=w, height=h)
    issues = [issue("audio_rate", sample_rate=44100)]
    if ok:
        assert planner.build_item(m, issues, profile(), "cpu", Path("D:/footage/raw")) is not None
    else:
        with pytest.raises(planner.UnsupportedError, match="256x120"):
            planner.build_item(m, issues, profile(), "cpu", Path("D:/footage/raw"))


def test_prores_has_no_minimum_size():
    p = profile(output={"codec": "prores_422", "container": "mov"})
    assert planner.build_item(media(width=64, height=64), [issue("audio_rate", sample_rate=44100)], p, "cpu",
                              Path("D:/footage/raw")) is not None


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
