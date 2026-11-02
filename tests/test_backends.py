"""Parsing of ffmpeg capability listings and acceleration backend selection."""
from pathlib import Path

import pytest

from clipsana.core import backends
from clipsana.core.models import FfmpegInfo, Probe

HWACCELS = """Hardware acceleration methods:
cuda
dxva2
qsv
d3d11va
vulkan

"""

ENCODERS = """Encoders:
 V..... = Video
 A..... = Audio
 ------
 VFS..D dnxhd                VC3/DNxHD
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V..... h264_qsv             H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (Intel Quick Sync Video acceleration) (codec h264)
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 A....D pcm_s16le            PCM signed 16-bit little-endian
"""

FILTERS = """Filters:
  T.. = Timeline support
  | = Source or sink filter
  ------
 .. libplacebo        N->V       Apply various GPU filters from libplacebo
 .S zscale            V->V       Apply resizing, colorspace and bit depth conversion.
 TS aap               AA->A      Apply Affine Projection algorithm to first audio stream.
"""


def test_parse_hwaccels_lists_methods_without_header():
    assert backends.parse_hwaccels(HWACCELS) == ["cuda", "dxva2", "qsv", "d3d11va", "vulkan"]


def test_parse_encoders_returns_names_below_separator():
    assert backends.parse_codec_list(ENCODERS) == {"dnxhd", "h264_nvenc", "h264_qsv", "libx264", "pcm_s16le"}


def test_parse_filters_returns_names_below_separator():
    assert backends.parse_codec_list(FILTERS) == {"libplacebo", "zscale", "aap"}


def test_parse_version_takes_first_line_version_token():
    text = "ffmpeg version n8.1.3-32-g760d10603e-20261102 Copyright (c) 2000-2026 the FFmpeg developers\nbuilt with gcc"
    assert backends.parse_version(text) == "n8.1.3-32-g760d10603e-20261102"


def _info(*working: str) -> FfmpegInfo:
    names = ["cuda", "qsv", "h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv"]
    return FfmpegInfo(
        ffmpeg="ffmpeg", ffprobe="ffprobe", version="n8.1",
        probes=[Probe(name=n, ok=n in working) for n in names],
    )


def test_choose_backend_prefers_cuda_when_device_and_nvenc_work():
    assert backends.choose_backend(_info("cuda", "h264_nvenc", "qsv", "h264_qsv")) == "cuda"


def test_choose_backend_skips_cuda_when_nvenc_fails():
    # NVENC is compiled into every BtbN build, so only a working encode proves the GPU can be used.
    assert backends.choose_backend(_info("cuda", "qsv", "h264_qsv")) == "qsv"


def test_choose_backend_falls_back_to_cpu():
    assert backends.choose_backend(_info()) == "cpu"


def _fake_ffmpeg_dir(root: Path) -> Path:
    root.mkdir(parents=True)
    for exe in ("ffmpeg.exe", "ffprobe.exe"):
        (root / exe).write_bytes(b"")
    return root


def test_find_ffmpeg_honors_env_override(tmp_path, monkeypatch):
    bin_dir = _fake_ffmpeg_dir(tmp_path / "custom")
    monkeypatch.setenv("CLIPSANA_FFMPEG", str(bin_dir))
    ffmpeg, ffprobe = backends.find_ffmpeg()
    assert (Path(ffmpeg), Path(ffprobe)) == (bin_dir / "ffmpeg.exe", bin_dir / "ffprobe.exe")


def test_find_ffmpeg_rejects_env_override_without_binaries(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPSANA_FFMPEG", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="CLIPSANA_FFMPEG"):
        backends.find_ffmpeg()
