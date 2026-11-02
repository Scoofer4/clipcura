"""Each rule: detection on synthetic MediaInfo and the FixStep it proposes (no ffmpeg needed)."""
import pytest

from clipsana import rules
from clipsana.core.models import AudioStream, MediaInfo, Profile, VideoStream

PROFILE = Profile.model_validate({
    "name": "t", "label": "T", "fps": 30, "max_long_side": 3840, "audio_rate": 48000,
    "output": {"codec": "dnxhr_hq", "container": "mov"},
})


def media(path="clip.mp4", audio=True, **video) -> MediaInfo:
    v = {"codec": "h264", "pix_fmt": "yuv420p", "width": 1920, "height": 1080, "r_fps": 30.0, "avg_fps": 30.0,
         "color_transfer": "bt709"} | video
    return MediaInfo(path=path, duration=10, video=VideoStream(**v),
                     audio=AudioStream(codec="aac", sample_rate=48000, channels=2) if audio else None)


def detect(rule_id: str, m: MediaInfo, profile: Profile = PROFILE):
    return rules.get_rule(rule_id).detect(m, profile)


def test_all_spec_rules_are_discovered():
    ids = {r.id for r in rules.load_rules()}
    assert ids >= {"vfr", "fps_mismatch", "hdr", "hevc_10bit", "resolution", "audio_rate", "rotation",
                   "no_audio", "insv", "corrupt"}


def test_clean_clip_has_no_issues():
    assert [r.id for r in rules.load_rules() if r.detect(media(), PROFILE)] == []


def test_disabled_rules_are_skipped():
    profile = PROFILE.model_copy(update={"rules": PROFILE.rules.model_copy(update={"disabled": ["vfr"]})})
    assert "vfr" not in {r.id for r in rules.load_rules(profile)}


# --- vfr ---------------------------------------------------------------------------------------------
def test_vfr_detected_from_nominal_vs_average_rate():
    issue = detect("vfr", media(r_fps=60.0, avg_fps=58.26))
    assert issue.severity == "error" and issue.auto_fixable


def test_vfr_detected_from_absurd_screen_recording_rate():
    assert detect("vfr", media(r_fps=90000.0, avg_fps=55.85))


def test_vfr_within_tolerance_is_ignored():
    assert detect("vfr", media(r_fps=30.0, avg_fps=29.9)) is None


def test_vfr_detected_by_deep_pts_check():
    m = media()
    m.pts_irregularity = 0.3
    assert detect("vfr", m)


def test_vfr_fix_forces_cfr_and_resyncs_audio():
    step = rules.get_rule("vfr").fix(detect("vfr", media(r_fps=60.0, avg_fps=50.0)), PROFILE)
    assert step.video_filters == ["fps=fps=30"]
    assert "async=1" in step.audio_filters[0]
    assert step.output_args == ["-fps_mode", "cfr"]


# --- fps_mismatch -------------------------------------------------------------------------------------
@pytest.mark.parametrize(("fps", "severity"), [(24.0, "warning"), (25.0, "warning"), (60.0, "info")])
def test_fps_mismatch_severity(fps, severity):
    assert detect("fps_mismatch", media(r_fps=fps, avg_fps=fps)).severity == severity


def test_fps_mismatch_uses_nominal_rate_of_vfr_phone_footage():
    # 60 fps phone video averaging 58.26 because of VFR is a clean 60 -> 30 conversion, not judder.
    issue = detect("fps_mismatch", media(r_fps=60.0, avg_fps=58.26))
    assert (issue.severity, issue.data["fps"]) == ("info", 60.0)


def test_fps_mismatch_falls_back_to_average_when_nominal_rate_is_nonsense():
    assert detect("fps_mismatch", media(r_fps=90000.0, avg_fps=55.85)).data["fps"] == 55.85


def test_fps_mismatch_flags_ntsc_rate_against_integer_target():
    assert detect("fps_mismatch", media(r_fps=29.97, avg_fps=29.97))


# --- hdr ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("trc", ["smpte2084", "arib-std-b67"])
def test_hdr_detected_and_tone_mapped(trc):
    issue = detect("hdr", media(color_transfer=trc))
    step = rules.get_rule("hdr").fix(issue, PROFILE)
    assert "tonemap" in step.video_filters[0]
    assert "tonemap:libplacebo" in step.gpu_variant


