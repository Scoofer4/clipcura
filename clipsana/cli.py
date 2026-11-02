"""Clipsana command line. Commands grow with milestones (doctor in M0, scan/plan/apply in M1)."""
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from clipsana.core.models import DoctorReport

app = typer.Typer(help="Clipsana - check and fix footage before editing.", no_args_is_help=True)

_STATUS_STYLE = {"ok": "green", "fixable": "yellow", "needs_human": "dark_orange", "error": "red",
                 "pending": "cyan", "done": "green", "exists": "yellow", "failed": "red", "cancelled": "yellow",
                 "unsupported": "dark_orange"}
_SEVERITY_STYLE = {"info": "dim", "warning": "yellow", "error": "red"}

ProfileOpt = Annotated[str, typer.Option("--profile", "-p", help="Target profile (see profiles/).")]
RecursiveOpt = Annotated[bool, typer.Option("--recursive", "-r", help="Include subfolders.")]
DeepOpt = Annotated[bool | None, typer.Option("--deep/--no-deep", help="Frame-timestamp VFR check (slower).")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable output.")]

_BACKEND_LABEL = {"cuda": "NVIDIA CUDA / NVENC", "qsv": "Intel Quick Sync", "cpu": "CPU only"}
_PROBE_KIND_LABEL = {"device": "GPU devices", "decoder": "HEVC 10-bit decode", "encoder": "Encoders",
                     "filter": "Filters"}


@app.command()
def version() -> None:
    """Print the application version."""
    from clipsana import __version__
    typer.echo(f"Clipsana {__version__}")


@app.command()
def scan(
    path: Annotated[Path, typer.Argument(help="Folder with footage.")],
    profile: ProfileOpt = "social-30", recursive: RecursiveOpt = False, deep: DeepOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Check every clip in a folder and report what would break the edit."""
    result = _scan(path, profile, recursive, deep, as_json)
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
    else:
        _print_scan(result)


@app.command()
def plan(
    scan_id: Annotated[str, typer.Argument(help="ID printed by `clipsana scan`.")],
    as_json: JsonOpt = False,
) -> None:
    """Build the ffmpeg commands that would fix a scanned folder (changes nothing)."""
    from clipsana.core import service
    result = service.plan(scan_id)
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
    else:
        _print_plan(result, show_commands=True)


@app.command()
def apply(
    plan_id: Annotated[str, typer.Argument(help="ID printed by `clipsana plan`.")],
    force: Annotated[bool, typer.Option("--force", help="Overwrite outputs Clipsana did not create.")] = False,
) -> None:
    """Run a plan. Originals are never touched; results go to the profile's output folder."""
    if not _run_plan(plan_id, force):
        raise typer.Exit(code=1)


@app.command()
def fix(
    path: Annotated[Path, typer.Argument(help="Folder with footage.")],
    profile: ProfileOpt = "social-30", recursive: RecursiveOpt = False, deep: DeepOpt = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Only show what would be done.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite outputs Clipsana did not create.")] = False,
) -> None:
    """Scan, plan and apply in one go."""
    from clipsana.core import service
    result = _scan(path, profile, recursive, deep, as_json=False)
    _print_scan(result)
    planned = service.plan(result.scan_id)
    _print_plan(planned, show_commands=dry_run)
    ok = dry_run or _run_plan(planned.plan_id, force)
    if not ok or result.summary.get("error") or result.summary.get("needs_human"):
        raise typer.Exit(code=1)


def _scan(path: Path, profile: str, recursive: bool, deep: bool | None, as_json: bool):
    from clipsana.core import profiles, service
    console = Console(stderr=True, highlight=False)
    try:
        if as_json:
            return service.scan(path, profile=profile, recursive=recursive, deep=deep)
        with console.status("Scanning...") as status:
            return service.scan(path, profile=profile, recursive=recursive, deep=deep,
                                on_file=lambda f: status.update(f"Scanned {Path(f.path).name}"))
    except (NotADirectoryError, profiles.ProfileError) as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=2) from e


def _print_scan(result) -> None:
    console = Console(highlight=False)
    table = Table(title=f"Scan {result.scan_id} · {result.root} · profile {result.profile}", title_justify="left")
    for col in ("File", "Status", "Video", "fps r/avg", "Audio", "Findings"):
        table.add_column(col)
    for f in result.files:
        v, a = f.media.video, f.media.audio
        video = f"{v.codec} {v.bit_depth}-bit {v.display_width}x{v.display_height}" if v else "-"
        fps = f"{v.r_fps:g} / {v.avg_fps:g}" if v else "-"
        audio = f"{a.sample_rate} Hz" if a else "-"
        findings = "\n".join(f"[{_SEVERITY_STYLE[i.severity]}]{escape(i.message)}[/]" for i in f.issues) or "-"
        table.add_row(escape(Path(f.path).name), f"[{_STATUS_STYLE[f.status]}]{f.status}[/]", video, fps, audio,
                      findings)
    console.print(table)
    console.print("  ".join(f"[{_STATUS_STYLE[k]}]{k}: {v}[/]" for k, v in result.summary.items()))


def _print_plan(result, show_commands: bool) -> None:
    import subprocess

    from clipsana.core.backends import find_ffmpeg
    console = Console(highlight=False)
    if not result.items:
        console.print("[green]Nothing to fix.[/]")
        return
    console.print(f"\n[bold]Plan {result.plan_id}[/] · backend {_BACKEND_LABEL[result.backend]} · "
                  f"~{result.est_bytes / 2**30:.2f} GB to write")
    for e in result.items:
        if e.item is None:
            console.print(f"  [{_STATUS_STYLE[e.status]}]{e.status}[/] file #{e.file_id}: {escape(e.reason)}")
            continue
        console.print(f"  [{_STATUS_STYLE[e.status]}]{e.status:8}[/] {escape(Path(e.item.source).name)} -> "
                      f"{escape(e.item.output)}  [dim]({', '.join(e.item.rule_ids)})[/]")
        if show_commands:
            # Printed verbatim: ffmpeg syntax like "0:v:0" would otherwise turn into emoji or markup.
            console.print("    " + subprocess.list2cmdline([find_ffmpeg()[0], *e.item.args]), style="dim",
                          markup=False, emoji=False, highlight=False, soft_wrap=True)


def _run_plan(plan_id: str, force: bool) -> bool:
    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

    from clipsana.core import service
    console = Console(highlight=False)
    tasks: dict[str, int] = {}
    with Progress(TextColumn("{task.description}"), BarColumn(), TextColumn("{task.percentage:>5.1f}%"),
                  TextColumn("{task.fields[fps]}"), TimeRemainingColumn(), console=console) as bar:
        def on_progress(job_id, p) -> None:
            if job_id not in tasks:
                tasks[job_id] = bar.add_task(f"job {job_id}", total=100, fps="")
            bar.update(tasks[job_id], completed=p.percent, fps=f"{p.fps:.0f} fps" if p.fps else "")
        results = service.apply(plan_id, force=force, on_progress=on_progress)
    for r in results:
        detail = f" [dim]{escape(r.error.splitlines()[-1]) if r.error else ''}[/]" if r.status != "done" else ""
        console.print(f"  [{_STATUS_STYLE[r.status]}]{r.status:9}[/] {escape(Path(r.output).name)} "
                      f"[dim]({r.backend_used}, {r.seconds:.1f} s)[/]{detail}")
    return all(r.status == "done" for r in results)


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON (for scripts, n8n, AI).")]
    = False,
    quick: Annotated[bool, typer.Option("--quick", help="Skip functional ffmpeg probes (listings only).")] = False,
    path: Annotated[list[Path] | None, typer.Option("--path", help="Folder whose free space to check (repeatable).")]
    = None,
) -> None:
    """Detect GPU, CPU, RAM, disk space and what the bundled ffmpeg can do on this machine."""
    from clipsana.core.doctor import run_doctor, save_report

    report = run_doctor(disk_paths=path or None, run_probes=not quick)
    saved = save_report(report)
    if as_json:
        typer.echo(report.model_dump_json(indent=2))
    else:
        _print_doctor(report, saved)
    if report.ffmpeg is None:
        raise typer.Exit(code=1)


