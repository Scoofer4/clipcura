"""The desktop app end to end (#9): window, in-process service and tray start, and "Quit" takes all of them down.

Opens a real window, so it runs only when asked: CLIPCURA_DESKTOP_TESTS=1 (not on CI)."""
import json
import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not os.environ.get("CLIPCURA_DESKTOP_TESTS"),
                                reason="opens a window; set CLIPCURA_DESKTOP_TESTS=1")

SCRIPT = textwrap.dedent("""
    import ctypes, json, sys, threading, time
    from clipcura.app import DesktopApp
    from clipcura.api.server import running_server

    app = DesktopApp()
    seen = {}

    def drive():
        deadline = time.monotonic() + 60
        while not (app.service and app.service.info and app.tray) and time.monotonic() < deadline:
            time.sleep(0.2)
        time.sleep(3)  # let the window load the GUI and the monitor poll once
        seen["service"] = running_server() is not None
        seen["tray"] = bool(ctypes.windll.user32.FindWindowW("ClipcuraTray", None))
        app.quit()     # what the tray menu's "Quit" calls

    threading.Thread(target=drive, daemon=True).start()
    app.run()
    seen["service_after"] = running_server() is not None
    seen["tray_after"] = bool(ctypes.windll.user32.FindWindowW("ClipcuraTray", None))
    print(json.dumps(seen))
""")


def test_app_starts_everything_and_quit_stops_everything(tmp_path):
    env = os.environ | {"CLIPCURA_HOME": str(tmp_path)}
    p = subprocess.run([sys.executable, "-c", SCRIPT], env=env, capture_output=True, text=True, timeout=120,
                       check=False)
    assert p.returncode == 0, p.stderr[-2000:]
    seen = json.loads(p.stdout.strip().splitlines()[-1])
    assert seen == {"service": True, "tray": True, "service_after": False, "tray_after": False}
    assert not (tmp_path / "server.json").exists()
