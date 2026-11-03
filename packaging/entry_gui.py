"""Clipcura.exe: the desktop app (window + service + notification-area icon). No console window.
`Clipcura.exe --browser` shows the GUI in the default browser instead of the window (#23)."""
import sys

from clipcura.app import run_app

if __name__ == "__main__":
    run_app(browser="--browser" in sys.argv[1:])
