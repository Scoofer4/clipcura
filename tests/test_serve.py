"""`clipsana serve` (headless API + worker) and `clipsana config`."""
import json
import os
import subprocess
import sys
import time

import httpx
from typer.testing import CliRunner

from clipsana.cli import app
from clipsana.core import config

runner = CliRunner()


def test_config_allow_and_show_never_print_the_token(tmp_path):
    token = config.load_config().token
    assert runner.invoke(app, ["config", "allow", str(tmp_path)]).exit_code == 0
    shown = runner.invoke(app, ["config", "show"]).output
    assert str(tmp_path.resolve()) in shown
    assert token not in shown and token[:4] in shown  # masked, recognisable


def test_config_approval_can_be_switched(tmp_path):
    runner.invoke(app, ["config", "approval", "off"])
    assert config.load_config().approval_mode is False
    runner.invoke(app, ["config", "approval", "on"])
    assert config.load_config().approval_mode is True


def test_no_running_server_is_detected_from_stale_file(tmp_path, monkeypatch):
    from clipsana.api import server
    monkeypatch.setenv("CLIPSANA_HOME", str(tmp_path))
    assert server.running_server() is None
    (tmp_path / "server.json").write_text('{"url": "http://127.0.0.1:9", "port": 9, "pid": 1}', encoding="utf-8")
    assert server.running_server() is None  # nothing answers there: a leftover from a crash


def test_gui_url_carries_token_only_in_fragment():
    from clipsana.api import server
    url = server.gui_url("http://127.0.0.1:5000", "abc")
    assert url == "http://127.0.0.1:5000/#token=abc"  # fragments never reach servers or logs


def test_serve_starts_api_on_loopback_and_announces_port(tmp_path):
    home = tmp_path / "home"
    env = os.environ | {"CLIPSANA_HOME": str(home)}
    proc = subprocess.Popen([sys.executable, "-m", "clipsana.cli", "serve"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        server_file = home / "server.json"
        deadline = time.monotonic() + 30
        info = None
        while time.monotonic() < deadline:
            if server_file.is_file():
                info = json.loads(server_file.read_text(encoding="utf-8"))
                try:
                    if httpx.get(f"{info['url']}/api/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
            time.sleep(0.2)
        assert info is not None, "server.json was not written"
        # The venv's python.exe on Windows is a launcher; server.json names the real server process.
        assert info["url"].startswith("http://127.0.0.1:") and info["pid"] > 0
        token = json.loads((home / "config.json").read_text(encoding="utf-8"))["token"]
        r = httpx.get(f"{info['url']}/api/profiles", headers={"Authorization": f"Bearer {token}"}, timeout=5)
        assert r.status_code == 200
    finally:
        # Kill the whole tree: terminating only the venv launcher would orphan the real server process.
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
        else:
            proc.terminate()
        proc.wait(timeout=10)


def test_service_stops_promptly_while_the_gui_listens_for_events(tmp_path, monkeypatch):
    # The desktop app's Quit waited 30 s: the event stream never noticed the server closing the socket.
    from websockets.sync.client import connect

    from clipsana.api.server import ServiceThread

    monkeypatch.setenv("CLIPSANA_HOME", str(tmp_path))
    service = ServiceThread()
    info = service.start()
    ws_url = info["url"].replace("http", "ws") + f"/api/events?token={config.load_config().token}"
    with connect(ws_url, additional_headers={"Host": f"127.0.0.1:{info['port']}"}):
        started = time.monotonic()
        service.stop()
        assert time.monotonic() - started < 5
    assert not (tmp_path / "server.json").exists()
