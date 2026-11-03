"""New Clipcura versions and missing parts, always with the user's consent (#22).

- New version: GitHub Releases is asked only after the user agreed to automatic checks (at most once a day) or
  pressed Check. The package matching this copy (installer or portable ZIP) is downloaded only on request and
  verified against the release's SHA256SUMS.txt before anything runs it.
- Missing WebView2: Microsoft's bootstrapper, checked for Microsoft's Authenticode signature before it runs.
- Missing FFmpeg: the exact pinned build (clipcura/core/ffmpeg_build.py), never a different version.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from clipcura import __version__
from clipcura.core import events, paths

log = logging.getLogger(__name__)

LATEST_URL = "https://api.github.com/repos/Scoofer4/clipcura/releases/latest"
CHECK_EVERY = timedelta(hours=24)
STATE_FILE = "updates.json"
CHECKSUMS = "SHA256SUMS.txt"
# Microsoft's Evergreen bootstrapper: a small signed program that downloads and installs the runtime per user.
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


class UpdateError(Exception):
    """A request that cannot be carried out; the message is shown to the user."""


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text.strip().lstrip("vV").split("-")[0]))


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def package_name(kind: str, version: str) -> str | None:
    """The release file for this kind of copy. A source checkout updates with git, not with a package."""
    return {"installed": f"Clipcura-Setup-{version}.exe",
            "portable": f"Clipcura-{version}-win64-portable.zip"}.get(kind)


def signed_by_microsoft(signature: str) -> bool:
    """`signature` is Get-AuthenticodeSignature's status on the first line and the signer's subject after it."""
    lines = signature.strip().splitlines()
    return bool(lines) and lines[0].strip() == "Valid" and "O=Microsoft Corporation" in " ".join(lines[1:])


def carry_data(old_data: Path, new_folder: Path) -> None:
    """Copy a portable copy's settings and history into its newer version (the old copy keeps its own)."""
    target = new_folder / "data"
    if old_data.is_dir() and not target.exists():
        try:
            shutil.copytree(old_data, target)
        except shutil.Error:
            # Everything else is copied first; a file still held by the closing window (WebView2 cache) is not
            # worth failing the switch for.
            log.warning("some files were not carried over", exc_info=True)


def _now() -> datetime:
    return datetime.now(UTC)


