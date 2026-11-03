"""MCP server (stdio) so AI assistants can use Clipcura (CLAUDE.md §8).

A thin client of the local API, calling it as actor "ai": the assistant gets exactly the actions a person has
in the GUI, nothing more. There is deliberately no approve tool; with the approval mode on (default), every
conversion an assistant requests waits for a human in the Clipcura window.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import PurePath
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

Lang = Literal["en", "cs"]

INSTRUCTIONS = """Clipcura checks video footage before editing in DaVinci Resolve and converts the clips that
would cause trouble (variable frame rate, HDR, 10-bit HEVC, odd sizes, wrong audio rate, rotation).
Typical flow: scan_folder -> get_report -> plan_fixes -> apply_fixes -> job_status.
Originals are never modified; results go to the profile's output folder (by default ../02_edit).
Conversions you request usually wait for the user's approval in the Clipcura window: tell the user so.
Only folders the user allowed can be used; if a folder is refused, ask the user to allow it in Clipcura's
settings. Pass lang="cs" for Czech summaries."""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def _connect() -> httpx.Client:
    """Client for the running service, starting a headless one if needed."""
    from clipcura.api.server import running_server, start_background
    from clipcura.core.config import load_config
    info = running_server() or start_background()
    return httpx.Client(base_url=info["url"], timeout=600,
                        headers={"Authorization": f"Bearer {load_config().token}", "X-Clipcura-Actor": "ai"})


def _name(path: str) -> str:
    return PurePath(path).name


def _say(lang: Lang, en: str, cs: str) -> str:
    return cs if lang == "cs" else en


def _size(n: int) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{max(1, round(n / 2**20))} MB"


def build_server(connect: Callable[[], httpx.Client] = _connect) -> MCPServer:
    mcp = MCPServer(name="clipcura", title="Clipcura", instructions=INSTRUCTIONS)
    holder: dict[str, httpx.Client] = {}

    def call(method: str, path: str, **kwargs: Any) -> Any:
        if "client" not in holder:
            holder["client"] = connect()
        r = holder["client"].request(method, path, **kwargs)
        if r.status_code == 403:
            raise ToolError(f"{r.json().get('detail', 'Forbidden')}. Ask the user to allow the folder in "
                            "Clipcura's settings; an assistant cannot change the allowed folders.")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise ToolError(f"Clipcura API {r.status_code}: {detail}")
        return r.json()

    @mcp.tool(annotations=READ)
    def system_info(lang: Lang = "en") -> dict[str, Any]:
        """Hardware, acceleration backend, chosen processing paths and free disk space."""
        s = call("GET", "/api/system")
        gpus = [g["name"] for g in s["system"]["gpus"]]
        disks = [{"path": d["path"], "free_gb": d["free_gb"]} for d in s["system"]["disks"]]
        summary = _say(lang, f"Backend {s['backend']}, GPU {', '.join(gpus) or 'none'}, decode {s['paths']['decode']}.",
                       f"Backend {s['backend']}, GPU {', '.join(gpus) or 'žádná'}, dekódování {s['paths']['decode']}.")
        return {"summary": summary, "backend": s["backend"], "paths": s["paths"], "gpus": gpus, "disks": disks,
                "ffmpeg": (s.get("ffmpeg") or {}).get("version")}

    @mcp.tool(annotations=READ)
    def list_profiles() -> dict[str, Any]:
        """Target profiles (frame rate, size limit, output codec and folder)."""
        profiles = call("GET", "/api/profiles")
        return {"summary": ", ".join(p["name"] for p in profiles), "profiles": [
            {"name": p["name"], "label": p["label"], "fps": p["fps"], "max_long_side": p["max_long_side"],
             "codec": p["output"]["codec"], "output_folder": p["output"]["folder"]} for p in profiles]}

    @mcp.tool(annotations=READ)
    def list_rules() -> dict[str, Any]:
        """The checks Clipcura runs on every clip."""
        rules = call("GET", "/api/rules")
        return {"summary": ", ".join(r["id"] for r in rules), "rules": rules}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                          open_world_hint=False))
    def scan_folder(path: str, profile: str = "social-30", recursive: bool = False, deep: bool = False,
                    lang: Lang = "en") -> dict[str, Any]:
        """Check every clip in a folder. Writes only to Clipcura's database. Returns scan_id and a summary."""
        s = call("POST", "/api/scans", json={"path": path, "profile": profile, "recursive": recursive, "deep": deep})
        n = s["summary"]
        summary = _say(
            lang,
            f"{len(s['files'])} clips: {n.get('fixable', 0)} fixable, {n.get('ok', 0)} ready, "
            f"{n.get('needs_human', 0)} need the user, {n.get('error', 0)} damaged.",
            f"{len(s['files'])} klipů: {n.get('fixable', 0)} opravitelných, {n.get('ok', 0)} v pořádku, "
            f"{n.get('needs_human', 0)} potřebuje uživatele, {n.get('error', 0)} poškozených.")
        return {"summary": summary, "scan_id": s["scan_id"], "root": s["root"], "profile": s["profile"], "counts": n,
                "files": [{"file_id": f["id"], "name": _name(f["path"]), "status": f["status"],
                           "findings": [i["rule_id"] for i in f["issues"]]} for f in s["files"]]}

    @mcp.tool(annotations=READ)
    def get_report(scan_id: str, status: Literal["ok", "fixable", "needs_human", "error"] | None = None,
                   lang: Lang = "en") -> dict[str, Any]:
        """Findings with plain-language messages and measured values, optionally filtered by status."""
        s = call("GET", f"/api/scans/{scan_id}")
        files = [f for f in s["files"] if status is None or f["status"] == status]
        out = []
        for f in files:
            v = f["media"].get("video") or {}
            a = f["media"].get("audio") or {}
            out.append({
                "file_id": f["id"], "name": _name(f["path"]), "path": f["path"], "status": f["status"],
                "video": {k: v.get(k) for k in ("codec", "pix_fmt", "width", "height", "r_fps", "avg_fps",
                                                "color_transfer", "rotation", "bit_depth")} if v else None,
                "audio_rate": a.get("sample_rate"), "duration_s": f["media"].get("duration"),
                "findings": [{"rule": i["rule_id"], "severity": i["severity"], "message": i["message"],
                              "auto_fixable": i["auto_fixable"]} for i in f["issues"]],
            })
        summary = _say(lang, f"{len(out)} clips in the report.", f"{len(out)} klipů v přehledu.")
        return {"summary": summary, "scan_id": scan_id, "files": out}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                                          open_world_hint=False))
    def plan_fixes(scan_id: str, file_ids: list[int] | None = None, lang: Lang = "en") -> dict[str, Any]:
        """Prepare the conversions (no file is written). Returns plan_id, size estimate and the ffmpeg commands."""
        p = call("POST", "/api/plans", json={"scan_id": scan_id, "file_ids": file_ids})
        items = []
        for e in p["items"]:
            it = e.get("item") or {}
            items.append({"file_id": e["file_id"], "status": e["status"], "reason": e.get("reason", ""),
                          "source": it.get("source"), "output": it.get("output"), "rules": it.get("rule_ids", []),
                          "est_bytes": it.get("est_bytes"),
                          "ffmpeg": ["ffmpeg", *it["args"]] if it.get("args") else None})
        pending = sum(1 for i in items if i["status"] == "pending")
        size = _size(p["est_bytes"])
        summary = _say(lang, f"{pending} conversions planned, about {size} to write.",
                       f"Naplánováno {pending} převodů, zapíše se asi {size}.")
        return {"summary": summary, "plan_id": p["plan_id"], "paths": p["paths"], "est_bytes": p["est_bytes"],
                "items": items}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                          open_world_hint=False))
    def apply_fixes(plan_id: str, lang: Lang = "en") -> dict[str, Any]:
        """Request the planned conversions. Writes only to the output folder; originals are never touched.
        With the approval mode on, the jobs wait for the user's approval in the Clipcura window."""
        jobs = call("POST", f"/api/plans/{plan_id}/apply")["jobs"]
        waiting = sum(1 for j in jobs if j["status"] == "awaiting_approval")
        summary = (_say(lang, f"{waiting} conversions wait for the user's approval in Clipcura (AI activity).",
                        f"{waiting} převodů čeká na schválení uživatelem v Clipcuře (Aktivita AI).") if waiting
                   else _say(lang, f"{len(jobs)} conversions queued.", f"{len(jobs)} převodů ve frontě."))
        return {"summary": summary, "jobs": [{"job_id": j["id"], "status": j["status"], "output": j["output"]}
                                              for j in jobs]}

    @mcp.tool(annotations=READ)
    def job_status(job_ids: list[str], lang: Lang = "en") -> dict[str, Any]:
        """Progress, errors and outputs of jobs."""
        jobs = call("GET", "/api/jobs", params={"ids": ",".join(job_ids)})
        counts: dict[str, int] = {}
        for j in jobs:
            counts[j["status"]] = counts.get(j["status"], 0) + 1
        summary = ", ".join(f"{v} {k}" for k, v in counts.items()) or _say(lang, "no such jobs", "žádné takové úlohy")
        return {"summary": summary, "jobs": [{"job_id": j["id"], "status": j["status"], "progress": j["progress"],
                                               "output": j["output"], "error": j["error"]} for j in jobs]}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                          open_world_hint=False))
    def cancel_job(job_id: str, lang: Lang = "en") -> dict[str, Any]:
        """Stop a running job (its partial output is removed) or withdraw a waiting one."""
        call("POST", f"/api/jobs/{job_id}/cancel")
        return {"summary": _say(lang, "Cancel requested.", "Zrušení vyžádáno."), "job_id": job_id}

    return mcp


def main() -> None:
    # stderr of an MCP server ends up in the client's log; one line per API call is noise there.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    build_server().run("stdio")
