"""The `loudness` rule (issue #15). It is also the acceptance check for CLAUDE.md §13: a new rule is one file in
clipsana/rules/ plus profile keys, and the core does not change."""
import subprocess
from pathlib import Path

import pytest

from clipsana import rules
from clipsana.core import backends, planner, probe, profiles, service
from clipsana.core.models import Profile
from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def profile(**loudness) -> Profile:
    base = profiles.load_profile("social-30").model_dump()
    base["rules"]["loudness"] = loudness
    return Profile.model_validate(base)


def clip(tmp_path: Path, volume_db: float, name: str = "talk.mp4") -> Path:
    ffmpeg, _ = backends.find_ffmpeg()
    out = tmp_path / name
    subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3",
                    "-f", "lavfi", "-i", f"sine=f=440:r=48000:d=3,volume={volume_db}dB", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-y", str(out)],
                   check=True, timeout=60)
    return out


def detect(path: Path, prof: Profile):
    return rules.get_rule("loudness").detect(probe.probe(path), prof)


def test_rule_is_picked_up_from_its_file():
    assert "loudness" in {r.id for r in rules.load_rules()}


def test_not_measured_unless_the_profile_turns_it_on(tmp_path):
    # Measuring decodes all audio, so plain scans stay fast.
    assert detect(clip(tmp_path, -30), profile()) is None


def test_quiet_clip_is_reported_but_not_changed_by_default(tmp_path):
    issue = detect(clip(tmp_path, -30), profile(measure=True, target_lufs=-14))
    assert issue.severity == "info" and not issue.auto_fixable
    assert issue.data["input_i"] < -40 and issue.data["target_lufs"] == -14
    assert service.file_status([issue]) == "ok"  # reporting alone never queues a conversion


def test_enabled_fix_normalises_to_the_target_in_the_single_pass(tmp_path):
    prof = profile(measure=True, target_lufs=-16, fix=True)
    issue = detect(clip(tmp_path, -30), prof)
    assert issue.auto_fixable
    step = rules.get_rule("loudness").fix(issue, prof)
    media = probe.probe(tmp_path / "talk.mp4")
    out = tmp_path / "out" / "talk_edit.mov"
    out.parent.mkdir()
    ffmpeg, _ = backends.find_ffmpeg()
    args = planner.build_args(media, [step], prof, "cpu", out)
    subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-nostdin", *args], check=True, timeout=120)

    fixed = probe.probe(out)
    assert fixed.audio.sample_rate == 48000  # loudnorm works at 192 kHz internally
    assert detect(out, prof) is None  # now within tolerance of -16 LUFS


def test_loud_clip_is_reported_with_its_true_peak(tmp_path):
    issue = detect(clip(tmp_path, 20), profile(measure=True, target_lufs=-14))
    assert issue.data["input_i"] > -14 and issue.data["input_tp"] > -1
    assert "dBTP" in issue.message


def test_bundled_social_profiles_measure_and_only_report():
    for name in ("social-30", "ipad-light"):
        settings = profiles.load_profile(name).rules.settings("loudness")
        assert settings["measure"] is True and settings["target_lufs"] == -14 and settings["fix"] is False


@pytest.mark.parametrize("bad", [{"measure": True, "target_lufs": "loud"}, {"measure": True, "target_lufs": 5}])
def test_invalid_settings_are_reported_instead_of_crashing_the_scan(tmp_path, bad):
    issue = detect(clip(tmp_path, -20), profile(**bad))
    assert issue.severity == "warning" and not issue.auto_fixable and "target_lufs" in issue.message