class Updater:
    """Lives in the service: one check, one download and one repair at a time; progress goes out as events."""

    def __init__(self, http: httpx.Client | None = None, kind: str | None = None, install_dir: Path | None = None,
                 current: str | None = None) -> None:
        self._http = http
        self.kind = kind or paths.install_kind()
        self.install_dir = install_dir if install_dir is not None else paths.install_dir()
        self.current = current or __version__
        self._lock = threading.Lock()
        self._checking = False
        self._check_error: str | None = None
        self.tasks: dict[str, dict] = {name: {"state": "idle", "progress": 0.0, "error": None, "path": None}
                                       for name in ("download", "webview2", "ffmpeg")}

    # --- state --------------------------------------------------------------------------------------------
    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=httpx.Timeout(10, read=60), follow_redirects=True,
                                      headers={"User-Agent": f"Clipcura/{self.current}"})
        return self._http

    def _state_path(self) -> Path:
        return paths.app_data_dir() / STATE_FILE

    def _load(self) -> dict:
        try:
            return json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _newer(self) -> dict | None:
        latest = self._load().get("latest")
        return latest if latest and is_newer(latest["version"], self.current) else None

    def status(self) -> dict:
        from clipcura.core import backends
        from clipcura.desktop import webview2

        latest = self._newer()
        try:
            backends.find_ffmpeg()
            ffmpeg_ok = True
        except FileNotFoundError:
            ffmpeg_ok = False
        return {
            "current": self.current, "kind": self.kind, "last_check": self._load().get("last_check"),
            "checking": self._checking, "error": self._check_error,
            "latest": None if latest is None else {**{k: latest[k] for k in ("version", "url", "notes")},
                                                   "package": package_name(self.kind, latest["version"])},
            "download": dict(self.tasks["download"]),
            "webview2": {"installed": webview2.installed(), **self.tasks["webview2"]},
            "ffmpeg": {"installed": ffmpeg_ok, **self.tasks["ffmpeg"]},
        }

    def _changed(self) -> None:
        events.publish("updates")

    # --- new version --------------------------------------------------------------------------------------
    def check(self) -> dict | None:
        """Ask GitHub for the latest release now (the user pressed Check, or agreed to daily checks)."""
        self._checking = True
        try:
            r = self.http.get(LATEST_URL, headers={"Accept": "application/vnd.github+json"})
            if r.status_code == 404:
                latest = None   # nothing published yet
            else:
                r.raise_for_status()
                data = r.json()
                latest = {"version": data["tag_name"].lstrip("vV"), "url": data["html_url"],
                          "notes": data.get("body") or "",
                          "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}}
            self._save({**self._load(), "last_check": _now().isoformat(timespec="seconds"), "latest": latest})
            self._check_error = None
            return self._newer()
        except (httpx.HTTPError, ValueError, KeyError) as e:
            self._check_error = f"Could not reach GitHub: {e}"
            raise UpdateError(self._check_error) from e
        finally:
            self._checking = False
            self._changed()

    def maybe_check(self, consent: bool | None, wait: bool = False) -> None:
        """The daily check, only with consent. Runs in the background unless `wait`."""
        if not consent or self._checking:
            return
        last = self._load().get("last_check")
        if last and _now() - datetime.fromisoformat(last) < CHECK_EVERY:
            return

        def run() -> None:
            try:
                self.check()
            except UpdateError:
                log.info("update check failed", exc_info=True)

        if wait:
            run()
        else:
            threading.Thread(target=run, name="clipcura-update-check", daemon=True).start()

    def download(self, wait: bool = False) -> Path | None:
        latest = self._newer()
        if latest is None:
            raise UpdateError("No newer version is known. Check for updates first.")
        name = package_name(self.kind, latest["version"])
        if name is None:
            raise UpdateError("This copy runs from source code: update it with git pull.")
        if name not in latest["assets"] or CHECKSUMS not in latest["assets"]:
            raise UpdateError(f"The release does not offer {name} with checksums.")
        folder = paths.app_data_dir() / "updates" / latest["version"]

        def fetch(progress: Callable[[float], None]) -> Path:
            folder.mkdir(parents=True, exist_ok=True)
            sums = self.http.get(latest["assets"][CHECKSUMS])
            sums.raise_for_status()
            from clipcura.core.ffmpeg_build import parse_checksums, verify_sha256
            expected = parse_checksums(sums.text).get(name)
            if not expected:
                raise UpdateError(f"{CHECKSUMS} does not list {name}.")
            target, part = folder / name, folder / f"{name}.part"
            try:
                self._stream(latest["assets"][name], part, progress)
                verify_sha256(part, expected)
                part.replace(target)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            return target

        return self._run("download", fetch, wait)

    def unpack_portable(self) -> Path:
        """Unpack a downloaded portable package next to this copy, e.g. Clipcura-0.2.0 beside Clipcura. The running
        copy is not touched; its data is carried over when the user switches (see DesktopApp.restart_into)."""
        task, latest = self.tasks["download"], self._newer()
        if self.kind != "portable" or task["state"] != "ready" or latest is None or self.install_dir is None:
            raise UpdateError("Download the new portable version first.")
        target = self.install_dir.parent / f"Clipcura-{latest['version']}"
        exe = target / "Clipcura.exe"
        if exe.is_file():
            return exe
        with tempfile.TemporaryDirectory(prefix="clipcura-unpack-", dir=self.install_dir.parent) as tmp:
            with zipfile.ZipFile(task["path"]) as z:
                z.extractall(tmp)   # zipfile strips absolute paths and ".." components
            Path(tmp, "Clipcura").rename(target)
        return exe

    def run_installer(self) -> None:
        """Start the downloaded installer; it closes the running Clipcura itself before replacing files."""
        task = self.tasks["download"]
        if self.kind != "installed" or task["state"] != "ready":
            raise UpdateError("Download the new installer first.")
        _detached([task["path"]])

    # --- missing parts ------------------------------------------------------------------------------------
    def install_webview2(self, wait: bool = False) -> Path | None:
        if sys.platform != "win32":
            raise UpdateError("WebView2 is a Windows component.")

        def install(progress: Callable[[float], None]) -> Path:
            folder = paths.app_data_dir() / "updates"
            folder.mkdir(parents=True, exist_ok=True)
            exe = folder / "MicrosoftEdgeWebview2Setup.exe"
            self._stream(WEBVIEW2_URL, exe, lambda p: progress(p * 0.2))
            if not signed_by_microsoft(_authenticode(exe)):
                exe.unlink(missing_ok=True)
                raise UpdateError("The downloaded WebView2 installer is not signed by Microsoft; it was deleted.")
            progress(0.25)
            # Run as the current user: the runtime installs per user, no administrator rights needed.
            result = subprocess.run([str(exe), "/silent", "/install"], timeout=900, check=False)
            from clipcura.desktop import webview2
            if not webview2.installed():
                raise UpdateError(f"WebView2 did not install (exit code {result.returncode}).")
            return exe

        return self._run("webview2", install, wait)

    def restore_ffmpeg(self, wait: bool = False) -> Path | None:
        from clipcura.core import ffmpeg_build

        def restore(progress: Callable[[float], None]) -> Path:
            target = paths.vendored_ffmpeg_dir()
            if target.exists():
                # Keep what is left (for a closer look), the fresh copy goes to the expected place.
                target.rename(target.with_name(f"ffmpeg.damaged-{_now():%Y%m%d-%H%M%S}"))
            return ffmpeg_build.install(target, lambda done, total: progress(done / total if total else 0))

        return self._run("ffmpeg", restore, wait)

    # --- plumbing -----------------------------------------------------------------------------------------
    def _stream(self, url: str, dest: Path, progress: Callable[[float], None]) -> None:
        with self.http.stream("GET", url) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            with dest.open("wb") as out:
                for chunk in r.iter_bytes(1 << 20):
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        progress(done / total)

    def _run(self, name: str, work: Callable[[Callable[[float], None]], Path], wait: bool) -> Path | None:
        task = self.tasks[name]
        with self._lock:
            if task["state"] == "running":
                raise UpdateError("Already in progress.")
            task.update(state="running", progress=0.0, error=None, path=None)
        self._changed()
        last = [0.0]

        def progress(p: float) -> None:
            task["progress"] = round(p, 3)
            if p - last[0] >= 0.02:   # about fifty updates, not one per chunk
                last[0] = p
                self._changed()

        def run() -> Path:
            try:
                path = work(progress)
            except Exception as e:
                task.update(state="failed", error=str(e))
                self._changed()
                raise
            task.update(state="ready", progress=1.0, path=str(path))
            self._changed()
            return path

        if wait:
            return run()

        def background() -> None:
            try:
                run()
            except Exception:
                log.warning("%s failed", name, exc_info=True)

        threading.Thread(target=background, name=f"clipcura-{name}", daemon=True).start()
        return None


def _authenticode(path: Path) -> str:
    # The path travels in an environment variable, never inside the PowerShell command text.
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:CLIPCURA_FILE; $s.Status.ToString(); "
              "if ($s.SignerCertificate) { $s.SignerCertificate.Subject }")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                         text=True, timeout=60, env=os.environ | {"CLIPCURA_FILE": str(path)}, check=False)
    return out.stdout


def _detached(cmd: list[str]) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
