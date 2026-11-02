"""Read a media file with ffprobe into MediaInfo. Read-only: never writes next to the original."""
from __future__ import annotations

import itertools
import json
import re
import statistics
import subprocess
from fractions import Fraction
from pathlib import Path

from clipsana.core.backends import find_ffmpeg
from clipsana.core.models import AudioStream, MediaInfo, VideoStream

DEEP_CHECK_SECONDS = 20
DECODE_CHECK_SECONDS = 1
_TIMEOUT_S = 120


def _fps(value: str | None) -> float:
    try:
        f = Fraction(value or "0/0")
    except (ValueError, ZeroDivisionError):
        return 0.0
    return round(float(f), 3) if f.denominator else 0.0


def _bit_depth(pix_fmt: str, raw: str | None) -> int:
    if raw and raw.isdigit():
        return int(raw)
    match = re.search(r"p(\d+)(le|be)?$", pix_fmt)
    return int(match.group(1)) if match else 8


_UNSET = {"", "unknown", "unspecified", "reserved"}


def parse_probe(path: str, data: dict, size: int, first_frame: dict | None = None) -> MediaInfo:
    """Build MediaInfo from ffprobe JSON. `first_frame` colour fields win over the container's tags:
    decoders use the bitstream's values, and some recorders write different ones into the container."""
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    media = MediaInfo(path=path, size=size, container=fmt.get("format_name", ""),
                      duration=float(fmt.get("duration") or 0))
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v:
        rotation = next((int(sd["rotation"]) for sd in v.get("side_data_list", []) if "rotation" in sd), 0)
        pix_fmt = v.get("pix_fmt", "")
        media.video = VideoStream(
            codec=v.get("codec_name", ""), profile=v.get("profile", ""), pix_fmt=pix_fmt,
            width=int(v.get("width", 0)), height=int(v.get("height", 0)),
            r_fps=_fps(v.get("r_frame_rate")), avg_fps=_fps(v.get("avg_frame_rate")),
            color_transfer=v.get("color_transfer", ""), color_primaries=v.get("color_primaries", ""),
            color_space=v.get("color_space", ""), rotation=rotation,
            bit_depth=_bit_depth(pix_fmt, v.get("bits_per_raw_sample")))
        for key in ("color_primaries", "color_transfer", "color_space"):
            value = (first_frame or {}).get(key, "")
            if value not in _UNSET:
                setattr(media.video, key, value)
    else:
        media.probe_error = "no video stream"
    if a:
        media.audio = AudioStream(codec=a.get("codec_name", ""), sample_rate=int(a.get("sample_rate") or 0),
                                  channels=int(a.get("channels") or 0))
    return media


def pts_irregularity(times: list[float]) -> float:
    """Share of frame intervals that differ from the mean by more than 20 %.

    Container frame-rate fields can look fine on VFR phone/screen footage; the real timestamps can't lie.
    """
    ordered = sorted(times)
    deltas = [b - a for a, b in itertools.pairwise(ordered) if b > a]
    if len(deltas) < 2:
        return 0.0
    mean = statistics.fmean(deltas)
    return sum(abs(d - mean) > 0.2 * mean for d in deltas) / len(deltas)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=_TIMEOUT_S, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def probe(path: Path, deep: bool = False, decode_check: bool = True) -> MediaInfo:
    _, ffprobe = find_ffmpeg()
    stat = path.stat()
    p = _run([ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    if p.returncode != 0:
        return MediaInfo(path=str(path), size=stat.st_size, mtime=stat.st_mtime,
                         probe_error=p.stderr.strip()[-300:] or "ffprobe failed")
    frame = _run([ffprobe, "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1", "-show_entries",
                  "frame=color_primaries,color_transfer,color_space", "-print_format", "json", str(path)])
    frames = json.loads(frame.stdout or "{}").get("frames", []) if frame.returncode == 0 else []
    media = parse_probe(str(path), json.loads(p.stdout or "{}"), stat.st_size,
                        first_frame=frames[0] if frames else None)
    media.mtime = stat.st_mtime
    if media.video is None:
        return media
    if media.duration <= 0:
        media.probe_error = "zero duration"
        return media

    if deep:
        out = _run([ffprobe, "-v", "error", "-select_streams", "v:0", "-read_intervals",
                    f"%+{DEEP_CHECK_SECONDS}", "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)])
        times = [float(t) for t in out.stdout.split() if re.fullmatch(r"\d+(\.\d+)?", t)]
        media.pts_irregularity = round(pts_irregularity(times), 4)

    if decode_check:
        # Decode one second from the middle: catches truncated or damaged files that probe fine. ffprobe
        # decodes without muxing, so only decoder errors show up; `ffmpeg -f null` also reports muxer
        # timestamp complaints that healthy VFR screen recordings trigger.
        start = max(0.0, media.duration / 2 - DECODE_CHECK_SECONDS / 2)
        d = _run([ffprobe, "-v", "error", "-select_streams", "v:0", "-read_intervals",
                  f"{start:.3f}%+{DECODE_CHECK_SECONDS}", "-show_entries", "frame=pts_time", "-of", "csv=p=0",
                  str(path)])
        if d.returncode != 0 or d.stderr.strip():
            media.decode_error = (d.stderr.strip() or "decode failed")[-300:]
    return media
