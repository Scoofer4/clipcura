"""Claude Desktop extension (#28): a small .mcpb that starts the installed Clipcura's MCP server and carries the logo,
which Claude Desktop shows only for extensions, not for servers added in its config file."""
import asyncio
import io
import json
import zipfile

from mcp.client import Client
from PIL import Image

from clipcura import __version__
from clipcura.mcp import extension
from clipcura.mcp.server import build_server


def test_manifest_starts_the_cli_from_the_chosen_clipcura_folder():
    m = extension.manifest()
    assert m["manifest_version"] == "0.3"
    assert m["name"] == "clipcura" and m["display_name"] == "Clipcura"
    assert m["version"] == __version__
    assert m["server"]["type"] == "binary"
    cfg = m["server"]["mcp_config"]
    assert cfg["command"] == "${user_config.app_folder}\\clipcura-cli.exe"
    assert cfg["args"] == ["mcp"]
    folder = m["user_config"]["app_folder"]
    assert folder["type"] == "directory" and folder["required"] is True
    # The per-user installer's folder ({autopf} with PrivilegesRequired=lowest); a portable copy is picked by hand.
    assert folder["default"] == "${HOME}\\AppData\\Local\\Programs\\Clipcura"
    assert m["compatibility"]["platforms"] == ["win32"]
    assert m["license"] == "Apache-2.0"


def test_manifest_lists_exactly_the_servers_tools():
    tools = asyncio.run(build_server(connect=lambda: None).list_tools())
    listed = {t["name"]: t["description"] for t in extension.manifest()["tools"]}
    assert set(listed) == {t.name for t in tools}
    assert all(desc and "\n" not in desc for desc in listed.values())


def test_package_holds_manifest_icon_and_entry_point(tmp_path):
    path = extension.write_mcpb(tmp_path / "Clipcura.mcpb")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        m = json.loads(z.read("manifest.json"))
        assert m == extension.manifest()
        assert m["icon"] in names and m["server"]["entry_point"] in names
        for entry in m["icons"]:
            assert entry["src"] in names
            img = Image.open(io.BytesIO(z.read(entry["src"])))
            assert img.format == "PNG" and f"{img.width}x{img.height}" == entry["size"]


def test_server_announces_its_name_version_and_logo():
    async def info():
        async with Client(build_server(connect=lambda: None)) as client:
            return client.server_info

    server = asyncio.run(info())
    assert server.name == "clipcura" and server.title == "Clipcura" and server.version == __version__
    assert server.website_url == extension.HOMEPAGE
    assert server.icons and server.icons[0].src.startswith("data:image/png;base64,")
    assert server.icons[0].mime_type == "image/png"
