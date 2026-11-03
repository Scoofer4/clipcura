"""Data models shared by the core, CLI, API and MCP (pydantic, so they serialize to JSON as-is)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

Backend = Literal["cuda", "qsv", "cpu"]
Vendor = Literal["nvidia", "intel", "amd", "other"]
Severity = Literal["info", "warning", "error"]
FileStatus = Literal["ok", "fixable", "needs_human", "error"]


class VideoStream(BaseModel):
    codec: str
    profile: str = ""
    pix_fmt: str = ""
    width: int = 0
    height: int = 0
    r_fps: float = 0.0       # nominal rate the container claims (r_frame_rate)
    avg_fps: float = 0.0     # frames / duration (avg_frame_rate)
    color_transfer: str = ""
    color_primaries: str = ""
    color_space: str = ""
    rotation: int = 0        # degrees from the display matrix, as ffprobe reports it
    bit_depth: int = 8

    @property
    def rotated(self) -> bool:
        return abs(self.rotation) % 180 == 90

    @property
    def display_width(self) -> int:
        return self.height if self.rotated else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotated else self.height


class AudioStream(BaseModel):
    codec: str
    sample_rate: int = 0
    channels: int = 0


class MediaInfo(BaseModel):
    path: str
    size: int = 0
    mtime: float = 0.0
    duration: float = 0.0
    container: str = ""
    video: VideoStream | None = None
    audio: AudioStream | None = None
    probe_error: str | None = None
    decode_error: str | None = None
    # Share of frame intervals deviating >20 % from the mean (None = deep check not run).
    pts_irregularity: float | None = None


class OutputSettings(BaseModel):
    codec: str
    container: Literal["mov", "mp4", "mkv"]
    folder: str = "../02_edit"
    suffix: str = "_edit"


class RuleSettings(BaseModel):
    disabled: list[str] = Field(default_factory=list)
    vfr_deep_check: bool = False
    add_silent_audio: bool = False

    # Rules added as plugins keep their own settings here under their rule id (e.g. `loudness: {...}`), so a
    # new rule never needs a core change (CLAUDE.md §6).
    model_config = ConfigDict(extra="allow")

    def settings(self, rule_id: str) -> dict:
        value = (self.model_extra or {}).get(rule_id)
        return value if isinstance(value, dict) else {}


class Profile(BaseModel):
    name: str
    label: str
    fps: PositiveFloat
    max_long_side: PositiveInt
    audio_rate: PositiveInt
    color: Literal["rec709-sdr"] = "rec709-sdr"
    output: OutputSettings
    rules: RuleSettings = Field(default_factory=RuleSettings)


class PlanItem(BaseModel):
    source: str
    output: str
    args: list[str]               # ffmpeg arguments (without the binary and progress flags)
    fallback_args: list[str]      # same job on the CPU, used when the GPU path fails at runtime
    backend: DecodePath           # decoding path of `args`
    rule_ids: list[str]
    plan_hash: str                # identifies "same input, same recipe" so reruns can skip finished files
    est_bytes: int
    duration: float


# Rule plugin contract (CLAUDE.md §6). Plain dataclasses keep third-party rules dependency-free.
@dataclass
class Issue:
    rule_id: str
    severity: Severity
    message: str
    auto_fixable: bool
    data: dict = field(default_factory=dict)


@dataclass
class FixStep:
    order: int                      # filter position: rotation < HDR < scale < fps
    video_filters: list[str] = field(default_factory=list)
    audio_filters: list[str] = field(default_factory=list)
    output_args: list[str] = field(default_factory=list)
    gpu_variant: dict[str, list[str]] | None = None
    # Extra inputs such as a generated silent audio track: each entry is the argument list before "-i".
    extra_inputs: list[list[str]] = field(default_factory=list)


class Rule(Protocol):
    id: str
    title: str

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None: ...

    def fix(self, issue: Issue, profile: Profile) -> FixStep | None: ...


class Probe(BaseModel):
    """Result of actually running ffmpeg with a capability, not just finding it in a listing."""
    name: str
    kind: Literal["device", "encoder", "filter", "decoder"] = "encoder"
    ok: bool
    seconds: float = 0.0
    detail: str = ""


class EncoderQuality(BaseModel):
    """How a GPU encoder compares with its CPU equivalent at the same profile (issue #14, CLAUDE.md §4)."""
    cpu_encoder: str
    metric: Literal["vmaf", "ssim"]
    quality: int | None   # first CQ / global_quality step that matches the CPU encoder; None = never matched
    delta: float | None   # worst GPU-minus-CPU score over the test clips at that step (or the best step tried)


class Benchmarks(BaseModel):
    """Measured throughput in frames per second per path (0 = path failed on this machine)."""
    # Whole-job throughput (decode -> filters -> DNxHR encode) on a camera-like 4K HEVC sample: measuring a
    # step in isolation picked the CPU decoder although the GPU was 2.6x faster on real footage.
    decode: dict[str, float] = Field(default_factory=dict)    # cpu | cuda | d3d11va
    scale: dict[str, float] = Field(default_factory=dict)     # cpu | scale_cuda | libplacebo, 4K -> 1080p
    tonemap: dict[str, float] = Field(default_factory=dict)   # zscale | libplacebo, HLG -> Rec.709
    quality: dict[str, EncoderQuality] = Field(default_factory=dict)  # per working GPU encoder


# Decoding goes through hwaccels that hand frames back in system memory at the source bit depth; QSV decoding
# would keep them on the GPU and break the CPU filter chain, so Intel GPUs decode through D3D11VA.
DecodePath = Literal["cpu", "cuda", "d3d11va"]
ScalePath = Literal["cpu", "scale_cuda", "libplacebo"]
TonemapPath = Literal["zscale", "libplacebo"]


class Paths(BaseModel):
    """Which implementation each processing step uses (CLAUDE.md §4: quality first, then measured speed)."""
    decode: DecodePath = "cpu"
    encode: Backend = "cpu"         # backend for auto_* encoders (nvenc / qsv / cpu)
    scale: ScalePath = "cpu"
    tonemap: TonemapPath = "zscale"
    # From doctor's quality calibration (issue #14): the quality setting each GPU encoder needs to match its CPU
    # equivalent, and the GPU encoders that never matched (auto_* codecs then encode on the CPU).
    gpu_quality: dict[str, int] = Field(default_factory=dict)
    cpu_only: list[str] = Field(default_factory=list)


class FfmpegInfo(BaseModel):
    ffmpeg: str
    ffprobe: str
    version: str
    build: dict = Field(default_factory=dict)
    hwaccels: list[str] = Field(default_factory=list)
    encoders: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    probes: list[Probe] = Field(default_factory=list)
    benchmarks: Benchmarks | None = None

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
    clipcura_version: str
    backend: Backend
    paths: Paths = Field(default_factory=Paths)
    system: SystemInfo
    ffmpeg: FfmpegInfo | None = None
    problems: list[str] = Field(default_factory=list)
