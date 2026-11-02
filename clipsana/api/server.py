"""Run the API + worker headless (`clipsana serve`) and announce where it listens in <app data>/server.json,
so the GUI window and the MCP server can find a running instance instead of starting a second one."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
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


def running_server() -> dict | None:
    """The announced server if it actually answers (server.json can outlive a crashed process)."""
    path = server_file()
    if not path.is_file():
        return None
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        with urllib.request.urlopen(f"{info['url']}/api/health", timeout=1) as r:
            return info if r.status == 200 else None
    except (OSError, ValueError, KeyError):
        return None


def gui_url(base: str, token: str) -> str:
    # The token goes in the fragment: browsers never send fragments to servers, so it stays out of logs.
    return f"{base}/#token={urllib.parse.quote(token)}"


def start_background() -> dict:
    """Start `clipsana serve` detached from this console and wait until it answers."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    cmd = [sys.executable, "-m", "clipsana.cli", "serve"]
    # MCP clients may run their server in a Windows job object that kills every member when the session ends;
    # the service (and the conversions a person approves later) must outlive the session, so leave the job.
    # Not every job allows that; then the service lives as long as the session and the next start resumes jobs.
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000) if sys.platform == "win32" else 0
    for extra in ((breakaway, 0) if breakaway else (0,)):
        try:
            subprocess.Popen(cmd, creationflags=flags | extra, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True)
            break
        except OSError:
            if not extra:
                raise
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if info := running_server():
            return info
        time.sleep(0.3)
    raise RuntimeError("Clipsana service did not start within 30 s")


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
