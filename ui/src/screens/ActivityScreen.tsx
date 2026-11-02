import { Bot, Check, CircleCheck, FileSearch, ListChecks, Play, User, Workflow, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type AuditEntry, type Job } from "../api/client";
import { useEventListener } from "../api/events";
import { fileName } from "../api/present";
import { useToast } from "../app/toast";
import { Button } from "../design-system/Button";
import { AiBadge } from "../design-system/Chip";
import { Segmented } from "../design-system/Controls";
import { Panel } from "../design-system/Panel";

const actionIcon: Record<string, typeof Bot> = {
  scan: FileSearch, plan: ListChecks, request_apply: Play, apply: Play, approve: Check, reject: X,
  job_finished: CircleCheck, cancel: X,
};
const actorIcon = { ai: Bot, human: User, n8n: Workflow } as const;

/** Screen 5: what assistants did over MCP, and the requests waiting for a human decision. */
export function ActivityScreen() {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [waiting, setWaiting] = useState<Job[]>([]);
  const [who, setWho] = useState<"all" | "ai" | "human" | "n8n">("all");

  const refresh = () => {
    api.audit(150).then(setEntries).catch(() => {});
    api.jobs(100).then((j) => setWaiting(j.filter((x) => x.status === "awaiting_approval"))).catch(() => {});
  };
  useEffect(refresh, []);
  useEventListener(["audit", "job.status"], refresh);

  const decide = async (jobs: Job[], approve: boolean) => {
    for (const j of jobs) {
      try { await (approve ? api.approve(j.id) : api.reject(j.id)); } catch { /* already decided elsewhere */ }
    }
    toast(approve ? t("toast.approved") : t("toast.rejected"), t("activity.decided", { count: jobs.length }));
    refresh();
  };

  const shown = useMemo(() => entries.filter((e) => who === "all" || e.actor === who), [entries, who]);
  const time = (ts: string) => new Date(ts).toLocaleTimeString(i18n.language, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return (
    <div className="mx-auto max-w-[980px]">
      <h1 className="text-[28px] font-semibold tracking-tight text-ink">{t("nav.activity")}</h1>
      <p className="mt-1 text-sm text-muted">{t("activity.intro")}</p>

      {waiting.length > 0 && (
        <Panel className="relative mt-6 overflow-hidden p-5" as="article">
          <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: "var(--accent-gradient)" }} aria-hidden />
          <div className="flex flex-wrap items-center gap-2">
            <Bot className="size-5 text-muted" aria-hidden />
            <h2 className="text-sm font-medium text-ink">{t("activity.waiting", { count: waiting.length })}</h2>
            <AiBadge />
          </div>
          <p className="mt-2 text-sm text-muted">{t("activity.waitingBody")}</p>
          <ul className="mt-3 space-y-2">
            {waiting.map((j) => (
              <li key={j.id} className="flex items-center gap-3 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="mono truncate text-[13px] text-ink">{fileName(j.source ?? "")}</div>
                  <div className="mono truncate text-xs text-faint">→ {j.output}</div>
                </div>
                <Button size="sm" variant="primary" onClick={() => decide([j], true)}>{t("ai.approve")}</Button>
                <Button size="sm" variant="danger" onClick={() => decide([j], false)}>{t("ai.reject")}</Button>
              </li>
            ))}
          </ul>
          {waiting.length > 1 && (
            <div className="mt-4 flex gap-2">
              <Button variant="primary" onClick={() => decide(waiting, true)}>{t("activity.approveAll")}</Button>
              <Button variant="danger" onClick={() => decide(waiting, false)}>{t("activity.rejectAll")}</Button>
            </div>
          )}
        </Panel>
      )}

      <section className="mt-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">{t("activity.timeline")}</h2>
          <Segmented label={t("activity.filter")} value={who} onChange={setWho} options={[
            { value: "all", label: t("activity.all") }, { value: "ai", label: "AI" },
            { value: "human", label: t("activity.human") }, { value: "n8n", label: "n8n" },
          ]} />
        </div>
        {shown.length === 0 ? (
          <p className="mt-4 text-sm text-faint">{t("activity.empty")}</p>
        ) : (
          <ol className="relative mt-4 space-y-1 border-l border-line pl-5">
            {shown.map((e) => {
              const Icon = actionIcon[e.action] ?? ListChecks;
              const Actor = actorIcon[e.actor as keyof typeof actorIcon] ?? User;
              return (
                <li key={e.id} className="relative flex items-start gap-3 py-1.5">
                  <span className="absolute -left-[27px] top-2.5 size-3 rounded-full border-2 border-[var(--bg)]"
                        style={{ background: e.actor === "ai" ? "var(--accent-2)" : "var(--line-strong)" }} aria-hidden />
                  <Icon className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                  <div className="min-w-0 flex-1 text-sm">
                    <span className="text-ink">{t(`activity.action.${e.action}`, { defaultValue: e.action })}</span>{" "}
                    <span className="mono text-[13px] text-muted">{fileName(e.target)}</span>
                    <span className="ml-2 text-xs text-faint">{t(`jobs.state.${e.result}`, { defaultValue: e.result })}</span>
                  </div>
                  <span className="flex shrink-0 items-center gap-1.5 text-xs text-faint">
                    <Actor className="size-3.5" aria-label={e.actor} />
                    <span className="mono tabular">{time(e.ts)}</span>
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </div>
  );
}
