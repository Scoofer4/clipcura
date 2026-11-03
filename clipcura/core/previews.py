"""Still frames for the GUI: the original ("before") and the same moment through the plan's filters ("after").

Both use the same timestamp, so the before/after slider compares exactly the same picture. Results are cached
in the app data folder (never next to the originals).
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from clipcura.core.backends import find_ffmpeg
from clipcura.core.paths import app_data_dir

PREVIEW_WIDTH = 640
_TIMEOUT_S = 60


def _cache_dir() -> Path:
    d = app_data_dir() / "previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def filters_from_args(args: list[str]) -> str:
    """The plan's video filter chain without its final pixel-format step (JPEG needs its own)."""
    if "-vf" not in args:
        return ""
    chain = args[args.index("-vf") + 1].split(",")
    while chain and chain[-1].startswith("format="):
        chain.pop()
    return ",".join(chain)


def frame_jpeg(source: Path, at: float, filters: str = "") -> bytes:
    stat = source.stat()
    key = hashlib.sha256(f"{source}|{stat.st_size}|{stat.st_mtime}|{at:.3f}|{filters}|{PREVIEW_WIDTH}".encode())
    cached = _cache_dir() / f"{key.hexdigest()[:24]}.jpg"
    if cached.is_file():
        return cached.read_bytes()

    ffmpeg, _ = find_ffmpeg()
    # Scale after the plan's own filters, so rotation, tone-mapping and colour conversion show as they will.
    chain = ",".join(f for f in (filters, f"scale={PREVIEW_WIDTH}:-2:flags=bicubic", "format=yuvj420p") if f)
    p = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(source),
         "-frames:v", "1", "-vf", chain, "-q:v", "4", "-f", "image2", "-c:v", "mjpeg", "pipe:1"],
        capture_output=True, timeout=_TIMEOUT_S, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(p.stderr.decode("utf-8", "replace").strip()[-300:] or "preview failed")
    cached.write_bytes(p.stdout)
    return p.stdout
