"""The pinned redistributable FFmpeg build: download, verify, unpack into the vendored folder.

Used by `tools/fetch_ffmpeg.py` for development and by the app to restore a missing FFmpeg after the user agrees
(#22). FFmpeg is not updated separately from Clipcura: GPU quality calibration and the tests are tied to this
build, so a newer FFmpeg arrives with a new Clipcura release.

Why a pinned dated build: BtbN's "latest" tag is rolling, so the same command could silently produce a different
binary tomorrow. Pinning the autobuild tag + verifying SHA-256 makes the vendored ffmpeg reproducible and lets the
installer reference the exact corresponding source.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

# GPL build without "nonfree" parts: freely redistributable (CLAUDE.md §4).
# Pin only a month's last build: BtbN keeps those for two years, daily builds only 14 days (#25).
RELEASE_TAG = "autobuild-2026-10-31-12-59"
ASSET = "ffmpeg-n8.1.3-27-g8dca1586f4-win64-gpl-8.1.zip"
ASSET_SHA256 = "401dffcf14c301082e1fc03b0bc876b92ea676bfc521fc56e80a1537d137034f"
FFMPEG_COMMIT = "8dca1586f4"
BASE_URL = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{RELEASE_TAG}"

Progress = Callable[[int, int], None]   # bytes done, bytes total (0 when unknown)


def parse_checksums(text: str) -> dict[str, str]:
    """Parse sha256sum output ("<hash>  <name>" or "<hash> *<name>") into {name: hash}."""
    result = {}
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            result[parts[1].lstrip("*")] = parts[0]
    return result


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    actual = sha256_of(path)
    if actual.lower() != expected.lower():
        raise ValueError(f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}")


def download(url: str, dest: Path, progress: Progress | None = None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Clipcura"})
    with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)


def install(vendor_dir: Path, progress: Progress | None = None) -> Path:
    """Download the pinned build into `vendor_dir` (which must not exist yet) and record where it came from."""
    # Downloads are untrusted until verified, so they go to a fresh empty directory next to the target (same
    # drive, so nothing lands on the system drive and the final move is a rename).
    vendor_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ffmpeg-dl-", dir=vendor_dir.parent) as tmp:
        tmp_dir = Path(tmp)
        sums_path, zip_path = tmp_dir / "checksums.sha256", tmp_dir / ASSET
        download(f"{BASE_URL}/checksums.sha256", sums_path)
        expected = parse_checksums(sums_path.read_text(encoding="utf-8")).get(ASSET)
        if not expected:
            raise ValueError(f"{ASSET} is not listed in checksums.sha256")
        if expected.lower() != ASSET_SHA256:
            raise ValueError(f"checksums.sha256 lists {expected} for {ASSET}, but the pin is {ASSET_SHA256}")
        download(f"{BASE_URL}/{ASSET}", zip_path, progress)
        verify_sha256(zip_path, ASSET_SHA256)

        extract_dir = tmp_dir / "extract"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)  # zipfile strips absolute paths and ".." components
        (top,) = [p for p in extract_dir.iterdir() if p.is_dir()]

        vendor_dir.mkdir(parents=True)
        shutil.move(str(top / "bin"), vendor_dir / "bin")
        shutil.move(str(top / "LICENSE.txt"), vendor_dir / "LICENSE.txt")

    # Provenance for the installer: GPL requires pointing to the corresponding source code.
    (vendor_dir / "BUILD.json").write_text(json.dumps({
        "asset": ASSET,
        "sha256": ASSET_SHA256,
        "release": f"https://github.com/BtbN/FFmpeg-Builds/releases/tag/{RELEASE_TAG}",
        "ffmpeg_source": f"https://github.com/FFmpeg/FFmpeg/commit/{FFMPEG_COMMIT}",
        "build_scripts": "https://github.com/BtbN/FFmpeg-Builds",
        "license": "GPL-3.0-or-later (see LICENSE.txt)",
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }, indent=2) + "\n", encoding="utf-8")
    return vendor_dir
