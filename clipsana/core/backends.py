"""Locate ffmpeg, discover what it can do on this machine and pick an acceleration backend.

A build lists NVENC/QSV encoders whether or not the hardware exists, so every capability that
matters is confirmed by a tiny real encode/decode ("probe") instead of trusting the listings.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clipsana.core.models import Backend, FfmpegInfo, Probe
from clipsana.core.paths import vendored_ffmpeg_dir

_EXE = ".exe" if sys.platform == "win32" else ""
PROBE_TIMEOUT_S = 30

# Small synthetic input: big enough for every encoder's minimum size, fast on any CPU.
_SRC = ["-f", "lavfi", "-i", "testsrc2=size=256x144:rate=30", "-frames:v", "5"]
_NULL = ["-f", "null", "-"]

DEVICE_PROBES = ["cuda", "qsv", "vulkan"]
ENCODER_PROBES: dict[str, list[str]] = {
    "libx264": ["-c:v", "libx264"],
    "h264_nvenc": ["-c:v", "h264_nvenc"],
    "hevc_nvenc": ["-c:v", "hevc_nvenc"],
    "h264_qsv": ["-c:v", "h264_qsv"],
    "hevc_qsv": ["-c:v", "hevc_qsv"],
    "dnxhd": ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq", "-pix_fmt", "yuv422p"],
    "prores_ks": ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le"],
}
FILTER_PROBES: dict[str, list[str]] = {
    "libplacebo": ["-vf", "libplacebo=w=128:h=72"],
    "zscale": ["-vf", "zscale=w=128:h=72"],
}
# HEVC 10-bit is the footage Resolve struggles with most, so GPU decoding is tested on exactly that.
DECODER_PROBES: dict[str, list[str]] = {
    "hevc10_cuda": ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
    "hevc10_qsv": ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"],
}


def _binaries_in(directory: Path) -> tuple[str, str] | None:
    ffmpeg, ffprobe = directory / f"ffmpeg{_EXE}", directory / f"ffprobe{_EXE}"
    return (str(ffmpeg), str(ffprobe)) if ffmpeg.is_file() and ffprobe.is_file() else None


def find_ffmpeg() -> tuple[str, str]:
    """Return (ffmpeg, ffprobe): CLIPSANA_FFMPEG dir, then vendor/ffmpeg/bin, then PATH."""
    override = os.environ.get("CLIPSANA_FFMPEG")
    if override:
        found = _binaries_in(Path(override))
        if not found:
            raise FileNotFoundError(f"CLIPSANA_FFMPEG={override} does not contain ffmpeg and ffprobe")
        return found
    found = _binaries_in(vendored_ffmpeg_dir() / "bin")
    if found:
        return found
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe
    raise FileNotFoundError("ffmpeg not found: run `uv run python tools/fetch_ffmpeg.py` or set CLIPSANA_FFMPEG")


def parse_hwaccels(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    return [ln for ln in lines[1:] if ln]


def parse_codec_list(text: str) -> set[str]:
    """Names from `ffmpeg -encoders` / `-filters`: second column of rows below the '------' line."""
    names: set[str] = set()
    below_separator = False
    for line in text.splitlines():
        if line.strip().startswith("------"):
            below_separator = True
        elif below_separator and line.strip():
            parts = line.split()
            if len(parts) >= 2:
                names.add(parts[1])
    return names


def parse_version(text: str) -> str:
    first = text.splitlines()[0] if text else ""
    parts = first.split()
    return parts[2] if len(parts) >= 3 and parts[1] == "version" else first


def choose_backend(info: FfmpegInfo) -> Backend:
    # Order from the spec: CUDA/NVENC -> Intel QSV -> CPU. A device that initializes but cannot
    # encode (driver too old, encoder sessions exhausted) is useless for us, so require both.
    if info.works("cuda") and (info.works("h264_nvenc") or info.works("hevc_nvenc")):
        return "cuda"
    if info.works("qsv") and (info.works("h264_qsv") or info.works("hevc_qsv")):
        return "qsv"
    return "cpu"


def _run(cmd: list[str], timeout: float = PROBE_TIMEOUT_S) -> subprocess.CompletedProcess:
    # Always an argument list, never a shell string (CLAUDE.md §6).
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _probe(ffmpeg: str, name: str, kind: str, args: list[str]) -> Probe:
    start = time.perf_counter()
    try:
        p = _run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", *args])
        ok, detail = p.returncode == 0, p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""
    except subprocess.TimeoutExpired:
        ok, detail = False, f"timed out after {PROBE_TIMEOUT_S} s"
    return Probe(name=name, kind=kind, ok=ok, seconds=round(time.perf_counter() - start, 2),
                 detail="" if ok else detail[:300])


def _make_hevc10_sample(ffmpeg: str, directory: Path) -> Path | None:
    sample = directory / "hevc10.mp4"
    p = _run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", *_SRC, "-c:v", "libx265",
              "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error", "-y", str(sample)])
    return sample if p.returncode == 0 else None


def inspect_ffmpeg(run_probes: bool = True) -> FfmpegInfo:
    ffmpeg, ffprobe = find_ffmpeg()
    info = FfmpegInfo(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        version=parse_version(_run([ffmpeg, "-hide_banner", "-version"]).stdout),
        hwaccels=parse_hwaccels(_run([ffmpeg, "-hide_banner", "-hwaccels"]).stdout),
        encoders=sorted(parse_codec_list(_run([ffmpeg, "-hide_banner", "-encoders"]).stdout)),
        filters=sorted(parse_codec_list(_run([ffmpeg, "-hide_banner", "-filters"]).stdout)),
    )
    build_file = Path(ffmpeg).parent.parent / "BUILD.json"
    if build_file.is_file():
        info.build = json.loads(build_file.read_text(encoding="utf-8"))
    if not run_probes:
        return info

    jobs: list[tuple[str, str, list[str]]] = []
    jobs += [(d, "device", ["-init_hw_device", f"{d}=hw", "-f", "lavfi", "-i", "nullsrc=s=64x64",
                            "-frames:v", "1", *_NULL]) for d in DEVICE_PROBES if d in info.hwaccels]
    jobs += [(n, "encoder", [*_SRC, *a, *_NULL]) for n, a in ENCODER_PROBES.items() if n in info.encoders]
    jobs += [(n, "filter", [*_SRC, *a, *_NULL]) for n, a in FILTER_PROBES.items() if n in info.filters]

    with tempfile.TemporaryDirectory(prefix="clipsana-doctor-") as tmp:
        sample = _make_hevc10_sample(ffmpeg, Path(tmp)) if "libx265" in info.encoders else None
        if sample:
            jobs += [(n, "decoder", [*a, "-i", str(sample), *_NULL]) for n, a in DECODER_PROBES.items()]
        # Probes are independent and mostly wait on drivers, so running a few at once keeps doctor snappy.
        with ThreadPoolExecutor(max_workers=4) as pool:
            info.probes = list(pool.map(lambda j: _probe(ffmpeg, *j), jobs))
    return info
