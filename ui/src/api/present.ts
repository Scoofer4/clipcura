import type { TFunction } from "i18next";
import type { FileRow } from "../design-system/FileTable";
import type { FileReport, Issue, MediaInfo } from "./client";

const num = (v: unknown) => (typeof v === "number" ? v : Number(v) || 0);
const fps = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, "").replace(/\.$/, ""));

/** The measured value shown next to a finding, in the units an editor thinks in. */
export function findingValue(issue: Issue): string | undefined {
  const d = issue.data ?? {};
  switch (issue.rule_id) {
    case "vfr": {
      const r = num(d.r_fps);
      const avg = num(d.avg_fps);
      return r > 240 ? `Ø ${fps(avg)}` : `${fps(r)} → ${fps(avg)}`;
    }
    case "fps_mismatch": return `${fps(num(d.fps))} → ${fps(num(d.target_fps))}`;
    case "hdr": return d.color_transfer === "arib-std-b67" ? "HLG" : "PQ";
    case "hevc_10bit": return `${num(d.bit_depth)}-bit`;
    case "resolution": return `${num(d.width)}×${num(d.height)} → ${num(d.target_width)}×${num(d.target_height)}`;
    case "audio_rate": return `${num(d.sample_rate) / 1000} → ${num(d.target) / 1000} kHz`;
    case "rotation": return `${num(d.rotation)}°`;
    case "color_space": return String(d.color_space || d.color_primaries || "").toUpperCase().replace("BT470BG", "BT.601");
    case "loudness": return `${num(d.input_i).toFixed(1)} LUFS`;
    case "corrupt": return String(d.probe_error || d.decode_error || "").split("\n").pop()?.slice(0, 48);
    default: return undefined;
  }
}

export function findingsOf(file: FileReport, t: TFunction) {
  return file.issues.map((i) => ({
    severity: i.severity,
    label: t(`rule.${i.rule_id}.label`, { defaultValue: i.rule_id }),
    value: findingValue(i),
  }));
}

export function displaySize(m: MediaInfo): { w: number; h: number } {
  const v = m.video;
  if (!v) return { w: 0, h: 0 };
  const rotated = Math.abs(v.rotation) % 180 === 90;
  return rotated ? { w: v.height, h: v.width } : { w: v.width, h: v.height };
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export function rowOf(file: FileReport, t: TFunction): FileRow {
  const v = file.media.video;
  const a = file.media.audio;
  const { w, h } = displaySize(file.media);
  return {
    id: file.id,
    name: fileName(file.path),
    status: file.status,
    video: v ? `${v.codec.toUpperCase().replace("HEVC", "HEVC").replace("H264", "H.264")} ${v.bit_depth}-bit` : "—",
    size: v ? `${w}×${h}` : "—",
    fps: v ? `${fps(v.r_fps)} / ${fps(v.avg_fps)}` : "—",
    audio: a ? `${a.sample_rate / 1000} kHz` : t("present.noAudio"),
    portrait: h > w,
    findings: findingsOf(file, t),
  };
}

export function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${Math.round(bytes / 2 ** 20)} MB`;
  return `${Math.round(bytes / 1024)} kB`;
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`
    : `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** Inputs for the cadence instrument from a real file (deep check if run, else from the rate mismatch). */
export function cadenceOf(file: FileReport): { inputFps: number; irregularity: number } | null {
  const v = file.media.video;
  if (!v || !v.avg_fps) return null;
  const irregular = file.media.pts_irregularity ?? Math.min(1, Math.abs(v.r_fps - v.avg_fps) / Math.max(v.avg_fps, 1) * 4);
  return { inputFps: v.avg_fps, irregularity: Math.max(0, Math.min(1, irregular)) };
}
