"""Target profiles (YAML). User profiles in the app data dir override the bundled ones by name."""
from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath
from typing import Literal

import yaml
from pydantic import ValidationError

from clipsana.core.models import Profile
from clipsana.core.paths import REPO_ROOT, app_data_dir

BUNDLED_DIR = REPO_ROOT / "profiles"


class ProfileError(ValueError):
    pass


def default_search_dirs() -> list[Path]:
    return [app_data_dir() / "profiles", BUNDLED_DIR]


def _read(path: Path) -> Profile:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Profile.model_validate(data)
    except (yaml.YAMLError, ValidationError) as e:
        raise ProfileError(f"Invalid profile {path.name}: {e}") from e


def list_profiles(search_dirs: list[Path] | None = None) -> list[Profile]:
    found: dict[str, Profile] = {}
    for directory in search_dirs or default_search_dirs():
        for path in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
            found.setdefault(path.stem, _read(path))  # earlier dirs win
    return list(found.values())


def load_profile(name: str, search_dirs: list[Path] | None = None) -> Profile:
    dirs = search_dirs or default_search_dirs()
    for directory in dirs:
        path = directory / f"{name}.yaml"
        if path.is_file():
            return _read(path)
    available = sorted({p.stem for d in dirs if d.is_dir() for p in d.glob("*.yaml")})
    raise ProfileError(f"Unknown profile '{name}'. Available: {', '.join(available)}")


# A profile name becomes a file name, so keep it to plain lowercase words.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# builtin: bundled with the app; user: made in settings; edited: a user copy that overrides a bundled one.
Source = Literal["builtin", "user", "edited"]


def user_dir() -> Path:
    return app_data_dir() / "profiles"


def source_of(name: str) -> Source:
    if not (user_dir() / f"{name}.yaml").is_file():
        return "builtin"
    return "edited" if (BUNDLED_DIR / f"{name}.yaml").is_file() else "user"


def validate(data: dict, allowed_roots: list[str]) -> Profile:
    """Check a profile from the editor beyond its schema, so a saved profile can always be planned with."""
    from clipsana import rules
    from clipsana.core import planner
    from clipsana.core.security import PathNotAllowed, ensure_allowed

    try:
        profile = Profile.model_validate(data)
    except ValidationError as e:
        raise ProfileError("; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())) from e
    out = profile.output
    if not NAME_PATTERN.match(profile.name):
        raise ProfileError("Name: use 1-40 lowercase letters, digits and dashes")
    if out.codec not in planner.CODECS:
        raise ProfileError(f"Unknown codec '{out.codec}'. Choose one of: {', '.join(sorted(planner.CODECS))}")
    if out.codec in planner.INTRA_CODECS and out.container == "mp4":
        raise ProfileError(f"{out.codec} needs the mov or mkv container (MP4 cannot carry its PCM audio)")
    folder = PureWindowsPath(out.folder)
    if folder.is_absolute() or folder.drive:
        try:
            ensure_allowed(out.folder, allowed_roots)
        except PathNotAllowed as e:
            raise ProfileError(f"Output folder must be relative to the footage or inside an allowed folder: {e}") \
                from e
    elif str(folder) in (".", "") and not out.suffix:
        raise ProfileError("Output next to the originals needs a suffix, or it would overwrite them")
    known = {r.id for r in rules.load_rules()}
    if unknown := [r for r in profile.rules.disabled if r not in known]:
        raise ProfileError(f"Unknown rule: {', '.join(unknown)}")
    return profile


def save_user_profile(profile: Profile) -> Path:
    path = user_dir() / f"{profile.name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "# Edited in Clipsana settings\n" + yaml.safe_dump(profile.model_dump(), allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return path


def delete_user_profile(name: str) -> None:
    """Remove a user profile; for an edited built-in this brings the bundled version back."""
    path = user_dir() / f"{name}.yaml"
    if not NAME_PATTERN.match(name) or not path.is_file():
        raise ProfileError(f"'{name}' is a built-in profile and cannot be deleted")
    path.unlink()
