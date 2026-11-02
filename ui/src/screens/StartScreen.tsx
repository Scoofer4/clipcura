import { FolderSearch, History, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type Profile, type RecentScan, type SystemReport } from "../api/client";
import { useEventListener, useEvents } from "../api/events";
import { fileName } from "../api/present";
import { LAST_SCAN_KEY } from "../app/Shell";
import { useToast } from "../app/toast";
import { Button } from "../design-system/Button";
import { StatusChip } from "../design-system/Chip";
import { Segmented } from "../design-system/Controls";
import { DropZone } from "../design-system/DropZone";
import { Hud, type SystemView } from "../design-system/Hud";
import { Panel } from "../design-system/Panel";

const PROFILE_KEY = "clipsana.profile";

function systemView(s: SystemReport | null): SystemView | null {
  if (!s) return null;
  const gpu = s.system.gpus.find((g) => g.vendor === "nvidia") ?? s.system.gpus[0];
  const disk = s.system.disks[0];
  const label = { cuda: "NVIDIA CUDA", qsv: "Intel Quick Sync", cpu: "CPU" }[s.backend] ?? s.backend;
  return {
    backend: label,
    gpu: gpu ? `${gpu.name}${gpu.driver ? `, ${gpu.driver}` : ""}` : s.system.cpu,
    gpuLoad: gpu?.utilization_pct ?? 0,
    vramUsedMb: gpu?.memory_used_mb ?? 0,
    vramTotalMb: gpu?.memory_total_mb ?? 1,
    diskFreeGb: disk?.free_gb ?? 0,
    diskPath: disk?.path.match(/^[A-Za-z]:\\/)?.[0] ?? disk?.path ?? "",  // the drive is what matters for space
    paths: s.paths,
  };
}

/** Folder of the first dropped file. pywebview exposes real paths on dropped files; browsers never do. */
function droppedFolder(files: File[]): string | null {
  const full = (files[0] as File & { pywebviewFullPath?: string })?.pywebviewFullPath;
  if (!full) return null;
  return full.replace(/[\\/][^\\/]+$/, "");
}

