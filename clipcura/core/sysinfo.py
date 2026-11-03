"""Hardware facts for doctor and the GUI's system HUD, using only the standard library and OS tools."""
from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from clipcura.core.models import DiskInfo, GpuInfo, SystemInfo, Vendor

# Windows lists remote-desktop / VR mirror drivers as video controllers; they cannot encode anything.
_VIRTUAL_MARKERS = ("virtual", "remote", "basic display", "mirror", "parsec", "meta ")


def _vendor_of(name: str) -> Vendor:
    lowered = name.lower()
    if "nvidia" in lowered:
        return "nvidia"
    if "intel" in lowered:
        return "intel"
    if "amd" in lowered or "radeon" in lowered:
        return "amd"
    return "other"


def _int_or_none(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:  # nvidia-smi prints "[N/A]" on some laptop GPUs
        return None


def parse_nvidia_smi(text: str) -> list[GpuInfo]:
    """Parse `--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu` CSV."""
    gpus = []
    for line in text.splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) >= 5 and cols[0]:
            gpus.append(GpuInfo(name=cols[0], vendor="nvidia", driver=cols[1],
                                memory_total_mb=_int_or_none(cols[2]), memory_used_mb=_int_or_none(cols[3]),
                                utilization_pct=_int_or_none(cols[4])))
    return gpus


def parse_video_controllers(text: str) -> list[GpuInfo]:
    data = json.loads(text) if text.strip() else []
    if isinstance(data, dict):
        data = [data]
    gpus = []
    for item in data:
        name = (item.get("Name") or "").strip()
        if not name or any(m in name.lower() for m in _VIRTUAL_MARKERS):
            continue
        gpus.append(GpuInfo(name=name, vendor=_vendor_of(name), driver=item.get("DriverVersion") or ""))
    return gpus


def merge_gpus(adapters: list[GpuInfo], nvidia: list[GpuInfo]) -> list[GpuInfo]:
    """Adapters from Windows, with NVIDIA entries replaced by richer nvidia-smi data when names match."""
    by_name = {g.name: g for g in nvidia}
    merged = [by_name.pop(g.name, g) for g in adapters]
    return merged + list(by_name.values())


def _run(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=20, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def detect_gpus() -> list[GpuInfo]:
    nvidia = []
    if shutil.which("nvidia-smi"):
        query = "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu"
        nvidia = parse_nvidia_smi(_run(["nvidia-smi", query, "--format=csv,noheader,nounits"]))
    adapters = []
    if sys.platform == "win32":
        adapters = parse_video_controllers(_run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion | ConvertTo-Json"]))
    return merge_gpus(adapters, nvidia)


def cpu_name() -> str:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory_mb() -> tuple[int, int]:
    """(total, available) physical RAM in MB. Win32 API so we avoid a psutil dependency."""
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return status.ullTotalPhys // 2**20, status.ullAvailPhys // 2**20


def disk_usage(path: Path) -> DiskInfo:
    usage = shutil.disk_usage(path)
    return DiskInfo(path=str(path), total_gb=round(usage.total / 2**30, 1), free_gb=round(usage.free / 2**30, 1))


def collect(disk_paths: list[Path]) -> SystemInfo:
    total, available = memory_mb()
    return SystemInfo(
        os=f"{platform.system()} {platform.release()} ({platform.version()})",
        cpu=cpu_name(),
        cpu_threads=os.cpu_count() or 1,
        ram_total_mb=total,
        ram_available_mb=available,
        gpus=detect_gpus(),
        disks=[disk_usage(p) for p in disk_paths if p.exists()],
    )


def pid_alive(pid: int | None) -> bool:
    """Whether a process with this id still runs. PIDs can be reused, but only long after the process ended."""
    if not pid or pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    # os.kill(pid, 0) would terminate the process on Windows; ask the kernel instead.
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
