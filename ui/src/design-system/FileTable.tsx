import { motion } from "framer-motion";
import { Check } from "lucide-react";
import type { KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { FindingChip, StatusChip, type FileStatus, type Severity } from "./Chip";

export interface FileRow {
  id: number;
  name: string;
  status: FileStatus;
  video: string;     // "HEVC 8-bit"
  size: string;      // "2160×3840"
  fps: string;       // "60 / 58.26"
  audio: string;     // "48 kHz"
  portrait: boolean;
  findings: { severity: Severity; label: string; value?: string }[];
}

/** Frame placeholder in the clip's real aspect ratio, until ffmpeg thumbnails arrive (M3b). */
function Thumb({ portrait, status }: { portrait: boolean; status: FileStatus }) {
  return (
    <div className="flex h-12 w-16 items-center justify-center" aria-hidden>
      <div
        className={`${portrait ? "h-12 w-7" : "h-9 w-16"} rounded-[5px] border border-line`}
        style={{
          background: `linear-gradient(135deg, color-mix(in srgb, var(--${status === "needs_human" ? "human" : status}) 22%, transparent), var(--surface-raised))`,
        }}
      />
    </div>
  );
}

export function FileTable({ rows, selected, onToggle, onOpen }: {
  rows: FileRow[];
  selected: Set<number>;
  onToggle: (id: number) => void;
  onOpen: (id: number) => void;
}) {
  const { t } = useTranslation();
  const onKey = (e: KeyboardEvent, id: number) => {
    if (e.key === " ") { e.preventDefault(); onToggle(id); }
    if (e.key === "Enter") onOpen(id);
  };
  return (
    <div className="glass overflow-x-auto">
      <table className="w-full min-w-[920px] border-collapse text-left text-sm">
        <caption className="sr-only">{t("table.caption")}</caption>
        <thead>
          <tr className="border-b border-line text-xs text-faint">
            <th scope="col" className="w-10 px-4 py-3 font-normal"><span className="sr-only">{t("table.select")}</span></th>
            <th scope="col" className="px-2 py-3 font-normal">{t("table.file")}</th>
            <th scope="col" className="px-3 py-3 font-normal">{t("table.status")}</th>
            <th scope="col" className="px-3 py-3 font-normal">{t("table.video")}</th>
            <th scope="col" className="px-3 py-3 font-normal">{t("table.fps")}</th>
            <th scope="col" className="px-3 py-3 font-normal">{t("table.audio")}</th>
            <th scope="col" className="px-4 py-3 font-normal">{t("table.findings")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isSelected = selected.has(r.id);
            return (
              <motion.tr
                layout
                key={r.id}
                tabIndex={0}
                aria-selected={isSelected}
                onKeyDown={(e) => onKey(e, r.id)}
                onDoubleClick={() => onOpen(r.id)}
                transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                className="cursor-default border-b border-line last:border-0 outline-none hover:bg-surface focus-visible:bg-surface focus-visible:[box-shadow:inset_2px_0_0_var(--accent-2)] aria-selected:bg-[var(--accent-soft)]"
              >
                <td className="px-4 py-2.5">
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={isSelected}
                    aria-label={t("table.selectFile", { name: r.name })}
                    tabIndex={-1}
                    onClick={() => onToggle(r.id)}
                    className={`flex size-[18px] items-center justify-center rounded-[5px] border ${isSelected ? "border-transparent [background:var(--accent-solid)] text-white" : "border-line-strong"}`}
                  >
                    {isSelected && <Check className="size-3" strokeWidth={3} aria-hidden />}
                  </button>
                </td>
                <td className="px-2 py-2.5">
                  <div className="flex items-center gap-3">
                    <Thumb portrait={r.portrait} status={r.status} />
                    <span className="mono max-w-[260px] truncate text-[13px] text-ink" title={r.name}>{r.name}</span>
                  </div>
                </td>
                <td className="px-3 py-2.5"><StatusChip status={r.status} /></td>
                <td className="mono tabular whitespace-nowrap px-3 py-2.5 text-[13px] text-muted">
                  <span className="text-ink">{r.video}</span><br />{r.size}
                </td>
                <td className="mono tabular whitespace-nowrap px-3 py-2.5 text-[13px] text-muted">{r.fps}</td>
                <td className="mono tabular whitespace-nowrap px-3 py-2.5 text-[13px] text-muted">{r.audio}</td>
                <td className="px-4 py-2.5">
                  <div className="flex flex-wrap gap-1.5">
                    {r.findings.length === 0
                      ? <span className="text-xs text-faint">{t("table.noFindings")}</span>
                      : r.findings.map((f) => <FindingChip key={f.label} {...f} />)}
                  </div>
                </td>
              </motion.tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
