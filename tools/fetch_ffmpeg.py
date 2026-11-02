"""Download the pinned redistributable FFmpeg build into vendor/ffmpeg.

Why a pinned dated build: BtbN's "latest" tag is rolling, so the same command could silently
produce a different binary tomorrow. Pinning the autobuild tag + verifying SHA-256 makes the
vendored ffmpeg reproducible and lets the installer reference the exact corresponding source.

Usage:  uv run python tools/fetch_ffmpeg.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

# GPL build without "nonfree" parts: freely redistributable (CLAUDE.md §4).
RELEASE_TAG = "autobuild-2026-11-02-12-51"
ASSET = "ffmpeg-n8.1.3-32-g760d10603e-win64-gpl-8.1.zip"
FFMPEG_COMMIT = "760d10603e"
BASE_URL = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{RELEASE_TAG}"

ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "vendor" / "ffmpeg"


def parse_checksums(text: str) -> dict[str, str]:
    """Parse sha256sum output ("<hash>  <name>" or "<hash> *<name>") into {name: hash}."""
    result = {}
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            result[parts[1].lstrip("*")] = parts[0]
    return result


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected.lower():
        raise ValueError(f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}")


def _download(url: str, dest: Path) -> None:
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as resp, dest.open("wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / total:6.1%}", end="", flush=True)
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="replace an existing vendor/ffmpeg")
    args = ap.parse_args()

    if VENDOR_DIR.exists():
        if not args.force:
            print(f"{VENDOR_DIR} already exists (use --force to replace it).")
            return 0
        shutil.rmtree(VENDOR_DIR)

    # Downloads are untrusted until verified, so they go to a fresh empty directory
    # (inside the git-ignored vendor/ so nothing lands on the system drive).
    (ROOT / "vendor").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ffmpeg-dl-", dir=ROOT / "vendor") as tmp:
        tmp_dir = Path(tmp)
        sums_path, zip_path = tmp_dir / "checksums.sha256", tmp_dir / ASSET
        _download(f"{BASE_URL}/checksums.sha256", sums_path)
        expected = parse_checksums(sums_path.read_text(encoding="utf-8")).get(ASSET)
        if not expected:
            raise SystemExit(f"{ASSET} is not listed in checksums.sha256")
        _download(f"{BASE_URL}/{ASSET}", zip_path)
        verify_sha256(zip_path, expected)
        print("SHA-256 verified.")

        extract_dir = tmp_dir / "extract"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)  # zipfile strips absolute paths and ".." components
        (top,) = [p for p in extract_dir.iterdir() if p.is_dir()]

        VENDOR_DIR.mkdir(parents=True)
        shutil.move(str(top / "bin"), VENDOR_DIR / "bin")
        shutil.move(str(top / "LICENSE.txt"), VENDOR_DIR / "LICENSE.txt")

    # Provenance for the installer: GPL requires pointing to the corresponding source code.
    (VENDOR_DIR / "BUILD.json").write_text(json.dumps({
        "asset": ASSET,
        "sha256": expected,
        "release": f"https://github.com/BtbN/FFmpeg-Builds/releases/tag/{RELEASE_TAG}",
        "ffmpeg_source": f"https://github.com/FFmpeg/FFmpeg/commit/{FFMPEG_COMMIT}",
        "build_scripts": "https://github.com/BtbN/FFmpeg-Builds",
        "license": "GPL-3.0-or-later (see LICENSE.txt)",
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"FFmpeg installed to {VENDOR_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
