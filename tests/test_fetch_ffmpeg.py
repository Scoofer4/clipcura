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
    f.write_bytes(b"clipsana")
    fetch_ffmpeg.verify_sha256(f, hashlib.sha256(b"clipsana").hexdigest().upper())


def test_verify_sha256_rejects_tampered_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        fetch_ffmpeg.verify_sha256(f, hashlib.sha256(b"clipsana").hexdigest())
