"""Data models shared by the core, CLI, API and MCP (pydantic, so they serialize to JSON as-is)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Backend = Literal["cuda", "qsv", "cpu"]
Vendor = Literal["nvidia", "intel", "amd", "other"]


class Probe(BaseModel):
    """Result of actually running ffmpeg with a capability, not just finding it in a listing."""
    name: str
    kind: Literal["device", "encoder", "filter", "decoder"] = "encoder"
    ok: bool
    seconds: float = 0.0
    detail: str = ""


class FfmpegInfo(BaseModel):
    ffmpeg: str
    ffprobe: str
    version: str
    build: dict = Field(default_factory=dict)
    hwaccels: list[str] = Field(default_factory=list)
    encoders: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    probes: list[Probe] = Field(default_factory=list)

    def works(self, name: str) -> bool:
        return any(p.name == name and p.ok for p in self.probes)


class GpuInfo(BaseModel):
    name: str
    vendor: Vendor
    driver: str = ""
    memory_total_mb: int | None = None
    memory_used_mb: int | None = None
    utilization_pct: int | None = None


class DiskInfo(BaseModel):
    path: str
    total_gb: float
    free_gb: float


class SystemInfo(BaseModel):
    os: str
    cpu: str
    cpu_threads: int
    ram_total_mb: int
    ram_available_mb: int
    gpus: list[GpuInfo] = Field(default_factory=list)
    disks: list[DiskInfo] = Field(default_factory=list)


class DoctorReport(BaseModel):
    created_at: str
    clipsana_version: str
    backend: Backend
    system: SystemInfo
    ffmpeg: FfmpegInfo | None = None
    problems: list[str] = Field(default_factory=list)
