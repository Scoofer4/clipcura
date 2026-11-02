#!/usr/bin/env python3
"""
mm_video_prep.py – kontrola a příprava videí pro střih (DaVinci Resolve)
Metaverse Media s.r.o.

Co dělá:
  1. Projde složku s videi (volitelně i podsložky).
  2. Každý soubor prozkoumá přes ffprobe a hledá problémy:
     VFR, jiná snímková frekvence, HDR, HEVC 10-bit, příliš velké
     nebo liché rozlišení, jiná vzorkovací frekvence zvuku.
  3. Problémové soubory převede do střihového formátu (výchozí DNxHR HQ),
     v pořádku jsou nechá být. Originály se NIKDY nemění.
  4. Zapíše report (CSV + JSON) – použitelný i pro n8n.

Požadavky: Python 3.9+, ffmpeg a ffprobe v PATH (build se zscale kvůli HDR).

Příklady:
  python mm_video_prep.py D:\\Footage\\2026_project\\01_raw
  python mm_video_prep.py ./01_raw --out ./02_edit --fps 30 --profile dnxhr
  python mm_video_prep.py ./01_raw --dry-run          # jen report, nic nepřevádí
  python mm_video_prep.py ./01_raw --profile h264     # lehčí soubory (iPad, notebook)

Návratové kódy (pro n8n): 0 = vše OK, 1 = některé soubory selhaly, 2 = chyba vstupu.
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from fractions import Fraction
from pathlib import Path

# Přípony, které skript zpracuje. .insv (Insta360 360°) se jen nahlásí –
# potřebuje reframe/export v Insta360 Studio nebo aplikaci.
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".mkv", ".avi"}
SKIP_EXT = {".insv", ".insp", ".lrv"}

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}   # PQ (HDR10/HDR10+) a HLG
VFR_TOLERANCE = 0.01                           # max. relativní rozdíl r vs avg fps

# Výstupní profily: video kodek, pixel formát, kontejner, audio
PROFILES = {
    # Plynulý střih v DaVinci i na slabším HW, velké soubory
    "dnxhr":  {"v": ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq"], "pix": "yuv422p",
               "ext": ".mov", "a": ["-c:a", "pcm_s16le"]},
    # 10bitová varianta (Log, HDR po převodu) – ještě větší soubory
    "dnxhrx": {"v": ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx"], "pix": "yuv422p10le",
               "ext": ".mov", "a": ["-c:a", "pcm_s24le"]},
    # ProRes 422 (na Windows funguje v Resolve také)
    "prores": {"v": ["-c:v", "prores_ks", "-profile:v", "2"], "pix": "yuv422p10le",
               "ext": ".mov", "a": ["-c:a", "pcm_s16le"]},
    # Lehký formát: H.264 s krátkým GOP (dobře se stříhá), pro iPad/notebook
    "h264":   {"v": ["-c:v", "libx264", "-preset", "medium", "-crf", "18"], "pix": "yuv420p",
               "ext": ".mp4", "a": ["-c:a", "aac", "-b:a", "320k"]},
}


@dataclass
class Result:
    """Jeden řádek reportu."""
    file: str
    status: str = "ok"            # ok | fixed | would_fix | skipped | error
    issues: list = field(default_factory=list)
    codec: str = ""
    pix_fmt: str = ""
    width: int = 0
    height: int = 0
    fps_r: float = 0.0            # nominální frekvence (r_frame_rate)
    fps_avg: float = 0.0          # průměrná frekvence (avg_frame_rate)
    transfer: str = ""
    audio_rate: int = 0
    output: str = ""
    message: str = ""


def run(cmd: list) -> subprocess.CompletedProcess:
    """Spustí příkaz a vrátí výsledek (bez výjimky při chybě)."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def to_fps(value: str) -> float:
    """Převede '30000/1001' na 29.97; '0/0' na 0."""
    try:
        f = Fraction(value)
        return float(f) if f.denominator else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path) -> dict:
    """Načte metadata první video a audio stopy přes ffprobe (JSON)."""
    p = run(["ffprobe", "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(path)])
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "ffprobe selhal")
    data = json.loads(p.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video:
        raise RuntimeError("soubor nemá video stopu")
    return {"video": video, "audio": audio}


def deep_vfr_check(path: Path, seconds: int = 20) -> bool:
    """
    Přesnější test VFR: změří rozestupy časových značek snímků
    v prvních N sekundách. Pomalejší, proto jen na vyžádání (--deep).
    """
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals",
             f"%+{seconds}", "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)])
    times = sorted(float(t) for t in p.stdout.split() if t.replace(".", "", 1).isdigit())
    if len(times) < 10:
        return False
    deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not deltas:
        return False
    mean = sum(deltas) / len(deltas)
    # Pokud se rozestupy liší o víc než 20 % od průměru u >2 % snímků, je to VFR
    outliers = sum(1 for d in deltas if abs(d - mean) > 0.2 * mean)
    return outliers / len(deltas) > 0.02


def analyze(path: Path, args) -> Result:
    """Zjistí problémy jednoho souboru a vyplní Result."""
    r = Result(file=str(path))
    info = probe(path)
    v, a = info["video"], info["audio"]

    r.codec = v.get("codec_name", "")
    r.pix_fmt = v.get("pix_fmt", "")
    r.width, r.height = int(v.get("width", 0)), int(v.get("height", 0))
    r.fps_r = round(to_fps(v.get("r_frame_rate", "0/0")), 3)
    r.fps_avg = round(to_fps(v.get("avg_frame_rate", "0/0")), 3)
    r.transfer = v.get("color_transfer", "") or ""
    r.audio_rate = int(a.get("sample_rate", 0)) if a else 0

    # 1) VFR – nominální a průměrná frekvence se liší (typicky telefon, screen recording)
    if r.fps_r and r.fps_avg and abs(r.fps_r - r.fps_avg) / r.fps_r > VFR_TOLERANCE:
        r.issues.append("VFR")
    elif args.deep and deep_vfr_check(path):
        r.issues.append("VFR (hluboký test)")

    # 2) Jiná snímková frekvence než cíl projektu
    if r.fps_avg and abs(r.fps_avg - args.fps) > 0.05:
        r.issues.append(f"fps {r.fps_avg} ≠ {args.fps}")

    # 3) HDR (PQ/HLG) – na SDR timeline vypadá vybledle nebo přepáleně
    if r.transfer in HDR_TRANSFERS:
        r.issues.append(f"HDR ({r.transfer})")

    # 4) HEVC 10-bit – DaVinci (hlavně free) ho dekóduje těžko nebo vůbec
    if r.codec == "hevc" and "10" in r.pix_fmt:
        r.issues.append("HEVC 10-bit")

    # 5) Rozlišení nad limit (delší strana) nebo liché rozměry
    if max(r.width, r.height) > args.max_size:
        r.issues.append(f"rozlišení {r.width}×{r.height} > {args.max_size}")
    if r.width % 2 or r.height % 2:
        r.issues.append("liché rozměry")

    # 6) Zvuk jinak než 48 kHz (standard pro video)
    if a and r.audio_rate and r.audio_rate != 48000:
        r.issues.append(f"zvuk {r.audio_rate} Hz")

    return r


def build_filters(r: Result, args, has_zscale: bool) -> list:
    """Sestaví řetězec video filtrů podle zjištěných problémů."""
    vf = []
    # HDR → SDR Rec.709 (tone-mapping). Vyžaduje filtr zscale v ffmpeg.
    if r.transfer in HDR_TRANSFERS and has_zscale:
        vf.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                  "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")
    # Zmenšení na limit, zachová poměr stran; -2 zaručí sudý rozměr
    if max(r.width, r.height) > args.max_size or r.width % 2 or r.height % 2:
        if r.width >= r.height:
            vf.append(f"scale='min({args.max_size},iw)':-2:flags=lanczos")
        else:
            vf.append(f"scale=-2:'min({args.max_size},ih)':flags=lanczos")
    # Konstantní snímková frekvence (řeší VFR i jinou fps)
    vf.append(f"fps={args.fps}")
    return vf


def transcode(r: Result, out_path: Path, args, has_zscale: bool) -> None:
    """Převede soubor do střihového formátu podle profilu."""
    prof = PROFILES[args.profile]
    vf = build_filters(r, args, has_zscale) + [f"format={prof['pix']}"]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if args.hwaccel:
        cmd += ["-hwaccel", "auto"]              # GPU dekódování (NVDEC apod.), je-li k dispozici
    cmd += ["-i", r.file,
            "-map", "0:v:0", "-map", "0:a:0?",   # první video + první audio, pokud existuje
            "-vf", ",".join(vf),
            "-fps_mode", "cfr",                  # vynutí konstantní frekvenci na výstupu
            *prof["v"],
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            *prof["a"],
            # Zvuk na 48 kHz a srovnání se změněnou časovou osou (prevence posunu u VFR)
            "-af", "aresample=48000:async=1:first_pts=0",
            "-map_metadata", "0",                # zachová datum natáčení apod.
            str(out_path)]
    if prof["ext"] == ".mp4":
        cmd.insert(-1, "-movflags")
        cmd.insert(-1, "+faststart")
    p = run(cmd)
    if p.returncode != 0:
        out_path.unlink(missing_ok=True)         # nenechávat poškozený výstup
        raise RuntimeError(p.stderr.strip()[-500:] or "ffmpeg selhal")


def main() -> int:
    ap = argparse.ArgumentParser(description="Kontrola a příprava videí pro střih.")
    ap.add_argument("input", type=Path, help="složka s videi (např. 01_raw)")
    ap.add_argument("--out", type=Path, help="výstupní složka (výchozí: ../02_edit vedle vstupu)")
    ap.add_argument("--fps", type=float, default=30.0, help="cílová fps projektu (výchozí 30)")
    ap.add_argument("--max-size", type=int, default=3840, help="max. delší strana v px (výchozí 3840)")
    ap.add_argument("--profile", choices=PROFILES.keys(), default="dnxhr", help="výstupní formát")
    ap.add_argument("--all", action="store_true", help="převést i soubory bez problémů (jednotný formát)")
    ap.add_argument("--recursive", action="store_true", help="procházet i podsložky")
    ap.add_argument("--deep", action="store_true", help="přesnější (pomalejší) test VFR")
    ap.add_argument("--hwaccel", action="store_true", help="dekódovat na GPU")
    ap.add_argument("--dry-run", action="store_true", help="jen report, nic nepřevádět")
    ap.add_argument("--force", action="store_true", help="přepsat existující výstupy")
    args = ap.parse_args()

    # Kontrola vstupu a nástrojů
    if not args.input.is_dir():
        print(f"Chyba: složka {args.input} neexistuje", file=sys.stderr)
        return 2
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"Chyba: {tool} není v PATH", file=sys.stderr)
            return 2
    has_zscale = " zscale " in run(["ffmpeg", "-hide_banner", "-filters"]).stdout

    out_dir = args.out or (args.input.parent / "02_edit")
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    pattern = "**/*" if args.recursive else "*"
    files = sorted(p for p in args.input.glob(pattern) if p.is_file())
    results = []

    for path in files:
        ext = path.suffix.lower()
        if ext in SKIP_EXT:
            results.append(Result(file=str(path), status="skipped",
                                  message="360°/Insta360 – exportovat v Insta360 Studio nebo app"))
            print(f"[skipped  ] {path.name}  360° originál – nejdřív export z Insta360")
            continue
        if ext not in VIDEO_EXT:
            continue
        try:
            r = analyze(path, args)
            if r.transfer in HDR_TRANSFERS and not has_zscale:
                r.message = "ffmpeg bez zscale – HDR nebude převedeno do SDR"
            needs_fix = bool(r.issues) or args.all
            out_path = out_dir / f"{path.stem}_edit{PROFILES[args.profile]['ext']}"
            if not needs_fix:
                r.status = "ok"
            elif args.dry_run:
                r.status = "would_fix"
            elif out_path.exists() and not args.force and out_path.stat().st_mtime >= path.stat().st_mtime:
                # Opakované spuštění (např. z n8n) nepřevádí znovu hotové soubory
                r.status, r.output, r.message = "fixed", str(out_path), "už převedeno dříve"
            else:
                print(f"→ převádím {path.name}: {', '.join(r.issues) or 'jednotný formát'}")
                transcode(r, out_path, args, has_zscale)
                r.status, r.output = "fixed", str(out_path)
        except Exception as e:                     # chyba jednoho souboru nezastaví zbytek
            r = Result(file=str(path), status="error", message=str(e))
        results.append(r)
        print(f"[{r.status:9}] {path.name}  {'; '.join(r.issues)}  {r.message}")

    # Report: CSV pro člověka, JSON pro n8n
    report_dir = out_dir if not args.dry_run else args.input
    with open(report_dir / "video_prep_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(Result(file="")).keys()), delimiter=";")
        w.writeheader()
        for r in results:
            row = asdict(r)
            row["issues"] = ", ".join(r.issues)
            w.writerow(row)
    (report_dir / "video_prep_report.json").write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")

    errors = sum(r.status == "error" for r in results)
    summary = {s: sum(r.status == s for r in results) for s in ("ok", "fixed", "would_fix", "skipped", "error")}
    print(f"\nHotovo: {summary}. Report: {report_dir / 'video_prep_report.csv'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
