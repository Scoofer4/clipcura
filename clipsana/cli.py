"""Clipsana command line. Commands grow with milestones (doctor in M0, scan/plan/apply in M1)."""
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from clipsana.core.models import DoctorReport

app = typer.Typer(help="Clipsana - check and fix footage before editing.", no_args_is_help=True)

_BACKEND_LABEL = {"cuda": "NVIDIA CUDA / NVENC", "qsv": "Intel Quick Sync", "cpu": "CPU only"}
_PROBE_KIND_LABEL = {"device": "GPU devices", "decoder": "HEVC 10-bit decode", "encoder": "Encoders",
                     "filter": "Filters"}


@app.command()
def version() -> None:
    """Print the application version."""
    from clipsana import __version__
    typer.echo(f"Clipsana {__version__}")


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
