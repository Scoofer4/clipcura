import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bot, Play, Pause, Square, Wand2, ArrowDownUp, CircleAlert } from "lucide-react";
import { Button } from "../design-system/Button";
import { AiBadge, FindingChip, StatusChip, type FileStatus } from "../design-system/Chip";
import { DropZone } from "../design-system/DropZone";
import { FileTable, type FileRow } from "../design-system/FileTable";
import { Hud, type SystemView } from "../design-system/Hud";
import { LOGO_CONCEPTS, LogoMark, Lockup, type LogoConcept } from "../design-system/Logo";
import { Tilt } from "../design-system/Motion";
import { Panel, StatCard } from "../design-system/Panel";
import { JobCard, ProgressBar } from "../design-system/Progress";
import { LiveToast, Modal, Segmented, Switch, ToastBody, ToastProvider, ToastViewport } from "../design-system/Controls";
import { useAppearance } from "../design-system/theme";
import { setLanguage, type Language } from "../i18n";
import { Cadence, cadenceEffect } from "../visuals/Cadence";
import { Scene } from "../visuals/Scene";

/* Sample data mirrors the owner's real test clips (names made generic: this repository is public). */
function useRows(): FileRow[] {
  const { t } = useTranslation();
  return useMemo(() => [
    { id: 1, name: "20261031_194820.mp4", status: "fixable", video: "HEVC 8-bit", size: "2160×3840", fps: "60 / 58.26",
      audio: "48 kHz", portrait: true, findings: [
        { severity: "error", label: t("finding.vfr"), value: "60 → 58.26" },
        { severity: "warning", label: t("finding.rotation"), value: "−90°" },
        { severity: "info", label: t("finding.fps"), value: "60 → 30" }] },
    { id: 2, name: "Screen_Recording_20261031_212841_Chrome.mp4", status: "fixable", video: "H.264 8-bit", size: "1080×2340",
      fps: "90000 / 55.85", audio: "48 kHz", portrait: true, findings: [
        { severity: "error", label: t("finding.vfr"), value: "Ø 55.85" },
        { severity: "warning", label: t("finding.fps"), value: "55.85 → 30" },
        { severity: "info", label: t("finding.colour"), value: "BT.601" }] },
    { id: 3, name: "Screen_Recording_20261031_232940_Chrome.mp4", status: "fixable", video: "H.264 8-bit", size: "1080×2340",
      fps: "90000 / 65.43", audio: "48 kHz", portrait: true, findings: [
        { severity: "error", label: t("finding.vfr"), value: "Ø 65.43" },
        { severity: "warning", label: t("finding.fps"), value: "65.43 → 30" }] },
    { id: 4, name: "C0042.MP4", status: "ok", video: "H.264 8-bit", size: "3840×2160", fps: "30 / 30", audio: "48 kHz",
      portrait: false, findings: [] },
    { id: 5, name: "VID_20261101_0012.insv", status: "needs_human", video: "—", size: "5760×2880", fps: "—", audio: "—",
      portrait: false, findings: [{ severity: "warning", label: t("finding.insv") }] },
    { id: 6, name: "export_final_v2.mov", status: "error", video: "—", size: "—", fps: "—", audio: "—", portrait: false,
      findings: [{ severity: "error", label: t("finding.corrupt"), value: "moov atom not found" }] },
  ], [t]);
}

const CADENCE: Record<number, { inputFps: number; irregularity: number }> = {
  1: { inputFps: 58.26, irregularity: 0.35 },
  2: { inputFps: 55.85, irregularity: 0.9 },
  3: { inputFps: 65.43, irregularity: 1 },
};

const SYSTEM: SystemView = {
  backend: "NVIDIA CUDA", gpu: "GeForce GTX 1650 Max-Q, driver 621.01", gpuLoad: 0, vramUsedMb: 410,
  vramTotalMb: 4096, diskFreeGb: 326, diskPath: "D:\\", paths: { decode: "cuda", scale: "cpu", tonemap: "libplacebo" },
};

function SectionTitle({ title, intro }: { title: string; intro?: string }) {
  return (
    <header className="mb-4 max-w-[70ch]">
      <h2 className="text-xl font-semibold tracking-tight text-ink">{title}</h2>
      {intro && <p className="mt-1 text-sm text-muted">{intro}</p>}
    </header>
  );
}

