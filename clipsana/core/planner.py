"""Turn a file's issues into exactly one ffmpeg command (CLAUDE.md §6): every fix runs in a single pass,
so the clip is decoded and encoded once."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from clipsana import rules
from clipsana.core.models import Backend, DecodePath, FixStep, Issue, MediaInfo, Paths, PlanItem, Profile


class PlanError(ValueError):
    pass


class UnsupportedError(PlanError):
    """The profile cannot produce this file (reported in the plan instead of failing at encode time)."""


# Encoders with a hard minimum frame size: dnxhd refuses anything below 256x120 with a generic error.
_MIN_SIZE = {"dnxhr_hq": (256, 120), "dnxhr_hqx": (256, 120)}
_TOO_SMALL = {
    "en": "Output {w}x{h} is below the {codec} minimum of {mw}x{mh} - pick a profile with another codec",
    "cs": "Výstup {w}x{h} je menší než minimum {codec} {mw}x{mh} - zvol profil s jiným kodekem",
}


# video args (fps -> list), pixel format, intra-frame editing codec (gets PCM audio)
_ENCODERS: dict[str, tuple] = {
    "dnxhr_hq": (lambda fps: ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq"], "yuv422p", True),
    "dnxhr_hqx": (lambda fps: ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx"], "yuv422p10le", True),
    "prores_422": (lambda fps: ["-c:v", "prores_ks", "-profile:v", "2", "-vendor", "apl0"], "yuv422p10le", True),
    # Long-GOP codecs get a one-second GOP: much smoother scrubbing in the editor at a small size cost.
    "libx264": (lambda fps: ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-g", fps], "yuv420p", False),
    "libx265": (lambda fps: ["-c:v", "libx265", "-preset", "medium", "-crf", "20", "-g", fps,
                             "-x265-params", "log-level=error"], "yuv420p", False),
    "h264_nvenc": (lambda fps: ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "19",
                                "-b:v", "0", "-g", fps], "yuv420p", False),
    "hevc_nvenc": (lambda fps: ["-c:v", "hevc_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "21",
                                "-b:v", "0", "-g", fps], "yuv420p", False),
    "h264_qsv": (lambda fps: ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "21", "-g", fps],
                 "nv12", False),
    "hevc_qsv": (lambda fps: ["-c:v", "hevc_qsv", "-preset", "medium", "-global_quality", "23", "-g", fps],
                 "nv12", False),
}
_AUTO = {"auto_h264": {"cuda": "h264_nvenc", "qsv": "h264_qsv", "cpu": "libx264"},
         "auto_hevc": {"cuda": "hevc_nvenc", "qsv": "hevc_qsv", "cpu": "libx265"}}
# What a profile may name as output.codec, and which of them are intra-frame editing codecs (PCM audio, so
# they need a container that carries PCM: MOV or Matroska, not MP4).
CODECS = frozenset(_ENCODERS) | frozenset(_AUTO)
INTRA_CODECS = frozenset(c for c, (_, _, intra) in _ENCODERS.items() if intra)
_CPU_EQUIVALENT = {"h264_nvenc": "libx264", "h264_qsv": "libx264", "hevc_nvenc": "libx265", "hevc_qsv": "libx265"}
# Rough output bits per pixel, only for the free-space check and the size estimate shown before a run.
_BITS_PER_PIXEL = {"dnxhr_hq": 2.33, "dnxhr_hqx": 3.5, "prores_422": 2.4, "libx264": 0.12, "libx265": 0.08,
                   "h264_nvenc": 0.12, "hevc_nvenc": 0.08, "h264_qsv": 0.12, "hevc_qsv": 0.08}
_HWACCEL = {"cuda": ["-hwaccel", "cuda"], "d3d11va": ["-hwaccel", "d3d11va"], "cpu": []}
_CONTAINER = {"mov": ["-f", "mov"], "mp4": ["-f", "mp4", "-movflags", "+faststart"], "mkv": ["-f", "matroska"]}
_REC709 = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]
# Encoder options alone are not enough: ffmpeg 8 writes primaries/transfer from the frames, which stay
# "unknown" for untagged sources. By this point every frame is Rec.709 (HDR tone-mapped, other colour spaces
# converted by the color_space rule, untagged treated as Rec.709), so labelling the frames is truthful.
_REC709_FRAMES = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"


def resolve_codec(codec: str, backend: Backend) -> str:
    if codec in _AUTO:
        return _AUTO[codec][backend]
    if backend == "cpu":
        return _CPU_EQUIVALENT.get(codec, codec)
    if codec not in _ENCODERS:
        raise PlanError(f"Unknown output codec '{codec}'")
    return codec


def _split(f: str) -> tuple[str, list[str]]:
    name, _, opts = f.partition("=")
    return name, opts.split(":") if opts else []


def merge_filters(filters: list[str]) -> list[str]:
    """Drop duplicates and merge single filters of the same name whose options are all `key=value`.

    Two rules can ask for the same filter (vfr and fps_mismatch both want `fps`, vfr and audio_rate both
    want `aresample`); running it twice would cost time and, for aresample, quality.
    """
    merged: list[str] = []
    for f in filters:
        if f in merged:
            continue
        name, opts = _split(f)
        target = next((i for i, m in enumerate(merged) if "," not in m and "," not in f and _split(m)[0] == name),
                      None)
        if target is not None:
            existing = _split(merged[target])[1]
            if all("=" in o for o in existing + opts):
                combined = dict(o.split("=", 1) for o in existing) | dict(o.split("=", 1) for o in opts)
                merged[target] = f"{name}=" + ":".join(f"{k}={v}" for k, v in combined.items())
                continue
        merged.append(f)
    return merged


def _dedupe_pairs(args: list[str]) -> list[str]:
    seen, out = set(), []
    for flag, value in zip(args[::2], args[1::2], strict=False):
        if (flag, value) not in seen:
            seen.add((flag, value))
            out += [flag, value]
    return out


def _video_filters(steps: list[FixStep], paths: Paths | None) -> list[str]:
    """Each step's CPU filters, or its GPU variant when the chosen paths say so."""
    selected = {f"scale:{paths.scale}", f"tonemap:{paths.tonemap}"} if paths else set()
    # scale_cuda uploads plain 4:2:0 frames; after tone-mapping or colour conversion that is no longer given.
    reformatted = any(s.order < 30 and s.video_filters for s in steps)
    filters: list[str] = []
    for s in steps:
        chosen = s.video_filters
        for key, variant in (s.gpu_variant or {}).items():
            if key in selected and not (key == "scale:scale_cuda" and reformatted):
                chosen = variant
                break
        filters += chosen
    return filters


