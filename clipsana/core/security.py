"""Folder whitelist for everything that arrives through the API or MCP (CLAUDE.md §10)."""
from __future__ import annotations

from pathlib import Path


class PathNotAllowed(PermissionError):
    pass


def ensure_allowed(path: Path | str, roots: list[str]) -> Path:
    """Return the real path if it lies inside an allowed root, else raise.

    Checked after full resolution, so `..` segments and symlinks/junctions cannot step outside a root.
    Windows paths compare case-insensitively.
    """
    if not roots:
        raise PathNotAllowed("No folders are allowed yet - allow one with `clipsana config allow <folder>` "
                             "or in the app settings")
    real = Path(path).resolve()
    for root in roots:
        root_real = Path(root).resolve()
        if real == root_real or real.is_relative_to(root_real):
            return real
    raise PathNotAllowed(f"{real} is outside the allowed folders")
