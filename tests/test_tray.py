"""Notification-area icon (#9): added, updated and removed again on a real Windows desktop."""
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows notification area")


def test_icon_appears_updates_and_goes_away():
    from clipsana.desktop import icon
    from clipsana.desktop.tray import MenuItem, Tray

    tray = Tray(lambda s: icon.png(s), "Clipsana - test", lambda: [MenuItem("Open", lambda: None)], lambda: None)
    if not tray.start():
        pytest.skip("no notification area in this session (service account / CI)")
    tray.update(lambda s: icon.png(s, progress=0.5), "Clipsana - converting")
    tray.update(lambda s: icon.png(s, attention=True))
    tray.stop()
    assert not any(t.name == "clipsana-tray" and t.is_alive() for t in threading.enumerate())


def test_installer_can_ask_the_running_app_to_quit():
    # Issue #18: the uninstaller posts WM_APP+4 to the "ClipsanaTray" window before it removes files.
    import ctypes

    from clipsana.desktop import icon
    from clipsana.desktop.tray import CLASS_NAME, WM_QUIT_APP, Tray

    asked = threading.Event()
    tray = Tray(lambda s: icon.png(s), "Clipsana - test", list, lambda: None, on_quit=asked.set)
    if not tray.start():
        pytest.skip("no notification area in this session (service account / CI)")
    try:
        assert WM_QUIT_APP == 0x8004  # packaging/installer.iss sends this number
        ctypes.windll.user32.PostMessageW(ctypes.windll.user32.FindWindowW(CLASS_NAME, None), WM_QUIT_APP, 0, 0)
        assert asked.wait(5)
    finally:
        tray.stop()