/* ---------- job simulation: a live, controllable stand-in for the worker until screens hook up the API ---- */
interface SimJob { running: boolean; frames: number; total: number; fps: number; history: number[]; done: boolean }
const TOTAL_FRAMES = 6366; // 212.2 s screen recording at 30 fps

function useJobSimulation(onDone: () => void) {
  const [job, setJob] = useState<SimJob>({ running: false, frames: 1480, total: TOTAL_FRAMES, fps: 66, history: [58, 61, 66, 64, 70, 68, 66], done: false });
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    if (!job.running) return;
    const id = setInterval(() => {
      setJob((j) => {
        const fps = Math.max(30, Math.min(90, j.fps + (Math.random() - 0.5) * 12));
        // Demo runs 8x faster than real time so the full cycle fits a review session.
        const frames = Math.min(j.total, j.frames + fps * 0.5 * 8);
        const done = frames >= j.total;
        if (done) setTimeout(() => doneRef.current(), 0);
        return { ...j, fps, frames, done, running: !done, history: [...j.history.slice(-23), fps] };
      });
    }, 500);
    return () => clearInterval(id);
  }, [job.running]);
  return {
    job,
    start: () => setJob((j) => ({ ...j, running: true, done: false, frames: j.done ? 0 : j.frames })),
    pause: () => setJob((j) => ({ ...j, running: false })),
    cancel: () => setJob((j) => ({ ...j, running: false, frames: 0, done: false })),
  };
}

