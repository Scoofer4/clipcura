"""Clipcura desktop app (CLAUDE.md §3, M5): the GUI in a native WebView2 window, the local service in the same
process, and an icon in the notification area that shows batch progress and announces finished batches and
assistant requests waiting for approval.

If a service already runs (started earlier by the MCP server), the window attaches to it instead of starting a
second worker, so people and assistants always see the same queue.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading

import httpx

from clipcura.core.config import load_config
from clipcura.core.paths import app_data_dir

log = logging.getLogger(__name__)
POLL_S = 1.0

MENU = {
    "en": {"open": "Open Clipcura", "pause": "Pause queue", "quit": "Quit",
           "background": "Clipcura keeps running here. Conversions continue; quit from this icon."},
    "cs": {"open": "Otevřít Clipcuru", "pause": "Pozastavit frontu", "quit": "Ukončit",
           "background": "Clipcura běží dál tady. Převody pokračují; ukončíte ji z této ikony."},
}


def ui_language() -> str:
    """Czech when Windows speaks Czech (or CLIPCURA_LANG says so), English otherwise."""
    forced = os.environ.get("CLIPCURA_LANG")
    if forced:
        return "cs" if forced == "cs" else "en"
    if sys.platform == "win32":
        return "cs" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x05 else "en"
    return "en"


class DesktopApp:
    def __init__(self) -> None:
        from clipcura.desktop.monitor import BatchMonitor

        self.lang = ui_language()
        self.text = MENU[self.lang]
        self.monitor = BatchMonitor(lang=self.lang)
        self.service = None          # ServiceThread when this process hosts the API and worker
        self.window = None
        self.tray = None
        self.quitting = threading.Event()
        self._told_background = False
        self._client: httpx.Client | None = None

    # --- lifecycle -----------------------------------------------------------------------------------------
    def run(self) -> None:
        import webview

        from clipcura.api.server import ServiceThread, gui_url, running_server

        cfg = load_config()
        info = running_server()
        if info is None:
            self.service = ServiceThread()
            info = self.service.start()
        self._client = httpx.Client(base_url=info["url"], timeout=5,
                                    headers={"Authorization": f"Bearer {cfg.token}"})
        self.window = webview.create_window("Clipcura", gui_url(info["url"], cfg.token), width=1360, height=860,
                                            min_size=(1024, 680), background_color="#12151A")
        self.window.events.closing += self._on_closing
        self._start_tray()
        threading.Thread(target=self._watch, name="clipcura-monitor", daemon=True).start()
        # WebView2 keeps its profile (theme, language, cache) with the rest of Clipcura's data.
        storage = app_data_dir() / "webview"
        webview.start(private_mode=False, storage_path=str(storage))
        self._shutdown()

    def _start_tray(self) -> None:
        if sys.platform != "win32":
            return
        from clipcura.desktop import icon
        from clipcura.desktop.tray import Tray

        tray = Tray(lambda size: icon.png(size), "Clipcura", self._menu, self.show, on_quit=self.quit)
        self.tray = tray if tray.start() else None

    def _shutdown(self) -> None:
        self.quitting.set()
        if self.service:
            self.service.stop()
        if self._client:
            self._client.close()
        # The icon goes last: the installer waits for its window to disappear before it replaces files (#18).
        if self.tray:
            self.tray.stop()

    # --- window --------------------------------------------------------------------------------------------
    def show(self) -> None:
        if self.window:
            self.window.show()
            self.window.restore()

    def quit(self) -> None:
        self.quitting.set()
        if self.window:
            self.window.destroy()   # ends webview.start(); run() then stops the tray and the service

    def _on_closing(self) -> bool | None:
        if self.quitting.is_set() or self.tray is None or _session_ending():
            # Really close: on request, without a notification area to live in, or when Windows logs off or
            # shuts down (refusing would hold the session up, #18).
            return None
        # Closing the window keeps the app (and running conversions) alive in the notification area.
        threading.Thread(target=self.window.hide, daemon=True).start()
        if not self._told_background:
            self._told_background = True
            self.tray.notify("Clipcura", self.text["background"])
        return False

    # --- notification area ---------------------------------------------------------------------------------
    def _menu(self):
        from clipcura.desktop.tray import MenuItem

        return [MenuItem(self.text["open"], self.show),
                MenuItem(self.text["pause"], self._toggle_pause, checked=self.monitor.paused),
                MenuItem("-", None),
                MenuItem(self.text["quit"], self.quit)]

    def _toggle_pause(self) -> None:
        try:
            r = self._client.post("/api/queue", json={"paused": not self.monitor.paused})
            self.monitor.paused = r.json()["paused"]
        except (httpx.HTTPError, ValueError, KeyError):
            log.warning("could not change the queue state", exc_info=True)

    def _watch(self) -> None:
        from clipcura.desktop import icon

        last = None
        while not self.quitting.wait(POLL_S):
            try:
                jobs = self._client.get("/api/jobs", params={"limit": 200}).json()
                self.monitor.paused = self._client.get("/api/queue").json()["paused"]
            except (httpx.HTTPError, ValueError, KeyError):
                continue  # the service is starting or stopping; try again on the next tick
            for notice in self.monitor.update(jobs):
                if self.tray:
                    self.tray.notify(notice.title, notice.message)
            s = self.monitor.state
            # Quantised so the icon is redrawn about once per percent, not on every progress tick.
            look = (None if s.progress is None else round(s.progress * 100), s.attention, self.monitor.tooltip())
            if self.tray and look != last:
                last = look
                progress = None if s.progress is None else look[0] / 100
                self.tray.update(lambda size, p=progress, a=s.attention: icon.png(size, progress=p, attention=a),
                                 look[2])


def _session_ending() -> bool:
    SM_SHUTTINGDOWN = 0x2000
    return sys.platform == "win32" and bool(ctypes.windll.user32.GetSystemMetrics(SM_SHUTTINGDOWN))


def run_app() -> None:
    from clipcura.core.paths import migrate_legacy_app_data

    migrate_legacy_app_data()  # the app was called Clipsana until 2026-11-03 (#19)
    if sys.platform == "win32":
        from clipcura.desktop.tray import show_running_instance

        if show_running_instance():
            return
    DesktopApp().run()
