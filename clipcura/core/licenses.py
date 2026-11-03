"""What Clipcura is built from, with licences: the About screen and THIRD-PARTY-NOTICES.txt in the installer.

From a source checkout the list comes from the installed package metadata (walking clipcura's runtime
requirements). The frozen app carries no package metadata, so the build writes the same data next to it
(licenses.json, THIRD-PARTY-NOTICES.txt) and those files win when present.
"""
from __future__ import annotations

import json
import re
from importlib import metadata
from pathlib import Path

from clipcura.core.paths import REPO_ROOT, vendored_ffmpeg_dir

COMPONENTS_FILE = "licenses.json"
NOTICES_FILE = "THIRD-PARTY-NOTICES.txt"
# Licence texts, not source modules that happen to be called license.py.
_LICENCE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)(?!.*\.pyc?$)", re.IGNORECASE)
_CLASSIFIER = "License :: OSI Approved :: "


def _licence(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c.removeprefix(_CLASSIFIER) for c in meta.get_all("Classifier") or [] if c.startswith(_CLASSIFIER)]
    if classifiers:
        return " / ".join(classifiers)
    text = (meta.get("License") or "").strip()
    # Some packages paste the whole licence text here; the first line names it well enough.
    return text.splitlines()[0][:60] if text else "see licence file"


def _homepage(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    if meta.get("Home-page"):
        return meta["Home-page"]
    for url in meta.get_all("Project-URL") or []:
        label, _, link = url.partition(",")
        if label.strip().lower() in ("homepage", "home", "source", "repository", "documentation"):
            return link.strip()
    return ""


def _requirements(dist: metadata.Distribution, extras: set[str]) -> list[tuple[str, set[str]]]:
    try:
        from packaging.requirements import Requirement
    except ImportError:  # without packaging, follow every requirement by name (may list a few extra packages)
        return [(re.split(r"[\s;<>=!\[~]", r, maxsplit=1)[0], set()) for r in dist.requires or []]
    found = []
    for raw in dist.requires or []:
        req = Requirement(raw)
        envs = [{"extra": e} for e in extras] or [{"extra": ""}]
        if req.marker is None or any(req.marker.evaluate(env) for env in envs):
            found.append((req.name, set(req.extras)))
    return found


def _python_components() -> list[dict]:
    seen: dict[str, dict] = {}
    queue = _requirements(metadata.distribution("clipcura"), set())
    while queue:
        name, extras = queue.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # a platform-specific requirement not installed here
        seen[key] = {"name": dist.metadata["Name"], "version": dist.version, "licence": _licence(dist),
                     "url": _homepage(dist), "kind": "python"}
        queue += _requirements(dist, extras)
    return sorted(seen.values(), key=lambda c: c["name"].lower())


def ffmpeg_component() -> dict | None:
    build_file = vendored_ffmpeg_dir() / "BUILD.json"
    if not build_file.is_file():
        return None
    build = json.loads(build_file.read_text(encoding="utf-8"))
    version = re.search(r"n(\d+\.\d+(?:\.\d+)?)", build.get("asset", ""))
    return {"name": "FFmpeg", "version": version.group(1) if version else "", "licence": "GPL-3.0-or-later",
            "url": "https://ffmpeg.org", "kind": "media", "source": build.get("ffmpeg_source", ""),
            "build": build.get("release", ""),
            "note": "Runs as a separate program; Clipcura calls ffmpeg and ffprobe as processes."}


def components() -> list[dict]:
    """FFmpeg first (it does the actual work), then the Python packages the service ships with."""
    bundled = REPO_ROOT / COMPONENTS_FILE
    if bundled.is_file():
        return json.loads(bundled.read_text(encoding="utf-8"))
    ffmpeg = ffmpeg_component()
    return ([ffmpeg] if ffmpeg else []) + _python_components()


def notices_text() -> str:
    """Every component with its licence text: MIT, BSD and Apache require the text to travel with the program."""
    bundled = REPO_ROOT / NOTICES_FILE
    if bundled.is_file():
        return bundled.read_text(encoding="utf-8")
    parts = ["Clipcura bundles the following third-party software.\n"]
    for c in components():
        parts.append(f"\n==== {c['name']} {c['version']} ====\nLicence: {c['licence']}\n")
        if c["kind"] == "media":
            parts.append(f"{c['note']}\nThe full licence text is in vendor\\ffmpeg\\LICENSE.txt.\n"
                         f"Corresponding source code: {c['source']}\nBinary release: {c['build']}\n")
            continue
        dist = metadata.distribution(c["name"])
        for f in dist.files or []:
            path = Path(str(dist.locate_file(f)))
            if _LICENCE_FILE.search(f.name) and path.is_file():
                parts.append(f"\n--- {f.name} ---\n{path.read_text(encoding='utf-8', errors='replace')}\n")
    return "".join(parts)
