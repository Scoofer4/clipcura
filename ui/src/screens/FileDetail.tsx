import { motion } from "framer-motion";
import { Check, Copy, Eye, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, imageUrl, type FileReport, type PlanEntry } from "../api/client";
import { cadenceOf, displaySize, fileName, findingValue, formatBytes, formatDuration } from "../api/present";
import { BeforeAfter } from "../design-system/BeforeAfter";
import { Button } from "../design-system/Button";
import { FindingChip, StatusChip } from "../design-system/Chip";
import { Segmented } from "../design-system/Controls";
import { Cadence, cadenceEffect } from "../visuals/Cadence";
import { Scene } from "../visuals/Scene";

function quote(arg: string) {
  return /[\s"]/.test(arg) ? `"${arg.replace(/"/g, '\\"')}"` : arg;
}

/** Screen 3: side panel with measured values, why each finding matters, before/after and the exact command. */
export function FileDetail({ file, scanId, onClose, gpuBusy }: {
  file: FileReport;
  scanId: string;
  onClose: () => void;
  gpuBusy: boolean;
}) {
  const { t } = useTranslation();
  const v = file.media.video;
  const a = file.media.audio;
  const { w, h } = displaySize(file.media);
  const at = Math.max(0, (file.media.duration || 2) * 0.4);
  const [before, setBefore] = useState<string | null>(null);
  const [entry, setEntry] = useState<PlanEntry | null>(null);
  const [after, setAfter] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [target, setTarget] = useState("30");
  const cadence = cadenceOf(file);
  const showCadence = cadence && file.issues.some((i) => i.rule_id === "vfr" || i.rule_id === "fps_mismatch");

  useEffect(() => {
    let url: string | null = null;
    setBefore(null); setAfter(null); setEntry(null);
    if (!v) return;
    imageUrl(`/api/files/${file.id}/thumbnail?at=${at.toFixed(2)}`).then((u) => { url = u; setBefore(u); }).catch(() => {});
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [file.id, at, v]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const preview = async () => {
    setPreparing(true);
    try {
      const plan = await api.plan(scanId, [file.id]);
      const e = plan.items[0] ?? null;
      setEntry(e);
      if (e?.item) setAfter(await imageUrl(`/api/plan-items/${e.id}/preview?at=${at.toFixed(2)}`));
    } finally {
      setPreparing(false);
    }
  };

  const command = entry?.item ? ["ffmpeg", ...entry.item.args].map(quote).join(" ") : "";
  const copy = async () => {
    await navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const rows: [string, string][] = v ? [
    [t("detail.codec"), `${v.codec} ${v.profile}, ${v.pix_fmt}`],
    [t("detail.resolution"), `${w}×${h}${v.rotation ? `  (${v.width}×${v.height}, ${v.rotation}°)` : ""}`],
    [t("detail.frameRate"), `${v.r_fps} / ${v.avg_fps}`],
    [t("detail.colour"), [v.color_primaries, v.color_transfer, v.color_space].filter(Boolean).join(" / ") || "—"],
    [t("detail.audio"), a ? `${a.codec}, ${a.sample_rate / 1000} kHz, ${a.channels} ch` : t("present.noAudio")],
    [t("detail.duration"), formatDuration(file.media.duration)],
    [t("detail.size"), formatBytes(file.media.size)],
  ] : [];

  return (
    <motion.aside
      initial={{ x: 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 40, opacity: 0 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      className="glass fixed inset-y-3 right-3 z-30 flex w-[min(560px,calc(100vw-24px))] flex-col overflow-hidden bg-solid"
      aria-label={t("detail.aria", { name: fileName(file.path) })}
    >
      <header className="flex items-start gap-3 border-b border-line p-5">
        <div className="min-w-0 flex-1">
          <h2 className="mono truncate text-[15px] text-ink" title={file.path}>{fileName(file.path)}</h2>
          <div className="mt-2"><StatusChip status={file.status} /></div>
        </div>
        <Button variant="ghost" size="sm" icon={<X className="size-4" aria-hidden />} onClick={onClose} aria-label={t("detail.close")}>
          Esc
        </Button>
      </header>

      <div className="flex-1 space-y-6 overflow-y-auto p-5">
        {file.issues.length > 0 && (
          <section>
            <h3 className="text-sm font-medium text-ink">{t("detail.findings")}</h3>
            <ul className="mt-3 space-y-3">
              {file.issues.map((i) => (
                <li key={i.rule_id} className="rounded-[var(--radius-control)] border border-line bg-surface p-3">
                  <FindingChip severity={i.severity} label={t(`rule.${i.rule_id}.label`, { defaultValue: i.rule_id })} value={findingValue(i)} />
                  <p className="mt-2 text-sm text-ink">{i.message}</p>
                  <p className="mt-1 text-xs text-muted">{t(`rule.${i.rule_id}.why`, { defaultValue: "" })}</p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {v && (
          <section>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-ink">{t("detail.preview")}</h3>
              {file.status === "fixable" && !after && (
                <Button size="sm" icon={<Eye className="size-4" aria-hidden />} loading={preparing} onClick={preview}>
                  {t("detail.previewFix")}
                </Button>
              )}
            </div>
            <div className="mt-3">
              {before && after ? <BeforeAfter before={before} after={after} aspect={w / h || 16 / 9} />
                : before ? <img src={before} alt={t("detail.before")} className="w-full rounded-[var(--radius-control)] border border-line" />
                : <div className="aspect-video animate-pulse rounded-[var(--radius-control)] bg-surface" />}
            </div>
            {entry && !entry.item && <p className="mt-2 text-xs text-human">{entry.reason}</p>}
          </section>
        )}

        {showCadence && cadence && (
          <section>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-ink">{t("ks.s3")}</h3>
              <Segmented label={t("cadence.target")} value={target} onChange={setTarget}
                         options={["24", "25", "30", "60"].map((x) => ({ value: x, label: x }))} />
            </div>
            <Scene label={t("cadence.aria")} paused={gpuBusy} className="mt-2 h-[170px]" camera={{ position: [-4.5, 1.7, 5.3], fov: 36 }}>
              <Cadence inputFps={cadence.inputFps} irregularity={cadence.irregularity} targetFps={Number(target)} />
            </Scene>
            {(() => {
              const fx = cadenceEffect(cadence.inputFps, Number(target));
              return <p className="text-xs text-muted">{t(`cadence.${fx.kind}`, { count: fx.perSecond })} {fx.uneven ? t("cadence.uneven") : t("cadence.even")}</p>;
            })()}
          </section>
        )}

        {rows.length > 0 && (
          <section>
            <h3 className="text-sm font-medium text-ink">{t("detail.values")}</h3>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              {rows.map(([k, val]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k}</dt>
                  <dd className="mono tabular truncate text-[13px] text-ink">{val}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {command && (
          <section>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-ink">{t("detail.command")}</h3>
              <Button size="sm" variant="ghost" icon={copied ? <Check className="size-4" /> : <Copy className="size-4" />} onClick={copy}>
                {copied ? t("detail.copied") : t("detail.copy")}
              </Button>
            </div>
            <pre className="mono mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-[var(--radius-control)] border border-line bg-surface p-3 text-[11.5px] leading-5 text-muted">
              {command}
            </pre>
            {entry?.item && <p className="mono mt-2 truncate text-xs text-faint" title={entry.item.output}>→ {entry.item.output}</p>}
          </section>
        )}
      </div>
    </motion.aside>
  );
}
