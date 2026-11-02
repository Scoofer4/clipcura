"""Run the API + worker headless (`clipsana serve`) and announce where it listens in <app data>/server.json,
so the GUI window and the MCP server can find a running instance instead of starting a second one."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import uvicorn

from clipsana.core.config import load_config
from clipsana.core.paths import app_data_dir

HOST = "127.0.0.1"  # never 0.0.0.0: the API is for this machine only (CLAUDE.md §10)
SERVER_FILE = "server.json"


def server_file() -> Path:
    return app_data_dir() / SERVER_FILE


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def serve(port: int | None = None) -> None:
    from clipsana.api.app import create_app

    cfg = load_config()
    port = port or cfg.port or free_port()
    info = {"url": f"http://{HOST}:{port}", "port": port, "pid": os.getpid()}
    path = server_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info), encoding="utf-8")
    try:
        uvicorn.run(create_app(), host=HOST, port=port, log_level="warning")
    finally:
        path.unlink(missing_ok=True)