def build_args(media: MediaInfo, steps: list[FixStep], profile: Profile, backend: DecodePath, output: Path,
               paths: Paths | None = None) -> list[str]:
    """ffmpeg arguments for one file. `backend` is the decode path; `paths` (if given) picks GPU filter
    variants and the backend for auto_* encoders. Without `paths` everything but decoding runs on the CPU."""
    steps = sorted(steps, key=lambda s: s.order)
    codec = resolve_codec(profile.output.codec, paths.encode if paths else "cpu")
    video_args, pix_fmt, intra = _ENCODERS[codec]
    fps = str(round(profile.fps))

    args = [*_HWACCEL[backend], "-i", media.path]
    extra = [inp for s in steps for inp in s.extra_inputs]
    for inp in extra:
        args += inp
    args += ["-map", "0:v:0"]
    if media.audio is not None:
        args += ["-map", "0:a:0"]
    elif extra:
        args += ["-map", "1:a:0", "-shortest"]

    vf = merge_filters(_video_filters(steps, paths)) + [_REC709_FRAMES, f"format={pix_fmt}"]
    args += ["-vf", ",".join(vf)]
    af = merge_filters([f for s in steps for f in s.audio_filters])
    if af:
        args += ["-af", ",".join(af)]
    args += video_args(fps)
    if media.audio is not None or extra:
        args += ["-c:a", "pcm_s16le"] if intra else ["-c:a", "aac", "-b:a", "320k"]
    args += _dedupe_pairs([a for s in steps for a in s.output_args])
    # Everything leaves as SDR Rec.709 (HDR is tone-mapped), so tag it explicitly for the editor.
    args += _REC709 + ["-map_metadata", "0"] + _CONTAINER[profile.output.container] + [str(output)]
    return args


