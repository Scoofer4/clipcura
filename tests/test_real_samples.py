"""Checks on real footage, which never goes into git (CLAUDE.md §14).

Put samples in tests/fixtures/real/ or point CLIPSANA_REAL_DIR at a folder; without samples these skip.
"""
import os
from pathlib import Path

import pytest

from clipsana.core import probe, service
from tests.conftest import needs_ffmpeg

REAL_DIR = Path(os.environ.get("CLIPSANA_REAL_DIR", Path(__file__).parent / "fixtures" / "real"))
SAMPLES = sorted(p for p in REAL_DIR.glob("*") if p.suffix.lower() in service.VIDEO_EXTENSIONS) \
    if REAL_DIR.is_dir() else []

pytestmark = [needs_ffmpeg, pytest.mark.skipif(not SAMPLES, reason=f"no real samples in {REAL_DIR}")]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.name)
def test_readable_real_footage_is_not_reported_as_damaged(sample):
    media = probe.probe(sample)
    assert media.probe_error is None
    assert media.decode_error is None
