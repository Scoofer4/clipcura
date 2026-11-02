"""Shared fixtures: synthetic clips generated with ffmpeg lavfi, one per problem the rules must fix."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from clipsana.core import backends

GENERATED = Path(__file__).parent / "fixtures" / "generated" / "clips"

_V = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
_A = ["-f", "lavfi", "-i", "sine=r=48000:d=2", "-c:a", "aac", "-shortest"]


_BT601 = "setparams=color_primaries=bt470bg:color_trc=smpte170m:colorspace=bt470bg"
_TAG709 = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]


def _src(size="320x180", rate=30, dur=2) -> list[str]:
    return ["-f", "lavfi", "-i", f"testsrc2=s={size}:r={rate}:d={dur}"]


# name -> ffmpeg arguments producing it ("{x.mp4}" is replaced by the path of an earlier clip)
CLIPS: dict[str, list[str]] = {
    "ok.mp4": [*_src(), *_A, *_V],
    "vfr.mp4": [*_src(rate=60), *_A, "-vf", r"select='not(eq(mod(n\,7)\,3))*not(eq(mod(n\,11)\,5))'",
                "-fps_mode", "vfr", *_V],
    "fps24.mp4": [*_src(rate=24), *_A, *_V],
    "fps25.mp4": [*_src(rate=25), *_A, *_V],
    "fps60.mp4": [*_src(rate=60), *_A, *_V],
    "hlg.mp4": [*_src(), *_A, "-vf", "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc",
                "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error"],
    "pq.mp4": [*_src(), *_A, "-vf", "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc",
               "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error"],
    "hevc10.mp4": [*_src(), *_A, "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error"],
    "big6k.mp4": [*_src(size="6144x3072", dur=0.5), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
                  "yuv420p"],
    "odd.mp4": [*_src(), *_A, "-vf", "scale=321:181,format=yuv444p", "-c:v", "libx264", "-preset", "ultrafast"],
    "a44k.mp4": [*_src(), "-f", "lavfi", "-i", "sine=r=44100:d=2", "-c:a", "aac", "-shortest", *_V],
    "noaudio.mp4": [*_src(), *_V],
    "tiny25.mp4": [*_src(size="240x136", rate=25), *_A, *_V],   # below the DNxHR minimum of 256x120
    # BT.601 frames in a container that claims BT.709, like Android screen recordings.
    "bt601src30.mp4": [*_src(), *_A, "-vf", _BT601, *_V],
    "bt601src25.mp4": [*_src(rate=25), *_A, "-vf", _BT601, *_V],
    "bt601_30.mp4": ["-i", "{bt601src30.mp4}", "-c", "copy", *_TAG709],
    "bt601_25.mp4": ["-i", "{bt601src25.mp4}", "-c", "copy", *_TAG709],
    # DNxHR needs at least 256x120, so the rotated clip must stay above that once it is portrait.
    "rotsrc.mp4": [*_src(size="640x360"), *_A, *_V],
    "rot.mp4": ["-display_rotation", "90", "-i", "{rotsrc.mp4}", "-c", "copy"],
}


def _ffmpeg_available() -> bool:
    try:
        backends.find_ffmpeg()
        return True
    except FileNotFoundError:
        return False


needs_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not installed (tools/fetch_ffmpeg.py)")


@pytest.fixture(scope="session")
def clips() -> Path:
    """Directory with every generated clip (cached between runs; regenerated if missing)."""
    ffmpeg, _ = backends.find_ffmpeg()
    GENERATED.mkdir(parents=True, exist_ok=True)
    for name, args in CLIPS.items():
        out = GENERATED / name
        if out.exists():
            continue
        args = [str(GENERATED / a[1:-1]) if a.startswith("{") and a.endswith("}") else a for a in args]
        subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", *args, str(out)], check=True,
                       timeout=120)
    (GENERATED / "broken.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"garbage" * 500)
    shutil.copyfile(GENERATED / "ok.mp4", GENERATED / "VID_0001.insv")
    return GENERATED


@pytest.fixture
def raw_folder(tmp_path, clips):
    """Copy selected clips into <tmp>/raw so each test owns its originals and its 02_edit output."""
    def make(*names: str) -> Path:
        raw = tmp_path / "raw"
        raw.mkdir(exist_ok=True)
        for n in names:
            shutil.copyfile(clips / n, raw / n)
        return raw
    return make


@pytest.fixture(autouse=True)
def _isolated_app_data(tmp_path, monkeypatch):
    # Database, doctor report and user profiles of a test never touch the real profile.
    monkeypatch.setenv("CLIPSANA_HOME", str(tmp_path / "home"))
