# PyInstaller spec (onedir): Clipcura.exe (windowed app) and clipcura-cli.exe (console: CLI, serve, MCP) share
# one folder. Build with tools/build_installer.py, which prepares the UI build and the icon first.
# Resources keep their repository layout under _internal/, so clipcura.core.paths.REPO_ROOT finds them.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
BUILD = Path(SPECPATH) / "build"
ICON = str(BUILD / "clipcura.ico")

datas = [
    (str(ROOT / "profiles"), "profiles"),
    (str(ROOT / "ui" / "dist"), "ui/dist"),
    # ffmpeg ships as a separate GPL program next to the app (CLAUDE.md §4), with its licence and build record.
    # ffplay is not used, so it stays out.
    (str(ROOT / "vendor" / "ffmpeg" / "bin" / "ffmpeg.exe"), "vendor/ffmpeg/bin"),
    (str(ROOT / "vendor" / "ffmpeg" / "bin" / "ffprobe.exe"), "vendor/ffmpeg/bin"),
    (str(ROOT / "vendor" / "ffmpeg" / "LICENSE.txt"), "vendor/ffmpeg"),
    (str(ROOT / "vendor" / "ffmpeg" / "BUILD.json"), "vendor/ffmpeg"),
    (str(ROOT / "LICENSE"), "."),
    # Written by tools/build_installer.py: the About screen's component list and the licence texts.
    (str(BUILD / "licenses.json"), "."),
    (str(BUILD / "THIRD-PARTY-NOTICES.txt"), "."),
    (str(ROOT / "NOTICE"), "."),
]
# Rules are found by scanning the package, and uvicorn picks protocol modules at runtime: name them all.
hidden = collect_submodules("clipcura") + collect_submodules("uvicorn") + collect_submodules("websockets")
excludes = ["tkinter", "pytest", "ruff", "PyInstaller"]


def analysis(script):
    return Analysis([str(Path(SPECPATH) / script)], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
                    excludes=excludes, noarchive=False)


gui, cli = analysis("entry_gui.py"), analysis("entry_cli.py")
version = str(BUILD / "version.txt")
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="Clipcura", icon=ICON, console=False,
              version=version, upx=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="clipcura-cli", icon=ICON,
              console=True, version=version, upx=False)
COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, name="Clipcura", upx=False)