def output_path(source: Path, scan_root: Path, profile: Profile) -> Path:
    out_dir = Path(_normalize(scan_root / profile.output.folder))
    relative = source.parent.relative_to(scan_root) if source.parent != scan_root else Path()
    out = out_dir / relative / f"{source.stem}{profile.output.suffix}.{profile.output.container}"
    if _normalize(out).lower() == _normalize(source).lower():
        raise PlanError(f"Output would overwrite the original {source}")
    return out


def _normalize(p: Path) -> str:
    # Pure path normalization (no filesystem access) so planning works on paths that don't exist yet.
    parts: list[str] = []
    for part in Path(p).parts:
        if part == "..":
            if parts and parts[-1] not in (Path(p).anchor,):
                parts.pop()
        elif part != ".":
            parts.append(part)
    return str(Path(*parts)) if parts else str(p)


def output_size(media: MediaInfo, vf: list[str]) -> tuple[int, int]:
    v = media.video
    w, h = (v.display_width, v.display_height) if v else (1920, 1080)
    for f in vf:
        if m := re.match(r"scale=(\d+):(\d+)", f):
            w, h = int(m.group(1)), int(m.group(2))
    return w, h


def _estimate_bytes(media: MediaInfo, vf: list[str], codec: str, profile: Profile) -> int:
    w, h = output_size(media, vf)
    video = _BITS_PER_PIXEL.get(codec, 0.5) * w * h * profile.fps * media.duration / 8
    audio = profile.audio_rate * 2 * 2 * media.duration  # 16-bit stereo PCM upper bound
    return int(video + audio)


def build_item(media: MediaInfo, issues: list[Issue], profile: Profile, backend: DecodePath,
               scan_root: Path, paths: Paths | None = None) -> PlanItem | None:
    fixable = [i for i in issues if i.auto_fixable]
    if not any(rules.is_standalone(i.rule_id) for i in fixable):
        return None
    steps = [s for i in fixable if (s := rules.get_rule(i.rule_id).fix(i, profile)) is not None]
    if not steps:
        return None
    vf = [f for s in steps for f in s.video_filters]
    if profile.output.codec in _MIN_SIZE:
        (mw, mh), (w, h) = _MIN_SIZE[profile.output.codec], output_size(media, vf)
        if w < mw or h < mh:
            raise UnsupportedError(rules.localize(_TOO_SMALL, w=w, h=h, codec="DNxHR", mw=mw, mh=mh))
    out = output_path(Path(media.path), scan_root, profile)
    args = build_args(media, steps, profile, backend, out, paths)
    # The fallback is the plain CPU recipe: no GPU decode, no GPU filters, no GPU encoder.
    fallback = build_args(media, steps, profile, "cpu", out)
    recipe = json.dumps({"args": fallback, "size": media.size, "mtime": media.mtime}, sort_keys=True)
    return PlanItem(
        source=media.path, output=str(out), args=args, fallback_args=fallback, backend=backend,
        rule_ids=sorted({i.rule_id for i in fixable}),
        plan_hash=hashlib.sha256(recipe.encode()).hexdigest()[:16],
        est_bytes=_estimate_bytes(media, vf, resolve_codec(profile.output.codec, paths.encode if paths else "cpu"),
                                  profile),
        duration=media.duration)
