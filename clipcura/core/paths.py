"""Well-known locations: per-user app data and the vendored ffmpeg."""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path
from typing import Literal

# Repository root in a source checkout (clipcura/core/paths.py -> ../../); `_internal` in a packaged build.
REPO_ROOT = Path(__file__).resolve().parents[2]

# The portable ZIP carries this file next to Clipcura.exe; the installer does not (#21).
PORTABLE_MARKER = "portable.txt"

InstallKind = Literal["source", "installed", "portable"]


def install_dir() -> Path | None:
    """Folder with Clipcura.exe in a packaged build, None when running from a source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def install_kind() -> InstallKind:
    folder = install_dir()
    if folder is None:
        return "source"
    return "portable" if (folder / PORTABLE_MARKER).is_file() else "installed"


@functools.cache
def portable_data_dir() -> Path | None:
    """`<app folder>\\data` for the portable package, so the whole app moves with its folder (USB drive).
    None when the app is installed or the folder is read-only (then the data goes to the user profile)."""
    if install_kind() != "portable":
        return None
    data = install_dir() / "data"
    try:
        data.mkdir(exist_ok=True)
        probe = data / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        return None
    return data


def app_data_dir() -> Path:
    """Directory for config, database and reports.

    CLIPCURA_HOME overrides the default so development and tests never touch the user's real
    profile (and can keep data off the system drive).
    """
    override = os.environ.get("CLIPCURA_HOME")
    if override:
        return Path(override)
    return portable_data_dir() or _appdata() / "Clipcura"


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


# The project was called Clipsana until 2026-11-03, when the name turned out to be taken (#19).
LEGACY_NAME = "Clipsana"


def migrate_legacy_app_data() -> Path | None:
    """Move settings, access token, database and profiles from the old app data folder, once. A folder under
    the new name is never touched; with CLIPCURA_HOME set there is nothing to migrate."""
    if os.environ.get("CLIPCURA_HOME") or install_kind() == "portable":
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
