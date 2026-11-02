import { motion } from "framer-motion";
import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { Button } from "./Button";
import { AiBadge } from "./Chip";

export function ProgressBar({ value, label, running = false }: { value: number; label: string; running?: boolean }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value)}
      className="relative h-2 overflow-hidden rounded-full bg-[var(--line)]"
    >
      <motion.div
        className="h-full rounded-full"
        style={{ background: "var(--accent-gradient)" }}
        initial={false}
        animate={{ width: `${value}%` }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      />
      {running && (
        // A single sweep of light marks the active job; it stops under reduced motion.
        <motion.div
          className="pointer-events-none absolute inset-y-0 w-24 bg-gradient-to-r from-transparent via-white/35 to-transparent"
          initial={{ x: "-6rem" }}
          animate={{ x: "40rem" }}
          transition={{ duration: 1.8, repeat: Infinity, ease: "linear" }}
        />
      )}
    </div>
  );
}

export interface JobView {
  name: string;
  percent: number;
  fps: number;
  etaSeconds: number;
  path: string;          // e.g. "decode CUDA · DNxHR HQ"
  speedHistory: number[]; // frames per second samples for the mini chart
  byAi?: boolean;
}

function formatEta(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function JobCard({ job, onCancel }: { job: JobView; onCancel?: () => void }) {
  const { t } = useTranslation();
  const gradientId = useId();
  const data = job.speedHistory.map((fps, i) => ({ i, fps }));
  return (
    <article className="glass p-4" aria-label={t("job.aria", { name: job.name })}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-medium text-ink">{job.name}</h3>
            {job.byAi && <AiBadge />}
          </div>
          <p className="mono mt-0.5 truncate text-xs text-faint">{job.path}</p>
        </div>
        <Button variant="ghost" size="sm" icon={<X className="size-4" aria-hidden />} onClick={onCancel}>
          {t("job.cancel")}
        </Button>
      </div>

      <div className="mt-3 flex items-end gap-4">
        <div className="min-w-0 flex-1">
          <ProgressBar value={job.percent} running label={t("job.progress", { name: job.name })} />
          <dl className="mono tabular mt-2 flex gap-4 text-xs text-muted">
            <div><dt className="sr-only">{t("job.done")}</dt><dd className="text-ink">{job.percent.toFixed(1)} %</dd></div>
            <div><dt className="sr-only">{t("job.speed")}</dt><dd>{job.fps.toFixed(0)} fps</dd></div>
            <div><dt className="sr-only">{t("job.remaining")}</dt><dd>{t("job.etaShort", { eta: formatEta(job.etaSeconds) })}</dd></div>
          </dl>
        </div>
        {/* Speed over time: dips show where the clip got heavy, useful when comparing GPU and CPU. */}
        <div className="h-12 w-32 shrink-0" aria-hidden>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--accent-2)" stopOpacity={0.45} />
                  <stop offset="100%" stopColor="var(--accent-2)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <YAxis hide domain={[0, "dataMax + 10"]} />
              <Area type="monotone" dataKey="fps" stroke="var(--accent-2)" strokeWidth={1.5}
                    fill={`url(#${gradientId})`} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </article>
  );
}