export function StartScreen() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();
  const { jobs: liveJobs } = useEvents();
  const input = useRef<HTMLInputElement>(null);
  const [path, setPath] = useState("");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profile, setProfile] = useState(() => { try { return localStorage.getItem(PROFILE_KEY) ?? "social-30"; } catch { return "social-30"; } });
  const [recent, setRecent] = useState<RecentScan[]>([]);
  const [system, setSystem] = useState<SystemReport | null>(null);
  const [scanning, setScanning] = useState<{ root: string; files: number } | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);

  useEffect(() => {
    api.profiles().then(setProfiles).catch(() => {});
    api.recentScans(6).then(setRecent).catch(() => {});
    api.system().then(setSystem).catch(() => {});
  }, []);

  useEventListener(["scan.file"], () => setScanning((s) => (s ? { ...s, files: s.files + 1 } : s)));

  const chooseProfile = (p: string) => {
    setProfile(p);
    try { localStorage.setItem(PROFILE_KEY, p); } catch { /* ignore */ }
  };

  const scan = async (folder: string) => {
    const root = folder.trim().replace(/^"|"$/g, "");
    if (!root) { input.current?.focus(); return; }
    setBlocked(null);
    setScanning({ root, files: 0 });
    try {
      const result = await api.scan(root, profile);
      try { localStorage.setItem(LAST_SCAN_KEY, result.scan_id); } catch { /* ignore */ }
      navigate(`/scans/${result.scan_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setBlocked(root);
      else toast(t("start.scanFailed"), e instanceof Error ? e.message : String(e));
    } finally {
      setScanning(null);
    }
  };

  const allowAndScan = async () => {
    if (!blocked) return;
    try {
      await api.addRoot(blocked);
      toast(t("start.allowed"), blocked);
      await scan(blocked);
    } catch (e) {
      toast(t("start.allowFailed"), e instanceof Error ? e.message : String(e));
    }
  };

  const onSubmit = (e: FormEvent) => { e.preventDefault(); void scan(path); };
  const gpuBusy = Object.values(liveJobs).some((j) => j.status === "running");
  const sys = systemView(system);

  return (
    <div className="mx-auto max-w-[1180px]">
      <h1 className="text-[28px] font-semibold tracking-tight text-ink">{t("start.title")}</h1>
      <p className="mt-1 max-w-[70ch] text-sm text-muted">{t("start.intro")}</p>

      <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_300px]">
        <div className="flex flex-col gap-3">
          <DropZone gpuBusy={gpuBusy} onFiles={(files) => {
            const folder = droppedFolder(files);
            if (folder) { setPath(folder); void scan(folder); } else {
              toast(t("start.dropBrowser"), t("start.dropBrowserHint"));
              input.current?.focus();
            }
          }} />
          <form onSubmit={onSubmit} className="glass flex items-center gap-2 p-2 pl-4">
            <FolderSearch className="size-4 shrink-0 text-faint" aria-hidden />
            <label htmlFor="folder" className="sr-only">{t("start.pathLabel")}</label>
            <input id="folder" ref={input} value={path} onChange={(e) => setPath(e.target.value)}
                   placeholder={t("start.pathPlaceholder")} spellCheck={false}
                   className="mono h-10 min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:font-sans placeholder:text-faint" />
            <Button type="submit" variant="primary" loading={!!scanning}>
              {scanning ? t("start.scanningCount", { count: scanning.files }) : t("start.scan")}
            </Button>
          </form>
          {blocked && (
            <Panel className="flex flex-wrap items-center gap-3 p-4" as="div">
              <ShieldAlert className="size-5 text-human" aria-hidden />
              <div className="min-w-0 flex-1 text-sm">
                <div className="text-ink">{t("start.notAllowed")}</div>
                <div className="mono truncate text-xs text-faint">{blocked}</div>
              </div>
              <Button variant="primary" onClick={allowAndScan}>{t("start.allowAndScan")}</Button>
            </Panel>
          )}
        </div>

        <div className="flex flex-col gap-4">
          {sys ? <Hud system={sys} /> : (
            <div className="glass h-[232px] animate-pulse p-4" aria-busy="true" aria-label={t("hud.aria")}>
              <div className="h-4 w-32 rounded bg-[var(--line)]" />
              <div className="mt-6 h-2 w-full rounded bg-[var(--line)]" />
              <div className="mt-6 h-2 w-full rounded bg-[var(--line)]" />
              <div className="mt-8 h-3 w-24 rounded bg-[var(--line)]" />
            </div>
          )}
          <Panel className="p-4">
            <div className="mb-2 text-sm text-ink">{t("profile.label")}</div>
            {profiles.length > 0 && (
              <Segmented label={t("profile.label")} value={profile} onChange={chooseProfile}
                         options={profiles.map((p) => ({ value: p.name, label: p.name, hint: p.label }))} />
            )}
            <p className="mt-2 text-xs text-faint">
              {(() => {
                const p = profiles.find((x) => x.name === profile);
                return p ? t("start.profileSummary", { fps: p.fps, side: p.max_long_side, codec: p.output.codec }) : "";
              })()}
            </p>
          </Panel>
        </div>
      </div>

      <section className="mt-10">
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
          <History className="size-4 text-muted" aria-hidden />{t("start.recent")}
        </h2>
        {recent.length === 0 ? (
          <p className="mt-2 text-sm text-faint">{t("start.noRecent")}</p>
        ) : (
          <ul className="mt-3 grid gap-2 md:grid-cols-2">
            {recent.map((r) => (
              <li key={r.scan_id} className="glass flex items-center gap-2 p-2 hover:border-line-strong">
                <button type="button" onClick={() => navigate(`/scans/${r.scan_id}`)}
                        className="flex min-w-0 flex-1 items-center gap-3 rounded-[8px] p-1 text-left">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-ink">{fileName(r.root)}</div>
                    <div className="mono truncate text-xs text-faint">{r.root}</div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {(["fixable", "needs_human", "error"] as const).filter((s) => r.summary[s]).map((s) => (
                      <span key={s} className="flex items-center gap-1 text-xs text-muted"><StatusChip status={s} /><span className="tabular">{r.summary[s]}</span></span>
                    ))}
                    {!r.summary.fixable && !r.summary.needs_human && !r.summary.error && <StatusChip status="ok" />}
                  </div>
                </button>
                <Button size="sm" variant="ghost" onClick={() => { setPath(r.root); void scan(r.root); }}>
                  {t("start.rescan")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
