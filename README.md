# Clipcura

**Every clip edit-ready.** Clipcura checks footage from phones, action/360° cameras and DSLRs and automatically
fixes what makes editors like DaVinci Resolve crash or stutter: variable frame rate (VFR), mixed frame rates
and resolutions, HDR, 10-bit HEVC and non-48 kHz audio.

- **For humans:** a modern desktop app – drop a folder, see what's wrong, fix it in one click.
- **For AI:** a built-in MCP server, so assistants like Claude can scan, plan and fix footage using exactly the
  same actions as the GUI (with optional human approval).
- **Fast and local:** runs on your PC, uses FFmpeg with GPU acceleration (NVIDIA NVENC/NVDEC, Intel QSV) and
  falls back to CPU. Originals are never modified.

> Status: early development (Windows first). Made by [Metaverse Media](https://metaversemedia.cz).

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Environment, `clipcura doctor` | ✅ |
| M1 | Core, rules, CLI, tests | ✅ |
| M2 | Local API, worker, events | ✅ |
| M3 | Design system and GUI | ✅ |
| M4 | MCP server and approvals | ✅ |
| M5 | Windows installer | ⏳ |

## Development (Windows)

```powershell
uv sync --group dev                     # Python environment
uv run python tools/fetch_ffmpeg.py     # pinned, SHA-256 verified FFmpeg 8.1 build into vendor/ffmpeg
uv run clipcura doctor                  # hardware and FFmpeg capabilities (add --json for machines)
uv run pytest                           # tests (integration tests need vendor/ffmpeg)
```

FFmpeg lives in `vendor/ffmpeg/` (not committed). Real sample footage goes to `tests/fixtures/real/` (not committed),
or point `CLIPCURA_REAL_DIR` at a folder to run the real-footage checks.

## Usage (CLI)

```powershell
uv run clipcura fix D:\Footage\01_raw              # scan, plan and convert what needs it into ..\02_edit
uv run clipcura fix D:\Footage\01_raw --dry-run    # show findings and the exact ffmpeg commands only
uv run clipcura scan D:\Footage\01_raw --deep      # findings only (+ frame-timestamp VFR check)
uv run clipcura plan <scan-id>                     # step by step: scan -> plan -> apply
uv run clipcura apply <plan-id>
```

Originals are never modified. Files that are already fine are left alone, and a rerun skips finished files.
Every check is a plugin in `clipcura/rules/` (one file per rule).

`clipcura doctor` also measures which decoder and scaler are fastest on your machine (whole-job timing), and
`plan` uses the result. Tone-mapping picks the higher-quality path whenever it works.

## Local API

```powershell
uv run clipcura config allow D:\Footage   # the API and MCP only touch allowed folders
uv run clipcura serve                     # API + job worker on 127.0.0.1 (port written to server.json)
```

All routes except `/api/health` need `Authorization: Bearer <token>` (token in `config.json` in the app data
folder). Progress and events stream over the WebSocket `/api/events?token=...`. Requests sent with
`X-Clipcura-Actor: ai` or `n8n` wait for human approval while the approval mode is on (default).

## AI assistants (MCP)

`clipcura mcp` is an MCP server on stdio. It starts the background service when no Clipcura window is open and
calls the local API as actor `ai`, so an assistant has the same actions as the GUI and nothing more:
`system_info`, `list_profiles`, `list_rules`, `scan_folder`, `get_report`, `plan_fixes`, `apply_fixes`,
`job_status`, `cancel_job`. There is no approve tool. While the approval mode is on (default), every
conversion an assistant requests waits in **AI activity** until a person approves it. Only folders allowed by a
person (`clipcura config allow` or Settings) can be used.

Register it in Claude Code, for example:

```powershell
claude mcp add clipcura -- uv run --project D:\path\to\clipcura clipcura mcp
```

## Project layout

```
clipcura/    core, rules (check plugins), api (local API), mcp (MCP server)
profiles/    target parameters (YAML)
ui/          React GUI (from M3)
tests/       tests, generated and real samples
tools/       original prototype script
packaging/   PyInstaller and installer
docs/        screenshots, benchmarks, notes
```

## License

Apache-2.0 – see [LICENSE](LICENSE) and [NOTICE](NOTICE). FFmpeg is a separate program under its own license.
"DaVinci Resolve" is a trademark of Blackmagic Design; Clipcura is not affiliated with Blackmagic Design.

---
Interní zadání projektu (česky): [`CLAUDE.md`](CLAUDE.md).
