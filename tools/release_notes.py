"""Write the fixed part of a GitHub Release description (#21) to the file given as the argument: which package to download, the first start, and
where the bundled FFmpeg's source code is (GPL). GitHub appends the list of changes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipcura import __version__

NOTES = """## Download

| Package | For |
|---|---|
| `Clipcura-Setup-{v}.exe` | Install for the current user (no administrator rights). Start menu entry, uninstaller. |
| `Clipcura-{v}-win64-portable.zip` | No installation: unzip anywhere (also a USB drive) and run `Clipcura\\Clipcura.exe`. Settings and history stay in the `data` folder next to it. |

Both contain the same app, including FFmpeg. Windows 10 22H2 or newer, 64-bit. Check a download against
`SHA256SUMS.txt`: `Get-FileHash <file> -Algorithm SHA256` in PowerShell.

The packages are not code-signed yet, so Windows SmartScreen may warn on the first start: **More info → Run anyway**.

The window uses Microsoft Edge WebView2 Runtime, which comes with Windows 11 and current Windows 10. Your default
browser does not matter.

## FFmpeg

Clipcura ships FFmpeg as a separate program under the GPL: {asset}.
Build: {release} · source code: {source} · build scripts: {scripts}.
"""


def main() -> None:
    build = json.loads((ROOT / "vendor" / "ffmpeg" / "BUILD.json").read_text(encoding="utf-8"))
    notes = NOTES.format(v=__version__, asset=build["asset"], release=build["release"], source=build["ffmpeg_source"],
                         scripts=build["build_scripts"])
    # Written as a UTF-8 file: a Windows console code page cannot print every character of the notes.
    Path(sys.argv[1]).write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()
