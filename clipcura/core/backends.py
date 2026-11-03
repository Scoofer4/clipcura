"""Locate ffmpeg, discover what it can do on this machine and pick an acceleration backend.

A build lists NVENC/QSV encoders whether or not the hardware exists, so every capability that
matters is confirmed by a tiny real encode/decode ("probe") instead of trusting the listings.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clipcura.core.models import Backend, Benchmarks, EncoderQuality, FfmpegInfo, Paths, Probe
from clipcura.core.paths import vendored_ffmpeg_dir

_EXE = ".exe" if sys.platform == "win32" else ""
PROBE_TIMEOUT_S = 30

# Small synthetic input: big enough for every encoder's minimum size, fast on any CPU.
_SRC = ["-f", "lavfi", "-i", "testsrc2=size=256x144:rate=30", "-frames:v", "5"]
_NULL = ["-f", "null", "-"]

DEVICE_PROBES = ["cuda", "qsv", "d3d11va", "vulkan"]
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
    "hevc10_d3d11va": ["-hwaccel", "d3d11va"],
}


def _binaries_in(directory: Path) -> tuple[str, str] | None:
    ffmpeg, ffprobe = directory / f"ffmpeg{_EXE}", directory / f"ffprobe{_EXE}"
    return (str(ffmpeg), str(ffprobe)) if ffmpeg.is_file() and ffprobe.is_file() else None


def find_ffmpeg() -> tuple[str, str]:
    """Return (ffmpeg, ffprobe): CLIPCURA_FFMPEG dir, then vendor/ffmpeg/bin, then PATH."""
    override = os.environ.get("CLIPCURA_FFMPEG")
    if override:
        found = _binaries_in(Path(override))
        if not found:
            raise FileNotFoundError(f"CLIPCURA_FFMPEG={override} does not contain ffmpeg and ffprobe")
        return found
    found = _binaries_in(vendored_ffmpeg_dir() / "bin")
    if found:
        return found
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe
    raise FileNotFoundError("ffmpeg not found: run `uv run python tools/fetch_ffmpeg.py` or set CLIPCURA_FFMPEG")


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


def _fastest(measured: dict[str, float], default: str) -> str | None:
    working = {k: v for k, v in measured.items() if v > 0}
    if not working:
        return None
    return max(working, key=lambda k: (working[k], k == default))  # ties go to the simpler default


def choose_paths(info: FfmpegInfo | None) -> Paths:
    """Quality first, then measured speed on this machine (CLAUDE.md §4, issue #5)."""
    if info is None:
        return Paths()
    encode = choose_backend(info)
    b = info.benchmarks
    unmeasured_decode = "cuda" if encode == "cuda" else "d3d11va" if info.works("d3d11va") else "cpu"
    decode = (_fastest(b.decode, "cpu") if b else None) or unmeasured_decode
    scale = (_fastest(b.scale, "cpu") if b else None) or "cpu"
    # libplacebo tone-maps with BT.2390 and peak detection: better than zscale+hable, so it wins whenever it
    # works, regardless of speed.
    placebo_ok = b.tonemap.get("libplacebo", 0) > 0 if b and b.tonemap else info.works("libplacebo")
    quality = b.quality if b else {}
    return Paths(decode=decode, encode=encode, scale=scale, tonemap="libplacebo" if placebo_ok else "zscale",
                 gpu_quality={e: r.quality for e, r in quality.items() if r.quality is not None},
                 cpu_only=sorted(e for e, r in quality.items() if r.quality is None))


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


def _make_hevc10_sample(ffmpeg: str, directory: Path, size: str = "256x144", frames: int = 5) -> Path | None:
    sample = directory / f"hevc10_{size}.mp4"
    src = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30", "-frames:v", str(frames)]
    p = _run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", *src, "-c:v", "libx265", "-preset", "ultrafast",
              "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error", "-y", str(sample)])
    return sample if p.returncode == 0 else None


def _bench_size() -> tuple[str, int]:
    # Tests set CLIPCURA_BENCH_FAST to keep the suite quick; real measurements need camera-sized work.
    return ("1280x720", 20) if os.environ.get("CLIPCURA_BENCH_FAST") else ("3840x2160", 60)


def _make_camera_sample(ffmpeg: str, directory: Path) -> Path | None:
    """HEVC at ~40 Mbit/s with film-grain-like noise: as hard to decode as phone footage. A clean synthetic
    clip decodes so cheaply that CPU and GPU look equal although real footage differs 2.6x."""
    size, frames = _bench_size()
    sample = directory / "camera_sample.mp4"
    p = _run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30",
              "-frames:v", str(frames), "-vf", "noise=alls=12:allf=t", "-c:v", "libx265", "-preset", "ultrafast",
              "-x265-params", "log-level=error:bitrate=40000", "-pix_fmt", "yuv420p", "-y", str(sample)],
             timeout=300)
    return sample if p.returncode == 0 else None


