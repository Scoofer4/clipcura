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
