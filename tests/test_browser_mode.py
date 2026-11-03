"""Browser mode (#23): Clipcura can show its GUI in the default browser instead of its own WebView2 window."""
import pytest
from fastapi.testclient import TestClient

from clipcura.api.app import create_app
from clipcura.app import choose_interface
from clipcura.core import config


@pytest.mark.parametrize(("requested", "configured", "webview2", "expected"), [
    (False, "window", True, "window"),
    (True, "window", True, "browser"),       # Clipcura.exe --browser
    (False, "browser", True, "browser"),     # chosen in Settings
    (False, "window", False, "browser"),     # WebView2 missing: the app still opens
])
def test_choose_interface(requested, configured, webview2, expected):
    assert choose_interface(requested, configured, webview2) == expected


def test_interface_is_a_setting_people_change_and_assistants_cannot():
    assert config.load_config().interface == "window"
    with TestClient(create_app(), base_url="http://127.0.0.1") as api:
        api.headers["Authorization"] = f"Bearer {config.load_config().token}"
        ai = {"X-Clipcura-Actor": "ai"}
        assert api.patch("/api/config", json={"interface": "browser"}, headers=ai).status_code == 403
        assert api.patch("/api/config", json={"interface": "browser"}).json()["interface"] == "browser"
        assert api.patch("/api/config", json={"interface": "tabs"}).status_code == 422
    assert config.load_config().interface == "browser"


def test_webview2_check_reads_the_registry_like_the_installer(monkeypatch):
    from clipcura.desktop import webview2

    versions = {}
    monkeypatch.setattr(webview2, "_registry_version", lambda hive, key: versions.get((hive, key)))
    assert webview2.installed() is False
    versions[(webview2.HKCU, webview2.CLIENT_KEY)] = "0.0.0.0"   # left behind by an uninstall
    assert webview2.installed() is False
    versions[(webview2.HKLM, webview2.CLIENT_KEY_WOW64)] = "131.0.2903.70"
    assert webview2.installed() is True
