"""Profile loading and validation."""
import pytest

from clipsana.core import profiles


def test_bundled_profiles_are_listed():
    names = {p.name for p in profiles.list_profiles()}
    assert {"social-30", "ipad-light", "hero-10bit"} <= names


def test_load_profile_reads_yaml_values():
    p = profiles.load_profile("social-30")
    assert (p.fps, p.max_long_side, p.audio_rate) == (30, 3840, 48000)
    assert (p.output.codec, p.output.container, p.output.suffix) == ("dnxhr_hq", "mov", "_edit")


def test_unknown_profile_raises_with_available_names():
    with pytest.raises(profiles.ProfileError, match="social-30"):
        profiles.load_profile("does-not-exist")


def test_invalid_profile_is_rejected(tmp_path):
    (tmp_path / "bad.yaml").write_text("name: bad\nlabel: Bad\nfps: -5\nmax_long_side: 100\n"
                                       "audio_rate: 48000\noutput: {codec: libx264, container: mp4}\n",
                                       encoding="utf-8")
    with pytest.raises(profiles.ProfileError, match="fps"):
        profiles.load_profile("bad", search_dirs=[tmp_path])


def test_user_profile_dir_overrides_bundled(tmp_path):
    (tmp_path / "social-30.yaml").write_text(
        "name: social-30\nlabel: Mine\nfps: 25\nmax_long_side: 1920\naudio_rate: 48000\n"
        "output: {codec: libx264, container: mp4}\n", encoding="utf-8")
    p = profiles.load_profile("social-30", search_dirs=[tmp_path, profiles.BUNDLED_DIR])
    assert p.fps == 25
