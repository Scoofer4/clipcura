"""Is Microsoft Edge WebView2 Runtime installed? The same registry check the installer makes (packaging/installer.iss).

It ships with Windows 11 and current Windows 10. Without it pywebview would fall back to the old Internet Explorer
engine, which cannot run the GUI, so Clipcura opens in the default browser instead (#23).
"""
from __future__ import annotations

import sys

HKLM, HKCU = "HKLM", "HKCU"
_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
CLIENT_KEY = rf"SOFTWARE\{_CLIENT}"
CLIENT_KEY_WOW64 = rf"SOFTWARE\WOW6432Node\{_CLIENT}"

_LOCATIONS = [(HKLM, CLIENT_KEY_WOW64), (HKLM, CLIENT_KEY), (HKCU, CLIENT_KEY)]


def _registry_version(hive: str, key: str) -> str | None:
    import winreg

    root = winreg.HKEY_LOCAL_MACHINE if hive == HKLM else winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(root, key) as k:
            return str(winreg.QueryValueEx(k, "pv")[0])
    except OSError:
        return None


def installed() -> bool:
    if sys.platform != "win32":
        return True   # other platforms use their own web engine
    return any((v := _registry_version(hive, key)) and v != "0.0.0.0" for hive, key in _LOCATIONS)
