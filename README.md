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
| M5 | Desktop app, notification-area icon, Windows installer | ✅ built and tested on one machine; clean-Windows install pending |

## Download

Every [release](https://github.com/Scoofer4/clipcura/releases) has two packages with the same app, FFmpeg included:

- **Installer** `Clipcura-Setup-<version>.exe`: per-user install without administrator rights, Start menu entry,
  uninstaller. Settings and history go to `%APPDATA%\Clipcura`.
- **Portable** `Clipcura-<version>-win64-portable.zip`: no installation. Unzip anywhere (also a USB drive) and run
  `Clipcura\Clipcura.exe`. Settings and history stay in the `data` folder next to it; delete `portable.txt` to keep
  them in your user profile instead.

`SHA256SUMS.txt` lists the checksums. The packages are not code-signed yet, so SmartScreen may ask on first start.
The window uses Microsoft Edge WebView2 Runtime, a part of Windows 11 and current Windows 10; your default browser
does not matter.

## Development (Windows)

```powershell
uv sync --group dev                     # Python environment
uv run python tools/fetch_ffmpeg.py     # pinned, SHA-256 verified FFmpeg 8.1 build into vendor/ffmpeg
uv run clipcura doctor                  # hardware and FFmpeg capabilities (add --json for machines)
uv run pytest                           # tests (integration tests need vendor/ffmpeg)
```

FFmpeg lives in `vendor/ffmpeg/` (not committed). Real sample footage goes to `tests/fixtures/real/` (not committed),
or point `CLIPCURA_REAL_DIR` at a folder to run the real-footage checks.

## Desktop app

```powershell
uv run clipcura app      # the GUI in its own window; the icon in the notification area shows batch progress
```

Closing the window keeps Clipcura in the notification area, so conversions continue; quit from the icon's menu.

`Clipcura.exe --browser` (or `clipcura app --browser`, or Settings → Appearance) shows the same GUI in your default
browser instead of the window; Clipcura does this by itself when WebView2 is missing. The browser gets a one-time
code (valid two minutes, once), never the access key, so its history holds nothing reusable.

## Updates

Clipcura asks on first start whether it may check GitHub for new versions once a day. Nothing is downloaded until
you press a button: Settings → Updates downloads the package matching your copy, verifies it against the release's
`SHA256SUMS.txt`, then runs the installer or unpacks the portable copy next to the current one and switches to it
with your settings. The same place restores a missing FFmpeg (the exact pinned build) and installs a missing
WebView2 (Microsoft's signed bootstrapper). From the command line: `clipcura update` (`--install`, `--ffmpeg`,
`--webview2`, `--auto/--no-auto`).
Every screen has help (the Help button or F1), and **About** lists the owner, the licence and every component
Clipcura is built from with its licence.

## Building the packages

```powershell
uv run python tools/build_installer.py                  # needs Node.js and Inno Setup 6 (ISCC on PATH, or set ISCC)
uv run python tools/build_installer.py --no-installer   # portable ZIP only
```

The results in `packaging\dist\` are the installer, the portable ZIP and `SHA256SUMS.txt`. Both packages carry
FFmpeg, its licence and the licence texts of every bundled component. Pushing a version tag (`v0.2.0`, matching
`clipcura.__version__` and `pyproject.toml`) builds them on GitHub Actions and attaches them to a draft release.

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

## Log

Every part of Clipcura (the app, the background service, the MCP server, CLI commands) logs what it does from start
to shutdown, including unhandled errors, to `logs\` in the app data folder (one file per part, rotated at 5 MB).
The **Log** screen shows it live with level filters and search, `clipcura logs` prints it, and assistants read the
same entries with the MCP tool `get_logs`. The access key and one-time codes are masked, so entries can be shared.

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
`job_status`, `cancel_job`, `get_logs`. There is no approve tool. While the approval mode is on (default), every
conversion an assistant requests waits in **AI activity** until a person approves it. Only folders allowed by a
person (`clipcura config allow` or Settings) can be used.

Register it in Claude Code, for example:

```powershell
claude mcp add clipcura -s user -- uv run --project D:\path\to\clipcura clipcura mcp      # source checkout
claude mcp add clipcura -s user -- "%LOCALAPPDATA%\Programs\Clipcura\clipcura-cli.exe" mcp   # installed app
```

## Built-in assistant (Ollama)

Clipcura can also run the assistant itself, on a model from your own Ollama server, with nothing else installed.
Give it tasks in plain words on the **Assistant** screen, or press **Explain** next to a failed job or a log error.
It uses the same tools as an MCP assistant, as actor `ai`, so the same limits apply. Turn it on in
**Settings → Assistant (Ollama)**: the server address, an optional access key and a model that can call tools.
The access key is never sent back to the GUI and never written to the log. Clipcura sends file names, paths and
measured values to that server, never the videos. See [docs/assistant-ollama.md](docs/assistant-ollama.md),
including how to protect Ollama with an access key.

## Project layout

```
clipcura/    core, rules (check plugins), api (local API), mcp (MCP server), assistant (Ollama), desktop (window, tray)
profiles/    target parameters (YAML)
ui/          React GUI (from M3)
tests/       tests, generated and real samples
tools/       FFmpeg fetch, benchmark, installer build, original prototype script
packaging/   PyInstaller and installer
docs/        screenshots, benchmarks, notes
```

## License

Apache-2.0 – see [LICENSE](LICENSE) and [NOTICE](NOTICE). FFmpeg is a separate program under its own license.
"DaVinci Resolve" is a trademark of Blackmagic Design; Clipcura is not affiliated with Blackmagic Design.

---
Interní zadání projektu (česky): [`CLAUDE.md`](CLAUDE.md).
