import { Cpu, HardDrive, MonitorPlay } from "lucide-react";
import { useTranslation } from "react-i18next";

export interface SystemView {
  backend: string;      // "NVIDIA CUDA"
  gpu: string;
  gpuLoad: number;      // percent
  vramUsedMb: number;
  vramTotalMb: number;
  diskFreeGb: number;
  diskPath: string;
  paths: { decode: string; scale: string; tonemap: string };
}

function Meter({ value, label }: { value: number; label: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--line)]" role="meter"
         aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)}>
      <div className="h-full rounded-full" style={{ width: `${value}%`, background: "var(--accent-gradient)" }} />
    </div>
  );
}

/** Compact system HUD: what the machine will use for the next job, at a glance. */
export function Hud({ system }: { system: SystemView }) {
  const { t } = useTranslation();
  const vram = (system.vramUsedMb / system.vramTotalMb) * 100;
  return (
    <section className="glass p-4" aria-label={t("hud.aria")}>
      <div className="flex items-center gap-2 text-sm text-ink">
        <MonitorPlay className="size-4 text-muted" aria-hidden />
        <span className="font-medium">{system.backend}</span>
      </div>
      <p className="mono mt-0.5 truncate text-xs text-faint">{system.gpu}</p>

      <dl className="mt-4 grid gap-3 text-xs">
        <div>
          <div className="mb-1.5 flex justify-between text-muted">
            <dt>{t("hud.gpuLoad")}</dt>
            <dd className="mono tabular text-ink">{system.gpuLoad} %</dd>
          </div>
          <Meter value={system.gpuLoad} label={t("hud.gpuLoad")} />
        </div>
        <div>
          <div className="mb-1.5 flex justify-between text-muted">
            <dt>{t("hud.vram")}</dt>
            <dd className="mono tabular text-ink">{(system.vramUsedMb / 1024).toFixed(1)} / {(system.vramTotalMb / 1024).toFixed(0)} GB</dd>
          </div>
          <Meter value={vram} label={t("hud.vram")} />
        </div>
        <div className="flex items-center justify-between text-muted">
          <dt className="flex items-center gap-1.5"><HardDrive className="size-3.5" aria-hidden />{t("hud.freeSpace")}</dt>
          <dd className="mono tabular text-ink">{system.diskFreeGb.toFixed(0)} GB <span className="text-faint">{system.diskPath}</span></dd>
        </div>
        <div className="flex items-start justify-between gap-3 border-t border-line pt-3 text-muted">
          <dt className="flex items-center gap-1.5"><Cpu className="size-3.5" aria-hidden />{t("hud.paths")}</dt>
          <dd className="mono text-right leading-5 text-ink">
            {t("hud.decode")} {system.paths.decode}<br />
            {t("hud.scale")} {system.paths.scale}<br />
            {t("hud.tonemap")} {system.paths.tonemap}
          </dd>
        </div>
      </dl>
    </section>
  );
}