def _measure_fps(ffmpeg: str, args: list[str], frames: int) -> float:
    """Whole-job frames per second. A short warm-up run first absorbs one-time costs such as CUDA kernel JIT
    compilation (seconds on a cold driver cache) that no real job pays again."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", *args]
    try:
        warm = _run([*cmd, "-frames:v", "5", *_NULL], timeout=120)
        if warm.returncode != 0:
            return 0.0
        start = time.perf_counter()
        p = _run([*cmd, *_NULL], timeout=300)
    except subprocess.TimeoutExpired:
        return 0.0
    elapsed = time.perf_counter() - start
    return round(frames / elapsed, 1) if p.returncode == 0 and elapsed > 0 else 0.0


def run_benchmarks(info: FfmpegInfo, workdir: Path) -> Benchmarks:
    """Measure whole jobs (decode -> filters -> DNxHR HQ encode), greedily: decoder first, then the scalers
    with the winning decoder, because a GPU scaler only pays off when frames come from a GPU decoder."""
    from clipcura.rules.hdr import LIBPLACEBO_TONEMAP, ZSCALE_TONEMAP

    ffmpeg = info.ffmpeg
    bench = Benchmarks()
    size, frames = _bench_size()
    w, h = (int(x) for x in size.split("x"))
    encode = ["-vf", "{vf}fps=fps=30,format=yuv422p", "-c:v", "dnxhd", "-profile:v", "dnxhr_hq"]

    def job(decode_args: list[str], vf: str = "") -> list[str]:
        return [*decode_args, "-i", str(sample), *[a.format(vf=vf) for a in encode]]

    sample = _make_camera_sample(ffmpeg, workdir)
    if sample:
        decoders = {"cpu": []} | {d: ["-hwaccel", d] for d in ("cuda", "d3d11va") if info.works(d)}
        bench.decode = {k: _measure_fps(ffmpeg, job(a), frames) for k, a in decoders.items()}
        best = _fastest(bench.decode, "cpu") or "cpu"
        tw, th = w // 2, h // 2
        scalers = {"cpu": f"scale={tw}:{th}:flags=lanczos,"}
        if info.works("cuda") and "scale_cuda" in info.filters:
            scalers["scale_cuda"] = (f"format=yuv420p,hwupload_cuda,scale_cuda={tw}:{th}:interp_algo=lanczos,"
                                     "hwdownload,format=yuv420p,")
        if info.works("libplacebo"):
            scalers["libplacebo"] = f"libplacebo=w={tw}:h={th}:downscaler=lanczos:upscaler=lanczos,"
        bench.scale = {k: _measure_fps(ffmpeg, job(decoders[best], vf), frames) for k, vf in scalers.items()}

    # Tone-mapping is chosen by quality (libplacebo wins whenever it works); its speed is informational.
    hlg = ["-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={frames / 30}", "-vf",
           "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc,format=yuv420p10le,{tm}"]
    tonemap = {"zscale": ZSCALE_TONEMAP} | ({"libplacebo": LIBPLACEBO_TONEMAP} if info.works("libplacebo") else {})
    bench.tonemap = {k: _measure_fps(ffmpeg, [*hlg[:-1], hlg[-1].format(tm=tm)], frames) for k, tm in tonemap.items()}
    bench.quality = calibrate_encoders(info, workdir)
    return bench


# How far a GPU encoder may score below its CPU equivalent and still count as the same quality. 0.5 VMAF is
# well under one just-noticeable difference (about 6 points); SSIM is the fallback without libvmaf.
QUALITY_MARGIN = {"vmaf": 0.5, "ssim": 0.002}
_SCORE = {"vmaf": re.compile(r"VMAF score: ([\d.]+)"), "ssim": re.compile(r"SSIM .*All:([\d.]+)")}


def first_matching(steps: list[tuple[int, list[float]]], margin: float) -> tuple[int | None, float | None]:
    """First quality step whose worst per-clip delta (GPU minus CPU score) stays within the margin.
    Without a match, returns None and the best worst-case delta seen, so doctor can say how far off it was."""
    best = None
    for quality, deltas in steps:
        worst = min(deltas)
        if worst >= -margin:
            return quality, round(worst, 3)
        best = worst if best is None else max(best, worst)
    return None, None if best is None else round(best, 3)


def _quality_clips(ffmpeg: str, directory: Path) -> list[Path]:
    """Two lossless references: clean motion graphics, and the same with heavy sensor-like grain. Grain is
    where rate control starves first, so a GPU encoder has to hold up on both."""
    size, frames = ("640x360", 10) if os.environ.get("CLIPCURA_BENCH_FAST") else ("1920x1080", 30)
    clips = []
    for name, vf in (("clean", "null"), ("grain", "noise=alls=8:allf=t")):
        clip = directory / f"quality_{name}.mkv"
        p = _run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30",
                  "-frames:v", str(frames), "-vf", vf, "-pix_fmt", "yuv420p", "-c:v", "ffv1", "-y", str(clip)],
                 timeout=120)
        if p.returncode == 0:
            clips.append(clip)
    return clips


def _score(ffmpeg: str, codec: str, quality: int | None, clip: Path, metric: str) -> float | None:
    from clipcura.core import planner

    args, pix_fmt, _ = planner.encoder_args(codec, "30", quality)
    out = clip.with_name(f"{clip.stem}_{codec}_{quality}.mp4")
    try:
        enc = _run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(clip), "-pix_fmt", pix_fmt, *args,
                    "-an", "-y", str(out)], timeout=300)
        if enc.returncode != 0:
            return None
        # [distorted][reference]; ffmpeg prints the score at info level.
        compare = "libvmaf=n_threads=4" if metric == "vmaf" else "ssim"
        m = _run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(out), "-i", str(clip), "-lavfi",
                  f"[0:v][1:v]{compare}", *_NULL], timeout=300)
    except subprocess.TimeoutExpired:
        return None
    finally:
        out.unlink(missing_ok=True)
    found = _SCORE[metric].search(m.stderr)
    return float(found.group(1)) if m.returncode == 0 and found else None


def calibrate_encoders(info: FfmpegInfo, workdir: Path) -> dict[str, EncoderQuality]:
    """Compare every working GPU encoder with its CPU equivalent on the same clips (issue #14): a faster path
    may only be used when the quality does not drop (CLAUDE.md §4). Tries the encoder's quality steps until
    one matches; an encoder that never matches is reported so auto codecs keep encoding on the CPU."""
    from clipcura.core import planner

    gpu = [e for e in planner.GPU_QUALITY if info.works(e)]
    if not gpu:
        return {}
    ffmpeg = info.ffmpeg
    metric = "vmaf" if "libvmaf" in info.filters else "ssim"
    clips = _quality_clips(ffmpeg, workdir)
    cpu_scores: dict[str, list[float | None]] = {}
    results: dict[str, EncoderQuality] = {}
    for encoder in gpu:
        cpu = planner.cpu_equivalent(encoder)
        if cpu not in cpu_scores:
            cpu_scores[cpu] = [_score(ffmpeg, cpu, None, c, metric) for c in clips]
        reference = cpu_scores[cpu]
        steps: list[tuple[int, list[float]]] = []
        if clips and all(r is not None for r in reference):
            for quality in planner.GPU_QUALITY[encoder][1]:
                scores = [_score(ffmpeg, encoder, quality, c, metric) for c in clips]
                if any(s is None for s in scores):
                    break
                steps.append((quality, [s - r for s, r in zip(scores, reference, strict=True)]))
                if min(steps[-1][1]) >= -QUALITY_MARGIN[metric]:
                    break
        chosen, delta = first_matching(steps, QUALITY_MARGIN[metric])
        results[encoder] = EncoderQuality(cpu_encoder=cpu, metric=metric, quality=chosen, delta=delta)
    return results


def inspect_ffmpeg(run_probes: bool = True, run_benchmarks_too: bool = False) -> FfmpegInfo:
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

    with tempfile.TemporaryDirectory(prefix="clipcura-doctor-") as tmp:
        sample = _make_hevc10_sample(ffmpeg, Path(tmp)) if "libx265" in info.encoders else None
        if sample:
            jobs += [(n, "decoder", [*a, "-i", str(sample), *_NULL]) for n, a in DECODER_PROBES.items()]
        # Probes are independent and mostly wait on drivers, so running a few at once keeps doctor snappy.
        with ThreadPoolExecutor(max_workers=4) as pool:
            info.probes = list(pool.map(lambda j: _probe(ffmpeg, *j), jobs))
        # Benchmarks run one at a time: parallel runs would compete for the same GPU and skew the numbers.
        if run_benchmarks_too:
            info.benchmarks = run_benchmarks(info, Path(tmp))
    return info
