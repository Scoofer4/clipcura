/**
 * Client for the local Clipcura API (same origin as the GUI).
 *
 * The bearer token arrives once in the URL fragment (#token=...): fragments are never sent to a server or
 * written to logs. It is moved to sessionStorage and removed from the address bar right away.
 */
export type FileStatus = "ok" | "fixable" | "needs_human" | "error";
export type Severity = "info" | "warning" | "error";
export type JobStatus = "awaiting_approval" | "queued" | "running" | "done" | "failed" | "cancelled" | "rejected";

export interface Issue { rule_id: string; severity: Severity; message: string; auto_fixable: boolean; data: Record<string, unknown> }
export interface VideoStream {
  codec: string; profile: string; pix_fmt: string; width: number; height: number; r_fps: number; avg_fps: number;
  color_transfer: string; color_primaries: string; color_space: string; rotation: number; bit_depth: number;
}
export interface MediaInfo {
  path: string; size: number; duration: number; container: string; video: VideoStream | null;
  audio: { codec: string; sample_rate: number; channels: number } | null;
  probe_error: string | null; decode_error: string | null; pts_irregularity: number | null;
}
export interface FileReport { id: number; path: string; status: FileStatus; media: MediaInfo; issues: Issue[] }
export interface ScanResult { scan_id: string; root: string; profile: string; files: FileReport[]; summary: Record<FileStatus, number> }
export interface RecentScan { scan_id: string; root: string; profile: string; created_at: string; actor: string; summary: Record<FileStatus, number> }
export interface PlanItem { source: string; output: string; args: string[]; fallback_args: string[]; backend: string; rule_ids: string[]; est_bytes: number; duration: number }
export interface PlanEntry { id: number; file_id: number; status: string; item: PlanItem | null; reason: string }
export interface Paths { decode: string; encode: string; scale: string; tonemap: string }
export interface PlanResult { plan_id: string; scan_id: string; backend: string; paths: Paths; items: PlanEntry[]; est_bytes: number }
export interface Job {
  id: string; status: JobStatus; progress: number; actor: string; backend: string | null; output: string;
  error: string | null; created_at: string; finished_at: string | null; source?: string; duration?: number; rule_ids?: string[];
}
export interface AuditEntry { id: number; ts: string; actor: string; action: string; target: string; result: string }
export type ProfileSource = "builtin" | "user" | "edited";
export interface Profile {
  name: string; label: string; fps: number; max_long_side: number; audio_rate: number; color?: string;
  output: { codec: string; container: "mov" | "mp4" | "mkv"; folder: string; suffix: string };
  rules: { disabled: string[]; vfr_deep_check: boolean };
  source?: ProfileSource;
}
export interface RuleInfo { id: string; title: string; standalone: boolean }
export interface AppConfig { port: number; allowed_roots: string[]; approval_mode: boolean; concurrency: { gpu: number; cpu: number }; interface: "window" | "browser" }
export interface SystemReport {
  backend: string; paths: Paths;
  system: { cpu: string; ram_total_mb: number; gpus: { name: string; vendor: string; driver: string; memory_total_mb: number | null; memory_used_mb: number | null; utilization_pct: number | null }[]; disks: { path: string; free_gb: number; total_gb: number }[] };
  ffmpeg: { version: string } | null;
}

const TOKEN_KEY = "clipcura.token";

/** Reads one value from the URL fragment and clears the fragment from the address bar. */
function takeFromFragment(name: string): string | null {
  const match = window.location.hash.match(new RegExp(`${name}=([^&]+)`));
  if (!match) return null;
  history.replaceState(null, "", window.location.pathname + window.location.search);
  return decodeURIComponent(match[1]);
}

let token = "";
export const hasToken = () => token.length > 0;
export const setToken = (t: string) => { token = t; try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* private mode */ } };

