"""Well-known locations: per-user app data and the vendored ffmpeg."""
from __future__ import annotations

import os
from pathlib import Path

# Repository root in a source checkout (clipsana/core/paths.py -> ../../).
REPO_ROOT = Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    """Directory for config, database and reports.

    CLIPSANA_HOME overrides the default so development and tests never touch the user's real
    profile (and can keep data off the system drive).
    """
    override = os.environ.get("CLIPSANA_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    return Path(base) / "Clipsana"


def vendored_ffmpeg_dir() -> Path:
    return REPO_ROOT / "vendor" / "ffmpeg"
