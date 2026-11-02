"""`clipsana doctor`: one report of hardware and ffmpeg capabilities, saved for the app to reuse."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from clipsana import __version__
from clipsana.core import backends, sysinfo
from clipsana.core.models import DoctorReport
from clipsana.core.paths import app_data_dir

REPORT_NAME = "doctor.json"
LOW_DISK_GB = 20  # DNxHR HQ needs roughly 0.5-1 GB per minute of 4K, so less than this fills up fast


def run_doctor(disk_paths: list[Path] | None = None, run_probes: bool = True) -> DoctorReport:
    paths = disk_paths or [Path.cwd()]
    system = sysinfo.collect(paths)
    problems: list[str] = []
    ffmpeg = None
    try:
        ffmpeg = backends.inspect_ffmpeg(run_probes=run_probes)
    except FileNotFoundError as e:
        problems.append(str(e))

    if ffmpeg and run_probes:
        for name in ("libx264", "dnxhd"):
            if name in ffmpeg.encoders and not ffmpeg.works(name):
                problems.append(f"CPU encoder {name} failed - ffmpeg build looks broken")
        if not (ffmpeg.works("libplacebo") or ffmpeg.works("zscale")):
            problems.append("No working HDR tone-mapping filter (libplacebo or zscale)")
    problems += [f"Low free space on {d.path}: {d.free_gb} GB" for d in system.disks if d.free_gb < LOW_DISK_GB]

    return DoctorReport(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        clipsana_version=__version__,
        backend=backends.choose_backend(ffmpeg) if ffmpeg and run_probes else "cpu",
        system=system,
        ffmpeg=ffmpeg,
        problems=problems,
    )


def save_report(report: DoctorReport) -> Path:
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REPORT_NAME
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
