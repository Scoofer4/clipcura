"""Target profiles (YAML). User profiles in the app data dir override the bundled ones by name."""
from __future__ import annotations

from pathlib import Path

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