// A browser opened by Clipcura gets a one-time code (#23): the address it was started with lands in the
// browser's history, so it must not hold the key. The desktop window passes the key itself.
const loginCode = takeFromFragment("code");
const fragmentToken = loginCode ? null : takeFromFragment("token");
if (fragmentToken) setToken(fragmentToken);
else if (!loginCode) { try { token = sessionStorage.getItem(TOKEN_KEY) ?? ""; } catch { /* private mode */ } }

/** "ok" once the page has a key; "expired" when the one-time code it was opened with no longer works. */
export const login: Promise<"ok" | "expired" | "none"> = loginCode
  ? fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: loginCode }) })
      .then(async (r) => { if (!r.ok) return "expired" as const; setToken((await r.json()).token); return "ok" as const; })
      .catch(() => "expired" as const)
  : Promise.resolve(hasToken() ? "ok" : "none");

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export interface Component {
  name: string; version: string; licence: string; url: string; kind: "media" | "python" | "ui";
  source?: string; note?: string;
}

export interface About {
  name: string; version: string; licence: string; source: string;
  owner: { name: string; url: string };
  install: { kind: "installed" | "portable" | "source"; data_dir: string };
  components: Component[];
}

async function text(path: string, auth: boolean): Promise<string> {
  const res = await fetch(path, { headers: auth ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.text();
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  about: () => request<About>("GET", "/api/about"),
  /** Licence texts of the service's components and of the GUI's libraries, one after the other. */
  notices: async () =>
    (await Promise.all([text("/api/about/notices", true), text("/ui-licenses.txt", false)])).join("\n\n"),
  system: () => request<SystemReport>("GET", "/api/system"),
  profiles: () => request<Profile[]>("GET", "/api/profiles"),
  rules: () => request<RuleInfo[]>("GET", "/api/rules"),
  saveProfile: (p: Profile) => {
    const { source: _source, ...body } = p;
    return request<Profile>("PUT", `/api/profiles/${encodeURIComponent(p.name)}`, body);
  },
  deleteProfile: (name: string) => request<unknown>("DELETE", `/api/profiles/${encodeURIComponent(name)}`),
  scan: (path: string, profile: string, recursive = false) =>
    request<ScanResult>("POST", "/api/scans", { path, profile, recursive }),
  getScan: (id: string) => request<ScanResult>("GET", `/api/scans/${id}`),
  recentScans: (limit = 8) => request<RecentScan[]>("GET", `/api/scans?limit=${limit}`),
  plan: (scanId: string, fileIds?: number[]) => request<PlanResult>("POST", "/api/plans", { scan_id: scanId, file_ids: fileIds }),
  apply: (planId: string) => request<{ jobs: Job[] }>("POST", `/api/plans/${planId}/apply`),
  jobs: (limit = 50) => request<Job[]>("GET", `/api/jobs?limit=${limit}`),
  cancel: (id: string) => request<unknown>("POST", `/api/jobs/${id}/cancel`),
  approve: (id: string) => request<Job>("POST", `/api/jobs/${id}/approve`),
  reject: (id: string) => request<Job>("POST", `/api/jobs/${id}/reject`),
  audit: (limit = 100) => request<AuditEntry[]>("GET", `/api/audit?limit=${limit}`),
  config: () => request<AppConfig>("GET", "/api/config"),
  patchConfig: (patch: Partial<Pick<AppConfig, "approval_mode" | "concurrency" | "interface">>) => request<AppConfig>("PATCH", "/api/config", patch),
  addRoot: (path: string) => request<AppConfig>("POST", "/api/config/roots", { path }),
  removeRoot: (path: string) => request<AppConfig>("DELETE", "/api/config/roots", { path }),
};

/** Fetch an authenticated image (img tags cannot send the bearer header) and return an object URL. */
export async function imageUrl(path: string): Promise<string> {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return URL.createObjectURL(await res.blob());
}

export function eventsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/events?token=${encodeURIComponent(token)}`;
}
