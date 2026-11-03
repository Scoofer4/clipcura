"""`clipcura doctor`: one report of hardware and ffmpeg capabilities, saved for the app to reuse."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from clipcura import __version__
from clipcura.core import backends, sysinfo
from clipcura.core.models import DoctorReport
from clipcura.core.paths import app_data_dir

REPORT_NAME = "doctor.json"
LOW_DISK_GB = 20  # DNxHR HQ needs roughly 0.5-1 GB per minute of 4K, so less than this fills up fast


def run_doctor(disk_paths: list[Path] | None = None, run_probes: bool = True) -> DoctorReport:
    paths = disk_paths or [Path.cwd()]
    system = sysinfo.collect(paths)
    problems: list[str] = []
    ffmpeg = None
    try:
        ffmpeg = backends.inspect_ffmpeg(run_probes=run_probes, run_benchmarks_too=run_probes)
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
        clipcura_version=__version__,
        backend=backends.choose_backend(ffmpeg) if ffmpeg and run_probes else "cpu",
        paths=backends.choose_paths(ffmpeg if run_probes else None),
        system=system,
        ffmpeg=ffmpeg,
        problems=problems,
    )


def load_report() -> DoctorReport | None:
    path = app_data_dir() / REPORT_NAME
    if not path.is_file():
        return None
    try:
        return DoctorReport.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:  # written by an older version: measure again rather than trust partial data
        return None


def save_report(report: DoctorReport) -> Path:
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REPORT_NAME
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
