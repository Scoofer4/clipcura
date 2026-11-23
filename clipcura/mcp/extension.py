"""Claude Desktop extension (.mcpb, #28) for the installed Clipcura.

Claude Desktop shows a server's logo only for extensions, taken from the extension's manifest; servers added in its
config file get a generic icon whatever the server announces. The extension is deliberately small: it carries the
manifest, the logo and a README, not a second copy of the app, and starts `clipcura-cli.exe mcp` from the Clipcura
folder the person picks when installing it. So it always runs the same app (and the same data) as the window.

Format: https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md (manifest version 0.3).
"""
from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path
from typing import Any

from clipcura import SOURCE, __version__
from clipcura.desktop import icon

HOMEPAGE = SOURCE
ICON = "icon.png"
ICON_SIZES = (32, 64, 128, 256, 512)
README = "README.md"
CLI = "clipcura-cli.exe"
# The per-user installer's folder ({autopf} with PrivilegesRequired=lowest in packaging/installer.iss). An
# all-users install or a portable copy is picked in Claude Desktop's extension settings.
DEFAULT_FOLDER = "${HOME}\\AppData\\Local\\Programs\\Clipcura"

DESCRIPTION = "Check video footage before editing in DaVinci Resolve and fix what would make it crash."
LONG_DESCRIPTION = """Clipcura checks footage from phones, action and system cameras and screen recordings, and converts
the clips that cause trouble in DaVinci Resolve: variable frame rate, HDR, 10-bit HEVC, odd sizes, audio that is not
48 kHz, rotation.

This extension connects Claude to the **Clipcura app installed on this computer**; install Clipcura first. Claude
gets the same actions a person has in the Clipcura window and nothing more: originals are never modified, only
allowed folders can be used, and with approval mode on (the default) every conversion Claude requests waits for
your approval in Clipcura."""

BUNDLE_README = """# Clipcura extension for Claude Desktop

This extension starts the MCP server of the Clipcura app installed on this computer
(`clipcura-cli.exe mcp` in the folder chosen in the extension's settings). It contains no program of its own.

Clipcura: {homepage}
"""


def _tools() -> list[dict[str, str]]:
    """The server's own tool list, so the manifest cannot drift from what Claude actually gets."""
    from clipcura.mcp.server import build_server

    tools = asyncio.run(build_server(connect=lambda: None).list_tools())
    return [{"name": t.name, "description": (t.description or "").strip().splitlines()[0]} for t in tools]


def manifest() -> dict[str, Any]:
    return {
        "manifest_version": "0.3",
        "name": "clipcura",
        "display_name": "Clipcura",
        "version": __version__,
        "description": DESCRIPTION,
        "long_description": LONG_DESCRIPTION,
        "author": {"name": "Metaverse Media s.r.o.", "url": HOMEPAGE},
        "repository": {"type": "git", "url": f"{HOMEPAGE}.git"},
        "homepage": HOMEPAGE,
        "documentation": f"{HOMEPAGE}#ai-assistants-mcp",
        "support": f"{HOMEPAGE}/issues",
        "icon": ICON,
        "icons": [{"src": _icon_name(s), "size": f"{s}x{s}"} for s in ICON_SIZES],
        "server": {
            "type": "binary",
            # The program lives in the Clipcura folder, not in the extension; the entry point names a file the
            # bundle does contain, so a client that checks it finds it.
            "entry_point": README,
            "mcp_config": {"command": f"${{user_config.app_folder}}\\{CLI}", "args": ["mcp"], "env": {}},
        },
        "tools": _tools(),
        "keywords": ["video", "ffmpeg", "davinci-resolve", "footage", "transcode"],
        "license": "Apache-2.0",
        "compatibility": {"platforms": ["win32"]},
        "user_config": {
            "app_folder": {
                "type": "directory",
                "title": "Clipcura folder",
                "description": f"The folder with Clipcura.exe and {CLI} (the installed app or a portable copy).",
                "required": True,
                "default": DEFAULT_FOLDER,
            },
        },
    }


def _icon_name(size: int) -> str:
    return ICON if size == max(ICON_SIZES) else f"icons/icon-{size}.png"


def write_mcpb(path: Path) -> Path:
    """The .mcpb is a ZIP with manifest.json at its root."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest(), indent=2, ensure_ascii=False) + "\n")
        z.writestr(README, BUNDLE_README.format(homepage=HOMEPAGE))
        for size in ICON_SIZES:
            z.writestr(_icon_name(size), icon.png(size))
    return path