/* ---------- contrast check for the token table ---------- */
function rgbOf(cssVar: string): [number, number, number] {
  const probe = document.createElement("span");
  probe.style.color = `var(${cssVar})`;
  document.body.appendChild(probe);
  const m = getComputedStyle(probe).color.match(/[\d.]+/g) ?? ["0", "0", "0"];
  probe.remove();
  return [Number(m[0]), Number(m[1]), Number(m[2])];
}
function luminance([r, g, b]: [number, number, number]) {
  const c = [r, g, b].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
function contrast(a: string, b: string) {
  const [l1, l2] = [luminance(rgbOf(a)), luminance(rgbOf(b))].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

const SWATCHES = ["--text", "--text-muted", "--text-faint", "--ok", "--fixable", "--human", "--error", "--info", "--accent-2"];

export function KitchenSink() {
  const { t, i18n } = useTranslation();
  const appearance = useAppearance();
  const rows = useRows();
  const [filter, setFilter] = useState<FileStatus | null>(null);
  const [sorted, setSorted] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set([2]));
  const [focusFile, setFocusFile] = useState(2);
  const [targetFps, setTargetFps] = useState("30");
  const [toast, setToast] = useState<{ title: string; description?: string } | null>(null);
  const [modal, setModal] = useState(false);
  const [aiState, setAiState] = useState<"waiting" | "approved" | "rejected">("waiting");
  const [profile, setProfile] = useState("social-30");
  const [dragPreview, setDragPreview] = useState(false);
  const [contrasts, setContrasts] = useState<Record<string, [number, number]>>({});

  const sim = useJobSimulation(() => setToast({ title: t("toast.converted"), description: "Screen_Recording_…_212841_edit.mov" }));
  const gpuBusy = sim.job.running;

  const counts = useMemo(() => {
    const c: Record<FileStatus, number> = { ok: 0, fixable: 0, needs_human: 0, error: 0 };
    rows.forEach((r) => c[r.status]++);
    return c;
  }, [rows]);

  const order: FileStatus[] = ["error", "needs_human", "fixable", "ok"];
  const visible = useMemo(() => {
    const list = filter ? rows.filter((r) => r.status === filter) : rows;
    return sorted ? [...list].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status)) : list;
  }, [rows, filter, sorted]);

  const fixable = [...selected].filter((id) => rows.find((r) => r.id === id)?.status === "fixable");
  const fixSelected = useCallback(() => {
    if (!fixable.length) return;
    setToast({ title: t("toast.queued", { count: fixable.length }), description: t("toast.queuedHint") });
    sim.start();
  }, [fixable.length, sim, t]);

  // F = fix selected (CLAUDE.md §9), ignored while typing in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input, textarea, [contenteditable]");
      if (!typing && e.key.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey) fixSelected();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fixSelected]);

  useEffect(() => {
    const id = requestAnimationFrame(() => {
      const next: Record<string, [number, number]> = {};
      SWATCHES.forEach((s) => (next[s] = [contrast(s, "--bg"), contrast(s, "--surface-solid")]));
      setContrasts(next);
    });
    return () => cancelAnimationFrame(id);
  }, [appearance.theme, appearance.accent]);

  const cadence = CADENCE[focusFile] ?? CADENCE[2];
  const effect = cadenceEffect(cadence.inputFps, Number(targetFps));
  const toggle = (id: number) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  return (
    <ToastProvider swipeDirection="right">
      <div className="mx-auto max-w-[1280px] px-6 pb-24 pt-8 md:px-10">
        {/* ---------- top bar: identity + appearance controls (the settings screen will reuse them) ---------- */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Lockup concept="viewfinder" size={34} />
          <div className="flex flex-wrap items-center gap-3">
            <Segmented label={t("settings.theme")} value={appearance.theme} onChange={appearance.setTheme}
                       options={[{ value: "dark", label: t("settings.dark") }, { value: "light", label: t("settings.light") }]} />
            <Segmented label={t("settings.accent")} value={appearance.accent} onChange={appearance.setAccent}
                       options={[{ value: "brand", label: t("settings.brand") }, { value: "aurora", label: t("settings.aurora") }]} />
            <Segmented label={t("settings.language")} value={i18n.language as Language} onChange={setLanguage}
                       options={[{ value: "en", label: "EN" }, { value: "cs", label: "CS" }]} />
          </div>
        </div>

        <div className="mt-10 max-w-[70ch]">
          <h1 className="text-[40px] font-semibold leading-[1.05] tracking-[-0.03em] text-ink">{t("ks.title")}</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-muted">{t("ks.intro")}</p>
        </div>

        {/* ---------- screen 1: drop zone + HUD ---------- */}
        <section className="mt-12">
          <SectionTitle title={t("ks.s1")} intro={t("ks.s1Intro")} />
          <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
            <DropZone gpuBusy={gpuBusy} forceActive={dragPreview}
                      onFiles={(files) => setToast({ title: t("toast.received", { count: files.length }), description: files[0]?.name })} />
            <div className="flex flex-col gap-4">
              <Hud system={{ ...SYSTEM, gpuLoad: gpuBusy ? 63 : 4, vramUsedMb: gpuBusy ? 1630 : 410 }} />
              <Panel className="p-4">
                <div className="mb-2 text-sm text-ink">{t("profile.label")}</div>
                <Segmented label={t("profile.label")} value={profile} onChange={setProfile} options={[
                  { value: "social-30", label: "Social 30", hint: t("profile.social") },
                  { value: "ipad-light", label: "iPad", hint: t("profile.ipad") },
                  { value: "hero-10bit", label: "Hero", hint: t("profile.hero") },
                ]} />
                <p className="mt-2 text-xs text-faint">{t(`profile.${profile === "social-30" ? "social" : profile === "ipad-light" ? "ipad" : "hero"}`)}</p>
                <div className="mt-4 border-t border-line pt-3">
                  <Switch checked={dragPreview} onChange={setDragPreview} label={t("ks.previewDrag")} description={t("ks.previewDragHint")} />
                </div>
              </Panel>
            </div>
          </div>
        </section>

        {/* ---------- screen 2: scan result ---------- */}
        <section className="mt-14">
          <SectionTitle title={t("ks.s2")} intro={t("ks.s2Intro")} />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {(["ok", "fixable", "needs_human", "error"] as FileStatus[]).map((s) => (
              <Tilt key={s}>
                <StatCard status={s} count={counts[s]} label={t(`status.${s}`)} hint={t(`statusHint.${s}`)}
                          active={filter === s} onClick={() => setFilter((f) => (f === s ? null : s))} />
              </Tilt>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="primary" icon={<Wand2 className="size-4" aria-hidden />} kbd="F"
                    disabled={!fixable.length} onClick={fixSelected}>
              {t("table.fixSelected", { count: fixable.length })}
            </Button>
            <Button variant="secondary" onClick={() => setSelected(new Set(rows.filter((r) => r.status === "fixable").map((r) => r.id)))}>
              {t("table.selectFixable")}
            </Button>
            <Button variant="ghost" icon={<ArrowDownUp className="size-4" aria-hidden />} aria-pressed={sorted} onClick={() => setSorted((v) => !v)}>
              {t("table.sortByStatus")}
            </Button>
            <span className="ml-auto text-xs text-faint">{t("table.estimate", { size: "8.9 GB", time: "3 min" })}</span>
          </div>
          <div className="mt-3">
            <FileTable rows={visible} selected={selected} onToggle={toggle}
                       onOpen={(id) => { setFocusFile(id); document.getElementById("cadence")?.scrollIntoView({ behavior: "smooth" }); }} />
          </div>
          <p className="mt-2 text-xs text-faint">{t("table.keys")}</p>
        </section>

        {/* ---------- screen 3 (part): cadence instrument ---------- */}
        <section id="cadence" className="mt-14 scroll-mt-6">
          <SectionTitle title={t("ks.s3")} intro={t("ks.s3Intro")} />
          <Panel className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
              <span className="mono truncate text-[13px] text-ink">{rows.find((r) => r.id === focusFile)?.name}</span>
              <span className="ml-auto text-xs text-muted">{t("cadence.target")}</span>
              <Segmented label={t("cadence.target")} value={targetFps} onChange={setTargetFps}
                         options={["24", "25", "30", "60"].map((v) => ({ value: v, label: `${v} fps` }))} />
            </div>
            <Scene label={t("cadence.aria")} paused={gpuBusy} className="h-[260px]"
                   camera={{ position: [-4.5, 1.7, 5.3], fov: 36 }}
                   overlay={
                     <>
                       <div className="pointer-events-none absolute bottom-4 left-5 text-xs">
                         <div className="text-muted">{t("cadence.input")}</div>
                         <div className="mono tabular text-ink">{t("cadence.inputValue", { fps: cadence.inputFps })}</div>
                       </div>
                       <div className="pointer-events-none absolute bottom-4 right-5 text-right text-xs">
                         <div className="text-muted">{t("cadence.output")}</div>
                         <div className="mono tabular text-ink">{t("cadence.outputValue", { fps: targetFps })}</div>
                       </div>
                     </>
                   }>
              <Cadence inputFps={cadence.inputFps} irregularity={cadence.irregularity} targetFps={Number(targetFps)} />
            </Scene>
            <div className="flex items-start gap-3 border-t border-line px-5 py-4 text-sm">
              {effect.uneven && <CircleAlert className="mt-0.5 size-4 shrink-0 text-fixable" aria-hidden />}
              <p className="text-muted">
                <span className="text-ink">{t(`cadence.${effect.kind}`, { count: effect.perSecond, fps: targetFps })}</span>{" "}
                {effect.uneven ? t("cadence.uneven") : t("cadence.even")}
              </p>
            </div>
          </Panel>
        </section>

        {/* ---------- screens 4 + 5: jobs and AI approvals ---------- */}
        <section className="mt-14 grid gap-4 lg:grid-cols-2">
          <div>
            <SectionTitle title={t("ks.s4")} intro={t("ks.s4Intro")} />
            <JobCard
              job={{ name: "Screen_Recording_20261031_212841_Chrome.mp4", percent: (sim.job.frames / sim.job.total) * 100,
                     fps: sim.job.fps, etaSeconds: ((sim.job.total - sim.job.frames) / sim.job.fps) / 8,
                     path: "decode cuda, DNxHR HQ, 30 fps", speedHistory: sim.job.history, byAi: aiState === "approved" }}
              onCancel={sim.cancel}
            />
            <Panel className="mt-3 overflow-hidden">
              <Scene label={t("cadence.jobAria")} className="h-[150px]" camera={{ position: [-4.5, 1.7, 5.3], fov: 36 }}
                     overlay={<div className="mono tabular pointer-events-none absolute right-4 top-3 text-xs text-muted">
                       {t("job.frames", { done: Math.round(sim.job.frames).toLocaleString(i18n.language), total: sim.job.total.toLocaleString(i18n.language) })}
                     </div>}>
                <Cadence inputFps={55.85} irregularity={0.9} targetFps={30} processedFrames={sim.job.frames} />
              </Scene>
              <div className="flex items-center gap-2 border-t border-line px-4 py-3">
                {sim.job.running
                  ? <Button size="sm" icon={<Pause className="size-4" aria-hidden />} onClick={sim.pause}>{t("job.pause")}</Button>
                  : <Button size="sm" variant="primary" icon={<Play className="size-4" aria-hidden />} onClick={sim.start}>{t("job.start")}</Button>}
                <Button size="sm" variant="ghost" icon={<Square className="size-4" aria-hidden />} onClick={sim.cancel}>{t("job.cancel")}</Button>
                <span className="ml-auto text-xs text-faint">{gpuBusy ? t("job.gpuBusy") : t("job.gpuIdle")}</span>
              </div>
            </Panel>
          </div>
          <div>
            <SectionTitle title={t("ks.s5")} intro={t("ks.s5Intro")} />
            <Panel className="relative overflow-hidden p-5" as="article">
              <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: "var(--accent-gradient)" }} aria-hidden />
              <div className="flex items-center gap-2">
                <Bot className="size-5 text-muted" aria-hidden />
                <h3 className="text-sm font-medium text-ink">{t("ai.request")}</h3>
                <AiBadge />
                <span className="mono ml-auto text-xs text-faint">20:06:30</span>
              </div>
              <p className="mt-3 text-sm text-muted">{t("ai.summary")}</p>
              <ul className="mono mt-3 space-y-1 text-[13px] text-ink">
                <li>Screen_Recording_20261031_212841_Chrome.mp4</li>
                <li>Screen_Recording_20261031_232940_Chrome.mp4</li>
                <li>20261031_194820.mp4</li>
              </ul>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <FindingChip severity="info" label={t("ai.output")} value="..\02_edit" />
                <FindingChip severity="info" label={t("ai.space")} value="13.5 GB" />
              </div>
              <div className="mt-5 flex items-center gap-2">
                {aiState === "waiting" ? (
                  <>
                    <Button variant="primary" onClick={() => { setAiState("approved"); setToast({ title: t("toast.approved") }); }}>{t("ai.approve")}</Button>
                    <Button variant="danger" onClick={() => { setAiState("rejected"); setToast({ title: t("toast.rejected") }); }}>{t("ai.reject")}</Button>
                    <Button variant="ghost" onClick={() => setModal(true)}>{t("ai.details")}</Button>
                  </>
                ) : (
                  <>
                    <StatusChip status={aiState === "approved" ? "ok" : "error"} />
                    <span className="text-sm text-muted">{t(`ai.${aiState}`)}</span>
                    <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setAiState("waiting")}>{t("ai.reset")}</Button>
                  </>
                )}
              </div>
            </Panel>
            <div className="mt-3 glass w-full max-w-[380px] p-4">
              <ToastBody title={t("toast.converted")} description="Screen_Recording_…_212841_edit.mov" />
            </div>
          </div>
        </section>

        {/* ---------- foundations ---------- */}
        <section className="mt-16">
          <SectionTitle title={t("ks.components")} />
          <Panel className="grid gap-6 p-6 md:grid-cols-2">
            <div>
              <div className="mb-3 text-sm text-muted">{t("ks.buttons")}</div>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="primary">{t("ks.btnPrimary")}</Button>
                <Button>{t("ks.btnSecondary")}</Button>
                <Button variant="ghost">{t("ks.btnGhost")}</Button>
                <Button variant="danger">{t("ks.btnDanger")}</Button>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button variant="primary" size="sm">{t("ks.small")}</Button>
                <Button variant="primary" size="lg">{t("ks.large")}</Button>
                <Button variant="primary" loading>{t("ks.loading")}</Button>
                <Button variant="primary" disabled>{t("ks.disabled")}</Button>
              </div>
            </div>
            <div>
              <div className="mb-3 text-sm text-muted">{t("ks.chips")}</div>
              <div className="flex flex-wrap gap-2">
                {(["ok", "fixable", "needs_human", "error"] as FileStatus[]).map((s) => <StatusChip key={s} status={s} />)}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <FindingChip severity="error" label={t("finding.vfr")} value="60 → 58.26" />
                <FindingChip severity="warning" label={t("finding.hdr")} value="HLG" />
                <FindingChip severity="info" label={t("finding.audio")} value="44.1 → 48 kHz" />
              </div>
            </div>
            <div>
              <div className="mb-3 text-sm text-muted">{t("ks.progress")}</div>
              <ProgressBar value={42} label={t("ks.progress")} />
              <div className="mt-4"><ProgressBar value={78} running label={t("ks.progress")} /></div>
            </div>
            <div className="space-y-4">
              <Switch checked={appearance.motion === "full"} onChange={(v) => appearance.setMotion(v ? "full" : "reduced")}
                      label={t("settings.motion")} description={t("settings.motionHint")} />
              <Button onClick={() => setModal(true)}>{t("ks.openModal")}</Button>
              <Button onClick={() => setToast({ title: t("toast.sample"), description: "C0042.MP4" })}>{t("ks.showToast")}</Button>
            </div>
          </Panel>
        </section>

        <section className="mt-12 grid gap-4 lg:grid-cols-[1.3fr_1fr]">
          <Panel className="p-6">
            <SectionTitle title={t("ks.colours")} intro={t("ks.coloursIntro")} />
            <table className="w-full text-sm">
              <thead><tr className="text-xs text-faint"><th className="pb-2 text-left font-normal">{t("ks.token")}</th>
                <th className="pb-2 text-right font-normal">{t("ks.onBg")}</th><th className="pb-2 text-right font-normal">{t("ks.onSurface")}</th></tr></thead>
              <tbody>
                {SWATCHES.map((s) => {
                  const [bg, surf] = contrasts[s] ?? [0, 0];
                  return (
                    <tr key={s} className="border-t border-line">
                      <td className="py-2"><span className="mr-2 inline-block size-3 rounded-full align-middle" style={{ background: `var(${s})` }} />
                        <span className="mono text-[13px] text-ink">{s}</span></td>
                      <td className={`mono tabular py-2 text-right ${bg >= 4.5 ? "text-ink" : "text-fixable"}`}>{bg.toFixed(1)}</td>
                      <td className={`mono tabular py-2 text-right ${surf >= 4.5 ? "text-ink" : "text-fixable"}`}>{surf.toFixed(1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
          <Panel className="p-6">
            <SectionTitle title={t("ks.type")} />
            <div className="space-y-2">
              <div className="text-[40px] font-semibold leading-none tracking-[-0.03em] text-ink">{t("ks.typeDisplay")}</div>
              <div className="text-[28px] font-semibold tracking-tight text-ink">{t("ks.typeTitle")}</div>
              <div className="text-xl font-medium text-ink">{t("ks.typeSection")}</div>
              <div className="text-[15px] text-ink">{t("ks.typeBody")}</div>
              <div className="text-[13px] text-muted">{t("ks.typeSmall")}</div>
              <div className="mono tabular text-[13px] text-ink">r_frame_rate=90000/1  avg_frame_rate=55.852  yuv420p  1080×2340</div>
            </div>
          </Panel>
        </section>

        {/* ---------- logo concepts ---------- */}
        <section className="mt-12">
          <SectionTitle title={t("ks.logo")} intro={t("ks.logoIntro")} />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {LOGO_CONCEPTS.map((c: LogoConcept) => (
              <Panel key={c} className="p-5">
                <div className="flex items-end gap-4">
                  <LogoMark concept={c} size={96} title={t(`logo.${c}`)} />
                  <div className="flex items-end gap-3 pb-1 text-ink">
                    <LogoMark concept={c} size={32} /><LogoMark concept={c} size={20} /><LogoMark concept={c} size={16} />
                  </div>
                </div>
                <div className="mt-4"><Lockup concept={c} size={28} /></div>
                <div className="mt-4 text-sm font-medium text-ink">{t(`logo.${c}`)}</div>
                <p className="mt-1 text-xs text-muted">{t(`logo.${c}Why`)}</p>
              </Panel>
            ))}
          </div>
        </section>
      </div>

      <Modal open={modal} onOpenChange={setModal} title={t("ai.modalTitle")} description={t("ai.modalBody")}
             footer={<><Button variant="ghost" onClick={() => setModal(false)}>{t("ai.close")}</Button>
               <Button variant="primary" onClick={() => { setModal(false); setAiState("approved"); }}>{t("ai.approve")}</Button></>}>
        <pre className="mono overflow-x-auto rounded-[var(--radius-control)] border border-line bg-surface p-3 text-xs text-muted">
{`ffmpeg -hwaccel cuda -i Screen_Recording_…_212841_Chrome.mp4
  -vf zscale=m=709:t=709:p=709:r=tv,fps=fps=30,setparams=…,format=yuv422p
  -af aresample=async=1:first_pts=0 -c:v dnxhd -profile:v dnxhr_hq
  -c:a pcm_s16le -fps_mode cfr -f mov …_212841_Chrome_edit.mov`}
        </pre>
      </Modal>
      {toast && <LiveToast open onOpenChange={(o) => !o && setToast(null)} title={toast.title} description={toast.description} />}
      <ToastViewport />
    </ToastProvider>
  );
}
