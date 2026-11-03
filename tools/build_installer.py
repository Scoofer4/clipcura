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
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
BUILD = PACKAGING / "build"
DIST = PACKAGING / "dist"
APP_DIR = DIST / "Clipsana"

sys.path.insert(0, str(ROOT))
from clipsana import __version__

VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
          StringStruct('CompanyName', 'Metaverse Media s.r.o.'),
          StringStruct('FileDescription', 'Clipsana - check and fix footage before editing'),
          StringStruct('FileVersion', '{v}'),
          StringStruct('InternalName', 'Clipsana'),
          StringStruct('LegalCopyright', 'Apache-2.0'),
          StringStruct('OriginalFilename', 'Clipsana.exe'),
          StringStruct('ProductName', 'Clipsana'),
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


def runtime_distributions() -> list[str]:
    """Names of the Python packages the app ships (no dev tools), from the lock file."""
    out = subprocess.run(["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "--no-header",
                          "--no-annotate"], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    names = []
    for line in out.splitlines():
        line = line.split(";")[0].strip()
        if line and not line.startswith(("#", "-")):
            names.append(line.split("==")[0].split("[")[0])
    return names


def third_party_notices(target: Path) -> Path:
    """One file with the licence of every bundled Python package (MIT/BSD/Apache all require the text to travel
    with the program) plus where ffmpeg's source is."""
    parts = ["Clipsana bundles the following third-party software.\n"]
    build = json.loads((ROOT / "vendor" / "ffmpeg" / "BUILD.json").read_text(encoding="utf-8"))
    parts.append(f"\n==== FFmpeg ({build['asset']}) ====\nLicence: {build['license']}; the full text is in "
                 f"vendor\\ffmpeg\\LICENSE.txt.\nFFmpeg runs as a separate program; Clipsana calls it as a process.\n"
                 f"Corresponding source code: {build['ffmpeg_source']}\nBuild scripts: {build['build_scripts']}\n"
                 f"Binary release: {build['release']}\n")
    missing = []
    for name in sorted(runtime_distributions(), key=str.lower):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        files = [f for f in dist.files or [] if any(k in f.name.upper() for k in ("LICENSE", "LICENCE", "COPYING",
                                                                                   "NOTICE", "AUTHORS"))]
        meta = dist.metadata
        licence = meta.get("License-Expression") or meta.get("License") or ""
        parts.append(f"\n==== {meta['Name']} {dist.version} ====\nLicence: {licence.splitlines()[0] if licence else '?'}\n")
        texts = [Path(str(dist.locate_file(f))) for f in files]
        texts = [t for t in texts if t.is_file()]
        if not texts:
            missing.append(meta["Name"])
        for t in texts:
            parts.append(f"\n--- {t.name} ---\n{t.read_text(encoding='utf-8', errors='replace')}\n")
    if missing:
        print("note: no licence file shipped by:", ", ".join(missing))
    target.write_text("".join(parts), encoding="utf-8")
    return target


def prepare() -> None:
    from clipsana.desktop import icon

    BUILD.mkdir(parents=True, exist_ok=True)
    icon.write_ico(BUILD / "clipsana.ico")
    parts = [int(p) for p in __version__.split(".")[:3]] + [0]
    (BUILD / "version.txt").write_text(VERSION_TEMPLATE.format(t=tuple(parts), v=__version__), encoding="utf-8")
    third_party_notices(BUILD / "THIRD-PARTY-NOTICES.txt")


def pyinstaller() -> None:
    run([sys.executable, "-m", "PyInstaller", str(PACKAGING / "clipsana.spec"), "--noconfirm",
         "--workpath", str(BUILD / "pyinstaller"), "--distpath", str(DIST)])
    shutil.copy2(BUILD / "THIRD-PARTY-NOTICES.txt", APP_DIR / "THIRD-PARTY-NOTICES.txt")


def smoke_test() -> None:
    """The frozen CLI runs, finds its bundled ffmpeg, profiles and rules."""
    cli = APP_DIR / "clipsana-cli.exe"
    env = os.environ | {"CLIPSANA_HOME": str(BUILD / "smoke-home")}
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
