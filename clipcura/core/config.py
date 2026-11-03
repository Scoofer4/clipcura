"""Per-user settings in <app data>/config.json: API token, port, allowed folders, approvals, concurrency."""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, PositiveInt

from clipcura.core.paths import app_data_dir

CONFIG_NAME = "config.json"


class Concurrency(BaseModel):
    gpu: PositiveInt = 1   # one GPU job keeps NVENC/NVDEC sessions and VRAM predictable on laptop GPUs
    cpu: PositiveInt = 1


class Config(BaseModel):
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    port: int = 0                          # 0 = pick a free port at start
    allowed_roots: list[str] = Field(default_factory=list)
    approval_mode: bool = True             # jobs requested by AI wait for a human (CLAUDE.md §10)
    concurrency: Concurrency = Field(default_factory=Concurrency)
    interface: Literal["window", "browser"] = "window"   # where the desktop app shows the GUI (#23)
    update_check: bool | None = None       # daily check for new versions; None = not asked yet (#22)


def _path() -> Path:
    return app_data_dir() / CONFIG_NAME


def save_config(cfg: Config) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")


def load_config() -> Config:
    path = _path()
    if path.is_file():
        return Config.model_validate_json(path.read_text(encoding="utf-8"))
    cfg = Config()
    save_config(cfg)  # persist the generated token so every client reads the same one
    return cfg


def disallow_root(folder: Path | str) -> Config:
    cfg = load_config()
    resolved = str(Path(folder).resolve())
    cfg.allowed_roots = [r for r in cfg.allowed_roots if Path(r).resolve() != Path(resolved)]
    save_config(cfg)
    return cfg


def allow_root(folder: Path | str) -> Config:
    cfg = load_config()
    resolved = str(Path(folder).resolve())
    if resolved not in cfg.allowed_roots:
        cfg.allowed_roots.append(resolved)
        save_config(cfg)
    return cfg
