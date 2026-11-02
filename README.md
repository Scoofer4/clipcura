# Clipsana

**Every clip edit-ready.** Clipsana checks footage from phones, action/360° cameras and DSLRs and automatically
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
| M0 | Environment, `clipsana doctor` | ⏳ |
| M1 | Core, rules, CLI, tests | ⏳ |
| M2 | Local API, worker, events | ⏳ |
| M3 | Design system and GUI | ⏳ |
| M4 | MCP server and approvals | ⏳ |
| M5 | Windows installer | ⏳ |

## Development (Windows)

```powershell
uv sync --group dev          # Python environment
uv run clipsana doctor       # hardware and FFmpeg capabilities (from M0)
uv run pytest                # tests
```

FFmpeg lives in `vendor/ffmpeg/` (not committed). Real sample footage goes to `tests/fixtures/real/` (not committed).

## Project layout

```
clipsana/    core, rules (check plugins), api (local API), mcp (MCP server)
profiles/    target parameters (YAML)
ui/          React GUI (from M3)
tests/       tests, generated and real samples
tools/       original prototype script
packaging/   PyInstaller and installer
docs/        screenshots, benchmarks, notes
```

## License

Apache-2.0 – see [LICENSE](LICENSE) and [NOTICE](NOTICE). FFmpeg is a separate program under its own license.
"DaVinci Resolve" is a trademark of Blackmagic Design; Clipsana is not affiliated with Blackmagic Design.

---
Interní zadání projektu (česky): [`CLAUDE.md`](CLAUDE.md).