def _print_doctor(report: DoctorReport, saved: Path) -> None:
    console = Console(highlight=False)
    s = report.system
    console.print(Panel.fit(
        f"[bold]Clipsana doctor[/]  ·  v{report.clipsana_version}\n"
        f"Acceleration backend: [bold cyan]{_BACKEND_LABEL[report.backend]}[/]",
        border_style="magenta"))

    system = Table(title="System", title_justify="left", show_header=False, box=None, padding=(0, 2))
    system.add_row("OS", s.os)
    system.add_row("CPU", f"{s.cpu}  [dim]({s.cpu_threads} threads)[/]")
    system.add_row("RAM", f"{s.ram_total_mb / 1024:.1f} GB  [dim]({s.ram_available_mb / 1024:.1f} GB free)[/]")
    for d in s.disks:
        system.add_row("Disk", f"{d.path}  [dim]{d.free_gb} GB free of {d.total_gb} GB[/]")
    console.print(system)

    gpus = Table(title="GPUs", title_justify="left")
    for col in ("Name", "Vendor", "Driver", "VRAM", "Load"):
        gpus.add_column(col)
    for g in s.gpus:
        vram = f"{g.memory_total_mb} MB" if g.memory_total_mb else "-"
        load = f"{g.utilization_pct} %" if g.utilization_pct is not None else "-"
        gpus.add_row(g.name, g.vendor, g.driver, vram, load)
    console.print(gpus if s.gpus else "[yellow]No GPU detected[/]")

    f = report.ffmpeg
    if f:
        build = f.build.get("asset", "unknown build (not from tools/fetch_ffmpeg.py)")
        console.print(f"\n[bold]ffmpeg[/] {f.version}\n[dim]{f.ffmpeg}\n{build}[/]")
        console.print(f"[dim]hwaccels:[/] {', '.join(f.hwaccels)}")
        probes = Table(title="Capability probes (real encode/decode on this machine)", title_justify="left")
        for col in ("Group", "Capability", "Result", "Time"):
            probes.add_column(col)
        for kind in ("device", "decoder", "encoder", "filter"):
            for p in (p for p in f.probes if p.kind == kind):
                result = "[green]✓ works[/]" if p.ok else f"[red]✗ failed[/] [dim]{p.detail[:60]}[/]"
                probes.add_row(_PROBE_KIND_LABEL[kind], p.name, result, f"{p.seconds:.2f} s")
        if f.probes:
            console.print(probes)

    for problem in report.problems:
        console.print(f"[bold orange1]![/] {problem}")
    if not report.problems:
        console.print("[green]No problems found.[/]")
    console.print(f"[dim]Report saved to {saved}[/]")


if __name__ == "__main__":
    app()
