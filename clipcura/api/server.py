"""Run the API + worker headless (`clipcura serve`) and announce where it listens in <app data>/server.json,
so the GUI window and the MCP server can find a running instance instead of starting a second one."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import uvicorn

from clipcura.core.config import load_config
from clipcura.core.paths import app_data_dir

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


def login_url(base: str, code: str) -> str:
    """The GUI address for a browser: a one-time code instead of the key (#23)."""
    return f"{base}/#code={urllib.parse.quote(code)}"


def browser_url(info: dict, token: str) -> str:
    """Ask the running service for a one-time code and build the address to open in the default browser."""
    req = urllib.request.Request(f"{info['url']}/api/login-codes", method="POST",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return login_url(info["url"], json.loads(r.read())["code"])


CLI_EXE = "clipcura-cli.exe"  # console executable next to Clipcura.exe in the installed app


def service_command() -> list[str]:
    """How to start `clipcura serve` from this process: the installed app has no Python to run `-m` with."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name(CLI_EXE)), "serve"]
    return [sys.executable, "-m", "clipcura.cli", "serve"]


def start_background() -> dict:
    """Start `clipcura serve` detached from this console and wait until it answers."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    cmd = service_command()
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
    raise RuntimeError("Clipcura service did not start within 30 s")


def _announce(port: int) -> dict:
    info = {"url": f"http://{HOST}:{port}", "port": port, "pid": os.getpid()}
    path = server_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info), encoding="utf-8")
    return info


def _withdraw() -> None:
    # Only our own announcement: a second instance must not hide the first one's.
    path = server_file()
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def serve(port: int | None = None) -> None:
    from clipcura.api.app import create_app

    port = port or load_config().port or free_port()
    _announce(port)
    try:
        uvicorn.run(create_app(), host=HOST, port=port, log_level="warning")
    finally:
        _withdraw()


class ServiceThread:
    """The API and worker inside the desktop app's process (CLAUDE.md §3), announced like `clipcura serve` so
    the MCP server finds it and does not start a second worker."""

    def __init__(self, port: int | None = None, on_restart=None) -> None:
        from clipcura.api.app import create_app

        self.port = port or load_config().port or free_port()
        # The graceful-shutdown limit is a backstop: a client that never lets go must not keep Quit waiting.
        self._server = uvicorn.Server(uvicorn.Config(create_app(on_restart=on_restart), host=HOST, port=self.port, log_level="warning",
                                                     timeout_graceful_shutdown=5))
        self._thread = threading.Thread(target=self._server.run, name="clipcura-service", daemon=True)
        self.info: dict = {}

    def start(self, timeout: float = 30.0) -> dict:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Clipcura service did not start")
            time.sleep(0.05)
        self.info = _announce(self.port)
        return self.info

    def stop(self, timeout: float = 30.0) -> None:
        # Uvicorn's shutdown runs the app lifespan, which stops the worker; queued jobs resume next start.
        _withdraw()
        self._server.should_exit = True
        self._thread.join(timeout)