# --- hevc_10bit ---------------------------------------------------------------------------------------
def test_hevc_10bit_detected_but_8bit_is_not():
    assert detect("hevc_10bit", media(codec="hevc", pix_fmt="yuv420p10le", bit_depth=10)).severity == "error"
    assert detect("hevc_10bit", media(codec="hevc")) is None


# --- resolution ---------------------------------------------------------------------------------------
def test_resolution_downscales_long_side_keeping_aspect_and_even_size():
    issue = detect("resolution", media(width=6144, height=3072))
    assert rules.get_rule("resolution").fix(issue, PROFILE).video_filters == ["scale=3840:1920:flags=lanczos"]


def test_resolution_fixes_odd_dimensions():
    issue = detect("resolution", media(width=321, height=181))
    assert rules.get_rule("resolution").fix(issue, PROFILE).video_filters == ["scale=320:180:flags=lanczos"]


def test_resolution_uses_display_size_of_rotated_portrait_video():
    issue = detect("resolution", media(width=6144, height=3456, rotation=-90))
    assert rules.get_rule("resolution").fix(issue, PROFILE).video_filters == ["scale=2160:3840:flags=lanczos"]


# --- audio_rate / no_audio ----------------------------------------------------------------------------
def test_audio_rate_resamples_to_profile_rate():
    m = media()
    m.audio.sample_rate = 44100
    step = rules.get_rule("audio_rate").fix(detect("audio_rate", m), PROFILE)
    assert step.audio_filters == ["aresample=osr=48000"]


def test_no_audio_is_info_and_fixable_only_when_profile_asks():
    assert detect("no_audio", media(audio=False)).auto_fixable is False
    profile = PROFILE.model_copy(update={"rules": PROFILE.rules.model_copy(update={"add_silent_audio": True})})
    issue = detect("no_audio", media(audio=False), profile)
    step = rules.get_rule("no_audio").fix(issue, profile)
    assert issue.severity == "info" and issue.auto_fixable
    assert "anullsrc" in " ".join(step.extra_inputs[0])


# --- rotation -----------------------------------------------------------------------------------------
def test_rotation_detected_from_display_matrix():
    issue = detect("rotation", media(rotation=-90))
    assert issue.data["rotation"] == -90
    assert rules.get_rule("rotation").fix(issue, PROFILE) is not None


# --- color_space --------------------------------------------------------------------------------------
def test_bt601_frames_are_converted_to_rec709():
    issue = detect("color_space", media(color_primaries="bt470bg", color_transfer="smpte170m",
                                        color_space="bt470bg"))
    step = rules.get_rule("color_space").fix(issue, PROFILE)
    assert step.video_filters == ["zscale=m=709:t=709:p=709:r=tv"]


@pytest.mark.parametrize("colors", [
    {"color_primaries": "bt709", "color_space": "bt709"},                    # already Rec.709
    {"color_primaries": "", "color_space": ""},                              # untagged: assume Rec.709
    {"color_primaries": "bt2020", "color_space": "bt2020nc", "color_transfer": "arib-std-b67"},  # hdr rule
])
def test_color_space_ignores_rec709_untagged_and_hdr(colors):
    assert detect("color_space", media(**colors)) is None


def test_color_space_alone_does_not_justify_a_conversion():
    assert rules.get_rule("color_space").standalone is False


# --- insv / corrupt -----------------------------------------------------------------------------------
def test_insv_needs_export_in_insta360_studio():
    issue = detect("insv", MediaInfo(path="VID_001.insv"))
    assert not issue.auto_fixable
    assert rules.get_rule("insv").fix(issue, PROFILE) is None


def test_corrupt_reports_probe_and_decode_errors():
    assert detect("corrupt", MediaInfo(path="x.mp4", probe_error="moov atom not found")).severity == "error"
    m = media()
    m.decode_error = "Invalid NAL unit size"
    assert not detect("corrupt", m).auto_fixable


def test_messages_are_localized(monkeypatch):
    monkeypatch.setenv("CLIPSANA_LANG", "cs")
    assert "snímková" in detect("vfr", media(r_fps=60.0, avg_fps=50.0)).message
