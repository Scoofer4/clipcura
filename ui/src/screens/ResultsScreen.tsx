import { AnimatePresence } from "framer-motion";
import { ArrowDownUp, FolderOpen, Wand2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, imageUrl, type FileStatus, type PlanResult, type ScanResult } from "../api/client";
import { useEvents } from "../api/events";
import { fileName, formatBytes, rowOf } from "../api/present";
import { LAST_SCAN_KEY } from "../app/Shell";
import { useToast } from "../app/toast";
import { Button } from "../design-system/Button";
import { Modal } from "../design-system/Controls";
import { FileTable } from "../design-system/FileTable";
import { Tilt } from "../design-system/Motion";
import { Panel, StatCard } from "../design-system/Panel";
import { FileDetail } from "./FileDetail";

const ORDER: FileStatus[] = ["error", "needs_human", "fixable", "ok"];

/** Screen 2: what the scan found, filterable, with bulk fix. */
export function ResultsScreen() {
  const { scanId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { t } = useTranslation();
  const { jobs: live } = useEvents();
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FileStatus | null>(null);
  const [sorted, setSorted] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [planning, setPlanning] = useState(false);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    setScan(null);
    setError(null);
    api.getScan(scanId).then((s) => {
      setScan(s);
      try { localStorage.setItem(LAST_SCAN_KEY, s.scan_id); } catch { /* ignore */ }
      // Pre-select everything Clipsana can fix: the common case is "fix all of it".
      setSelected(new Set(s.files.filter((f) => f.status === "fixable").map((f) => f.id)));
    }).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [scanId]);

  // Real frames for the table, fetched one at a time so a big folder does not start dozens of ffmpeg runs.
  const [thumbs, setThumbs] = useState<Record<number, string>>({});
  useEffect(() => {
    if (!scan) return;
    let cancelled = false;
    const made: string[] = [];
    (async () => {
      for (const f of scan.files) {
        if (cancelled) break;
        if (!f.media.video || f.status === "error") continue;
        try {
          const url = await imageUrl(`/api/files/${f.id}/thumbnail?at=${(f.media.duration * 0.4).toFixed(2)}`);
          made.push(url);
          if (!cancelled) setThumbs((m) => ({ ...m, [f.id]: url }));
        } catch { /* placeholder stays */ }
      }
    })();
    return () => { cancelled = true; made.forEach((u) => URL.revokeObjectURL(u)); setThumbs({}); };
  }, [scan]);

  const rows = useMemo(() => {
    if (!scan) return [];
    const list = scan.files.filter((f) => !filter || f.status === filter);
    const ordered = sorted ? [...list].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status)) : list;
    return ordered.map((f) => ({ ...rowOf(f, t), thumb: thumbs[f.id] }));
  }, [scan, filter, sorted, t, thumbs]);

  const fixableSelected = scan ? scan.files.filter((f) => selected.has(f.id) && f.status === "fixable").map((f) => f.id) : [];

  const openFix = useCallback(async () => {
    if (!scan || !fixableSelected.length) return;
    setPlanning(true);
    try {
      setPlan(await api.plan(scan.scan_id, fixableSelected));
    } catch (e) {
      toast(t("results.planFailed"), e instanceof Error ? e.message : String(e));
    } finally {
      setPlanning(false);
    }
  }, [scan, fixableSelected, toast, t]);

  const start = async () => {
    if (!plan) return;
    setStarting(true);
    try {
      const { jobs } = await api.apply(plan.plan_id);
      toast(t("toast.queued", { count: jobs.length }), t("toast.queuedHint"));
      setPlan(null);
      navigate("/jobs");
    } catch (e) {
      toast(t("results.startFailed"), e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  // F fixes the selection (CLAUDE.md §9); ignored while typing or with a dialog open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input, textarea, [contenteditable], [role=dialog]");
      if (!typing && !plan && e.key.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey && !e.altKey) void openFix();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openFix, plan]);

  const openId = Number(params.get("file")) || null;
  const openFile = scan?.files.find((f) => f.id === openId) ?? null;
  const gpuBusy = Object.values(live).some((j) => j.status === "running");

  if (error) {
    return (
      <Panel className="mx-auto mt-10 max-w-[560px] p-8 text-center">
        <h1 className="text-lg font-semibold text-ink">{t("results.notFound")}</h1>
        <p className="mt-2 text-sm text-muted">{error}</p>
        <Button className="mt-5" variant="primary" onClick={() => navigate("/")}>{t("results.backToStart")}</Button>
      </Panel>
    );
  }
  if (!scan) return <div className="mx-auto max-w-[1180px] animate-pulse"><div className="h-8 w-64 rounded bg-surface" /><div className="mt-6 h-64 rounded-[var(--radius-panel)] bg-surface" /></div>;

  const counts: Record<FileStatus, number> = Object.assign({ ok: 0, fixable: 0, needs_human: 0, error: 0 }, scan.summary);

  return (
    <div className="mx-auto max-w-[1180px]">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[28px] font-semibold tracking-tight text-ink">{fileName(scan.root)}</h1>
          <p className="mt-1 flex gap-3 truncate text-xs text-faint">
            <span className="mono truncate">{scan.root}</span><span className="mono shrink-0">{scan.profile}</span>
          </p>
        </div>
        <Button variant="ghost" icon={<FolderOpen className="size-4" aria-hidden />} onClick={() => navigate("/")}>
          {t("results.otherFolder")}
        </Button>
      </div>

      {scan.files.length === 0 ? (
        <Panel className="mt-6 p-10 text-center">
          <h2 className="text-lg font-semibold text-ink">{t("results.emptyTitle")}</h2>
          <p className="mt-2 text-sm text-muted">{t("results.emptyBody")}</p>
        </Panel>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            {(["ok", "fixable", "needs_human", "error"] as FileStatus[]).map((s) => (
              <Tilt key={s}>
                <StatCard status={s} count={counts[s]} label={t(`status.${s}`)} hint={t(`statusHint.${s}`)}
                          active={filter === s} onClick={() => setFilter((f) => (f === s ? null : s))} />
              </Tilt>
            ))}
          </div>

          {counts.fixable === 0 && counts.needs_human === 0 && counts.error === 0 && (
            <p className="mt-4 text-sm text-ok">{t("results.allReady")}</p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="primary" icon={<Wand2 className="size-4" aria-hidden />} kbd="F" loading={planning}
                    disabled={!fixableSelected.length} onClick={openFix}>
              {t("table.fixSelected", { count: fixableSelected.length })}
            </Button>
            <Button onClick={() => setSelected(new Set(scan.files.filter((f) => f.status === "fixable").map((f) => f.id)))}>
              {t("table.selectFixable")}
            </Button>
            <Button variant="ghost" onClick={() => setSelected(new Set())}>{t("results.clearSelection")}</Button>
            <Button variant="ghost" icon={<ArrowDownUp className="size-4" aria-hidden />} aria-pressed={sorted} onClick={() => setSorted((v) => !v)}>
              {t("table.sortByStatus")}
            </Button>
          </div>

          <div className="mt-3">
            <FileTable rows={rows} selected={selected}
                       onToggle={(id) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; })}
                       onOpen={(id) => setParams({ file: String(id) })} />
          </div>
          <p className="mt-2 text-xs text-faint">{t("table.keys")}</p>
        </>
      )}

      <AnimatePresence>
        {openFile && <FileDetail key={openFile.id} file={openFile} scanId={scan.scan_id} gpuBusy={gpuBusy}
                                 onClose={() => setParams({})} />}
      </AnimatePresence>

      <Modal open={!!plan} onOpenChange={(o) => !o && setPlan(null)}
             title={t("results.confirmTitle", { count: plan?.items.filter((i) => i.status === "pending").length ?? 0 })}
             description={t("results.confirmBody")}
             footer={<>
               <Button variant="ghost" onClick={() => setPlan(null)}>{t("job.cancel")}</Button>
               <Button variant="primary" loading={starting} onClick={start}
                       disabled={!plan?.items.some((i) => i.status === "pending")}>{t("results.startConversion")}</Button>
             </>}>
        {plan && (
          <div className="space-y-3 text-sm">
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5">
              <dt className="text-muted">{t("results.write")}</dt><dd className="mono tabular text-ink">~{formatBytes(plan.est_bytes)}</dd>
              <dt className="text-muted">{t("results.into")}</dt>
              <dd className="mono truncate text-ink">{plan.items.find((i) => i.item)?.item?.output.replace(/[\\/][^\\/]+$/, "") ?? "—"}</dd>
              <dt className="text-muted">{t("results.paths")}</dt>
              <dd className="mono text-ink">{t("hud.decode")} {plan.paths.decode}, {t("hud.scale")} {plan.paths.scale}, {t("hud.tonemap")} {plan.paths.tonemap}</dd>
            </dl>
            {plan.items.filter((i) => i.status !== "pending").length > 0 && (
              <ul className="space-y-1 rounded-[var(--radius-control)] border border-line bg-surface p-3 text-xs">
                {plan.items.filter((i) => i.status !== "pending").map((i) => (
                  <li key={i.id} className="text-muted">
                    <span className="mono text-ink">{fileName(i.item?.source ?? scan.files.find((f) => f.id === i.file_id)?.path ?? "")}</span>{" "}
                    {t(`results.skip.${i.status}`, { reason: i.reason, defaultValue: i.status })}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
