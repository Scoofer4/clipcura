"""MCP server (M4): the assistant works through the same API as the GUI, as actor "ai", and cannot approve."""
import asyncio
import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from clipcura.api.app import create_app
from clipcura.core import config
from clipcura.mcp.server import build_server
from tests.conftest import needs_ffmpeg

BASE = "http://127.0.0.1"
TOOLS = {"system_info", "list_profiles", "list_rules", "scan_folder", "get_report", "plan_fixes", "apply_fixes",
         "job_status", "cancel_job", "get_logs"}


@pytest.fixture
def mcp(tmp_path):
    """MCP server wired to an in-process API; `human` is the same API seen from the GUI."""
    cfg = config.load_config()
    config.allow_root(tmp_path)
    with TestClient(create_app(), base_url=BASE) as human:
        human.headers["Authorization"] = f"Bearer {cfg.token}"
        ai = TestClient(human.app, base_url=BASE)
        ai.headers.update({"Authorization": f"Bearer {cfg.token}", "X-Clipcura-Actor": "ai"})
        server = build_server(connect=lambda: ai)
        yield server, human


def call(server, name: str, **args) -> dict:
    result = asyncio.run(server.call_tool(name, args))
    return result.structured_content


def test_tools_match_the_gui_actions_and_none_approves(mcp):
    server, _ = mcp
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(tools) == TOOLS
    assert not any("approve" in name for name in tools)
    for name in ("system_info", "list_profiles", "list_rules", "get_report", "job_status", "get_logs"):
        assert tools[name].annotations.read_only_hint is True
    assert tools["apply_fixes"].annotations.read_only_hint is False
    assert tools["apply_fixes"].annotations.destructive_hint is False  # writes only new files to the output folder


def test_profiles_and_rules_come_back_structured(mcp):
    server, _ = mcp
    assert "social-30" in {p["name"] for p in call(server, "list_profiles")["profiles"]}
    rules = call(server, "list_rules")
    assert "vfr" in {r["id"] for r in rules["rules"]} and rules["summary"]


def test_folder_outside_the_whitelist_asks_for_the_user(mcp, tmp_path_factory):
    server, _ = mcp
    outside = tmp_path_factory.mktemp("outside")
    with pytest.raises(ToolError, match="allow the folder"):
        asyncio.run(server.call_tool("scan_folder", {"path": str(outside)}))


@needs_ffmpeg
def test_scan_plan_apply_waits_for_human_approval(mcp, raw_folder):
    server, human = mcp
    raw = raw_folder("a44k.mp4", "ok.mp4")
    scan = call(server, "scan_folder", path=str(raw), lang="cs")
    assert scan["counts"]["fixable"] == 1 and "opravitelných" in scan["summary"]

    report = call(server, "get_report", scan_id=scan["scan_id"], status="fixable")
    (clip,) = report["files"]
    assert clip["name"] == "a44k.mp4" and clip["audio_rate"] == 44100
    # social-30 also reports loudness (info only); the fix that matters here is the sample rate
    assert [f["rule"] for f in clip["findings"] if f["severity"] != "info"] == ["audio_rate"]

    plan = call(server, "plan_fixes", scan_id=scan["scan_id"])
    (item,) = [i for i in plan["items"] if i["status"] == "pending"]
    assert item["ffmpeg"][0] == "ffmpeg" and plan["est_bytes"] > 0

    applied = call(server, "apply_fixes", plan_id=plan["plan_id"])
    (job,) = applied["jobs"]
    assert job["status"] == "awaiting_approval" and "approval" in applied["summary"]

    # The GUI sees the request; only the human can let it run.
    assert human.post(f"/api/jobs/{job['job_id']}/approve").json()["status"] == "queued"
    deadline = time.monotonic() + 120
    while (status := call(server, "job_status", job_ids=[job["job_id"]]))["jobs"][0]["status"] != "done":
        assert status["jobs"][0]["status"] in ("queued", "running") and time.monotonic() < deadline
        time.sleep(0.3)
    assert os.path.exists(status["jobs"][0]["output"])
    actors = {e["actor"] for e in human.get("/api/audit").json()}
    assert {"ai", "human"} <= actors


@needs_ffmpeg
def test_cancel_withdraws_a_waiting_request(mcp, raw_folder):
    server, _ = mcp
    scan = call(server, "scan_folder", path=str(raw_folder("a44k.mp4")))
    plan = call(server, "plan_fixes", scan_id=scan["scan_id"])
    (job,) = call(server, "apply_fixes", plan_id=plan["plan_id"])["jobs"]
    call(server, "cancel_job", job_id=job["job_id"])
    assert call(server, "job_status", job_ids=[job["job_id"]])["jobs"][0]["status"] == "cancelled"


def test_stdio_server_starts_the_service_on_demand(tmp_path):
    """What Claude Code actually runs: `clipcura mcp` over stdio, with no Clipcura window open."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    home = tmp_path / "stdio-home"
    env = os.environ | {"CLIPCURA_HOME": str(home)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "clipcura.cli", "mcp"], env=env)

    async def session() -> tuple[set[str], dict]:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            rules = await s.call_tool("list_rules", {})
            return names, rules.structured_content

    try:
        names, rules = asyncio.run(session())
        assert names == TOOLS
        assert "vfr" in {r["id"] for r in rules["rules"]}
    finally:
        # The headless service outlives the MCP process by design; stop the one this test started.
        announce = home / "server.json"
        if announce.exists():
            pid = json.loads(announce.read_text(encoding="utf-8"))["pid"]
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


def test_assistant_reads_the_same_log_as_the_person(mcp):
    # #26: when something fails, an assistant can see where, like the person on the Log screen.
    import logging

    from clipcura.core import logs

    server, _ = mcp
    logs.setup("service")
    logging.getLogger("clipcura.jobs").error("Job j9 failed (x.mp4): Invalid data found")
    result = call(server, "get_logs", level="error")
    assert "Invalid data found" in result["entries"][0]["message"] and "1 error" in result["summary"]
