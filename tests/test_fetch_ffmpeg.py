"""Tests for the pure parts of tools/fetch_ffmpeg.py (no network)."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "fetch_ffmpeg", Path(__file__).resolve().parents[1] / "tools" / "fetch_ffmpeg.py"
)
fetch_ffmpeg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fetch_ffmpeg)


def test_parse_checksums_maps_file_names_to_hashes():
    text = (
        "aa11  ffmpeg-a.zip\n"
        "bb22 *ffmpeg-b.zip\n"  # binary-mode marker written by sha256sum -b
        "\n"
    )
    assert fetch_ffmpeg.parse_checksums(text) == {"ffmpeg-a.zip": "aa11", "ffmpeg-b.zip": "bb22"}


def test_verify_sha256_accepts_matching_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"clipcura")
    fetch_ffmpeg.verify_sha256(f, hashlib.sha256(b"clipcura").hexdigest().upper())


def test_verify_sha256_rejects_tampered_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        fetch_ffmpeg.verify_sha256(f, hashlib.sha256(b"clipcura").hexdigest())


def test_pin_is_a_month_end_build_that_btbn_keeps():
    # BtbN deletes daily builds after 14 days but keeps each month's last build for two years (#25).
    import calendar
    import re

    y, m, d = map(int, re.match(r"autobuild-(\d{4})-(\d{2})-(\d{2})", fetch_ffmpeg.RELEASE_TAG).groups())
    assert d == calendar.monthrange(y, m)[1], fetch_ffmpeg.RELEASE_TAG


def test_pin_carries_its_own_checksum():
    # The release's checksums.sha256 alone would not notice a replaced release.
    assert len(fetch_ffmpeg.ASSET_SHA256) == 64 and int(fetch_ffmpeg.ASSET_SHA256, 16) >= 0
