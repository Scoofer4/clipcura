"""Measure a full Clipcura job on 4K HEVC 10-bit HLG footage: CPU only vs the path doctor picked (CLAUDE.md §13).

Generates a 10 s 4K 29.97 fps HLG HEVC Main10 clip with 44.1 kHz audio (what a phone records and what trips
up the editor), then converts it with each path and reports wall time and the output format. Everything is
written under the given work folder, which must not exist yet; app data stays inside it as well.

Usage:  uv run python tools/benchmark_hevc10.py D:\\Temp\\clipcura-bench [--profile social-30] [--rounds 3]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--profile", default="social-30")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()
    if args.workdir.exists():
        sys.exit(f"{args.workdir} exists; pass a new folder (results and app data are written there)")
    os.environ["CLIPCURA_HOME"] = str(args.workdir / "app")

    # Imported after CLIPCURA_HOME is set so the database lands in the work folder.
    from clipcura.core import backends, service
    from clipcura.core.models import Paths

    ffmpeg, ffprobe = backends.find_ffmpeg()
    raw = args.workdir / "01_raw"
    raw.mkdir(parents=True)
    src = raw / "hlg_hevc10_4k.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=3840x2160:r=30000/1001:d=10",
                    "-f", "lavfi", "-i", "sine=f=440:r=44100:d=10",
                    "-vf", ("setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc,"
                            "format=yuv420p10le"),
                    "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error",
                    "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
                    "-c:a", "aac", "-shortest", str(src)], check=True)

    runs = {"cpu-only": Paths(decode="cpu", encode="cpu", scale="cpu", tonemap="zscale"),
            "measured": service.detect_paths()}
    report = {}
    for name, paths in runs.items():
        times, out = [], {}
        for _ in range(args.rounds):
            scan = service.scan(raw, profile=args.profile)
            plan = service.plan(scan.scan_id, paths=paths)
            started = time.perf_counter()
            (res,) = service.apply(plan.plan_id, force=True)
            times.append(time.perf_counter() - started)
            if res.status != "done":
                sys.exit(f"{name}: {res.status} {res.error}")
            probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=codec_name,profile,pix_fmt,width,height,r_frame_rate,color_transfer",
                                    "-of", "json", res.output], capture_output=True, text=True, check=True)
            out = json.loads(probe.stdout)["streams"][0]
            Path(res.output).unlink()
        report[name] = {"paths": paths.model_dump(), "seconds": [round(t, 1) for t in times],
                        "median_s": round(statistics.median(times), 1), "output": out}
    report["speedup"] = round(report["cpu-only"]["median_s"] / report["measured"]["median_s"], 2)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
