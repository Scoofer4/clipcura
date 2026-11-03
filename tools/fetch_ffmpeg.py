"""Download the pinned redistributable FFmpeg build into vendor/ffmpeg (pin and checks: clipcura/core/ffmpeg_build.py).

Usage:  uv run python tools/fetch_ffmpeg.py [--force]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipcura.core.ffmpeg_build import (  # re-exported for the tests  # noqa: F401
    ASSET,
    ASSET_SHA256,
    RELEASE_TAG,
    install,
    parse_checksums,
    verify_sha256,
)

VENDOR_DIR = ROOT / "vendor" / "ffmpeg"


def _progress(done: int, total: int) -> None:
    if total:
        print(f"\r  {done / total:6.1%}", end="", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="replace an existing vendor/ffmpeg")
    args = ap.parse_args()

    if VENDOR_DIR.exists():
        if not args.force:
            print(f"{VENDOR_DIR} already exists (use --force to replace it).")
            return 0
        shutil.rmtree(VENDOR_DIR)

    print(f"Downloading {ASSET} ({RELEASE_TAG})")
    install(VENDOR_DIR, _progress)
    print(f"\nSHA-256 verified. FFmpeg installed to {VENDOR_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
