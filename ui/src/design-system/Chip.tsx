import { CircleAlert, CircleCheck, CircleX, Hand, Info, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

export type FileStatus = "ok" | "fixable" | "needs_human" | "error";
export type Severity = "info" | "warning" | "error";

const statusColor: Record<FileStatus, string> = {
  ok: "var(--ok)",
  fixable: "var(--fixable)",
  needs_human: "var(--human)",
  error: "var(--error)",
};

const statusIcon = { ok: CircleCheck, fixable: Wrench, needs_human: Hand, error: CircleX };

/** File status: colour + icon + word, so it never relies on colour alone (WCAG 1.4.1). */
export function StatusChip({ status }: { status: FileStatus }) {
  const { t } = useTranslation();
  const Icon = statusIcon[status];
  return (
    <span
      className="inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-xs font-medium"
      style={{
        color: statusColor[status],
        background: `color-mix(in srgb, ${statusColor[status]} 13%, transparent)`,
        boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${statusColor[status]} 30%, transparent)`,
      }}
    >
      <Icon className="size-3.5" aria-hidden />
      {t(`status.${status}`)}
    </span>
  );
}

const severityColor: Record<Severity, string> = { info: "var(--info)", warning: "var(--fixable)", error: "var(--error)" };
const severityIcon = { info: Info, warning: CircleAlert, error: CircleX };

/** A finding: human label plus the measured value in mono, e.g. "Variable frame rate  60 → 58.26". */
export function FindingChip({ severity, label, value }: { severity: Severity; label: string; value?: string }) {
  const Icon = severityIcon[severity];
  return (
    <span className="inline-flex h-6 items-center gap-1.5 rounded-full border border-line bg-raised pl-2 pr-2.5 text-xs text-ink">
      <Icon className="size-3.5 shrink-0" style={{ color: severityColor[severity] }} aria-hidden />
      <span>{label}</span>
      {value && <span className="mono tabular text-muted">{value}</span>}
    </span>
  );
}

/** Marks work requested by an AI assistant through MCP (screens 4 and 5). */
export function AiBadge() {
  const { t } = useTranslation();
  return (
    <span
      className="inline-flex h-5 items-center rounded-full px-2 text-[11px] font-semibold text-[var(--accent-ink)]"
      style={{ background: "var(--accent-solid)" }}
      title={t("ai.badgeTitle")}
    >
      AI
    </span>
  );
}
