"""Build the Windows installer (M5): UI -> icon, version and licence files -> PyInstaller (onedir) -> smoke test
-> Inno Setup.

    uv run python tools/build_installer.py              # everything, installer in packaging/dist/
    uv run python tools/build_installer.py --no-installer   # stop after the app folder (no Inno Setup needed)

Inno Setup's compiler is taken from --iscc, the ISCC environment variable, PATH, or its default install folders.
PyInstaller keeps a cache in PYINSTALLER_CONFIG_DIR (set it to keep the cache off the system drive).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
BUILD = PACKAGING / "build"
DIST = PACKAGING / "dist"
APP_DIR = DIST / "Clipcura"

sys.path.insert(0, str(ROOT))
from clipcura import __version__

VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
          StringStruct('CompanyName', 'Metaverse Media s.r.o.'),
          StringStruct('FileDescription', 'Clipcura - check and fix footage before editing'),
          StringStruct('FileVersion', '{v}'),
          StringStruct('InternalName', 'Clipcura'),
          StringStruct('LegalCopyright', 'Apache-2.0'),
          StringStruct('OriginalFilename', 'Clipcura.exe'),
          StringStruct('ProductName', 'Clipcura'),
          StringStruct('ProductVersion', '{v}')])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def build_ui() -> None:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        sys.exit("npm not found: install Node.js or pass --skip-ui with an existing ui/dist")
    run([npm, "run", "build"], cwd=ROOT / "ui")


def prepare() -> None:
    from clipcura.desktop import icon

    BUILD.mkdir(parents=True, exist_ok=True)
    icon.write_ico(BUILD / "clipcura.ico")
    parts = [int(p) for p in __version__.split(".")[:3]] + [0]
    (BUILD / "version.txt").write_text(VERSION_TEMPLATE.format(t=tuple(parts), v=__version__), encoding="utf-8")
    # The frozen app has no package metadata: ship the About screen's data and the licence texts as files.
    from clipcura.core import licenses

    (BUILD / licenses.COMPONENTS_FILE).write_text(json.dumps(licenses.components(), indent=1), encoding="utf-8")
    (BUILD / licenses.NOTICES_FILE).write_text(licenses.notices_text(), encoding="utf-8")


def pyinstaller() -> None:
    run([sys.executable, "-m", "PyInstaller", str(PACKAGING / "clipcura.spec"), "--noconfirm",
         "--workpath", str(BUILD / "pyinstaller"), "--distpath", str(DIST)])
    shutil.copy2(BUILD / "THIRD-PARTY-NOTICES.txt", APP_DIR / "THIRD-PARTY-NOTICES.txt")


def smoke_test() -> None:
    """The frozen CLI runs, finds its bundled ffmpeg, profiles and rules."""
    cli = APP_DIR / "clipcura-cli.exe"
    env = os.environ | {"CLIPCURA_HOME": str(BUILD / "smoke-home")}
    for args in (["version"], ["doctor", "--quick", "--json"]):
        out = subprocess.run([str(cli), *args], capture_output=True, text=True, check=True, env=env,
                             timeout=120).stdout
        if args[0] == "doctor":
            report = json.loads(out)
            if not report["ffmpeg"] or "_internal" not in report["ffmpeg"]["ffmpeg"]:
                sys.exit(f"frozen app does not use its bundled ffmpeg: {report['ffmpeg']}")
    print("smoke test ok:", cli)


def find_iscc(explicit: str | None) -> str:
    candidates = [explicit, os.environ.get("ISCC"), shutil.which("iscc"),
                  r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                  str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe")]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    sys.exit("Inno Setup compiler (ISCC.exe) not found: install Inno Setup 6, or pass --iscc / set ISCC")


def installer(iscc: str) -> None:
    run([iscc, f"/DAppVersion={__version__}", f"/O{DIST}", str(PACKAGING / "installer.iss")])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-ui", action="store_true", help="use the existing ui/dist")
    ap.add_argument("--no-installer", action="store_true", help="stop after the app folder")
    ap.add_argument("--iscc", help="path to ISCC.exe")
    args = ap.parse_args()
    if not args.skip_ui:
        build_ui()
    prepare()
    pyinstaller()
    smoke_test()
    if not args.no_installer:
        installer(find_iscc(args.iscc))


if __name__ == "__main__":
    main()
