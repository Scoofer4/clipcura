"""Well-known locations: per-user app data and the vendored ffmpeg."""
from __future__ import annotations

import os
from pathlib import Path

# Repository root in a source checkout (clipcura/core/paths.py -> ../../).
REPO_ROOT = Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    """Directory for config, database and reports.

    CLIPCURA_HOME overrides the default so development and tests never touch the user's real
    profile (and can keep data off the system drive).
    """
    override = os.environ.get("CLIPCURA_HOME")
    if override:
        return Path(override)
    return _appdata() / "Clipcura"


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


# The project was called Clipsana until 2026-11-03, when the name turned out to be taken (#19).
LEGACY_NAME = "Clipsana"


def migrate_legacy_app_data() -> Path | None:
    """Move settings, access token, database and profiles from the old app data folder, once. A folder under
    the new name is never touched; with CLIPCURA_HOME set there is nothing to migrate."""
    if os.environ.get("CLIPCURA_HOME"):
        return None
    old, new = _appdata() / LEGACY_NAME, app_data_dir()
    if not old.is_dir() or new.exists():
        return None
    try:
        old.rename(new)
    except OSError:  # files in use by a still-running old version: keep both and try on the next start
        return None
    return new


def vendored_ffmpeg_dir() -> Path:
    return REPO_ROOT / "vendor" / "ffmpeg"
