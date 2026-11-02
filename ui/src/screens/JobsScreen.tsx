import { CircleCheck, CircleX, Clock, Ban } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, type Job } from "../api/client";
import { useEventListener, useEvents } from "../api/events";
import { fileName } from "../api/present";
import { useToast } from "../app/toast";
import { Button } from "../design-system/Button";
import { AiBadge } from "../design-system/Chip";
import { Panel } from "../design-system/Panel";
import { JobCard } from "../design-system/Progress";
import { Cadence } from "../visuals/Cadence";
import { Scene } from "../visuals/Scene";

const ACTIVE = new Set(["running", "queued"]);
const finishedIcon = { done: CircleCheck, failed: CircleX, cancelled: Ban, rejected: Ban } as const;

/** Screen 4: live job queue. Everything updates from the event stream, including jobs started by AI or n8n. */
export function JobsScreen() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();
  const { jobs: live } = useEvents();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = () => api.jobs(60).then((j) => { setJobs(j); setLoaded(true); }).catch(() => setLoaded(true));
  useEffect(() => { void refresh(); }, []);
  useEventListener(["job.status"], (e) => {
    void refresh();
    if (e.status === "done") toast(t("jobs.doneToast"), fileName(String(e.output ?? "")));
    if (e.status === "failed") toast(t("jobs.failedToast"), String(e.error ?? "").split("\n").pop());
  });

  const active = jobs.filter((j) => ACTIVE.has(live[j.id]?.status ?? j.status));
  const finished = jobs.filter((j) => !ACTIVE.has(live[j.id]?.status ?? j.status) && j.status !== "awaiting_approval");
  const running = active.find((j) => (live[j.id]?.status ?? j.status) === "running");

  return (
    <div className="mx-auto max-w-[1180px]">
      <h1 className="text-[28px] font-semibold tracking-tight text-ink">{t("nav.jobs")}</h1>
      <p className="mt-1 text-sm text-muted">{t("jobs.intro")}</p>

      {loaded && active.length === 0 && finished.length === 0 && (
        <Panel className="mt-6 p-10 text-center">
          <h2 className="text-lg font-semibold text-ink">{t("jobs.emptyTitle")}</h2>
          <p className="mt-2 text-sm text-muted">{t("jobs.emptyBody")}</p>
          <Button className="mt-5" variant="primary" onClick={() => navigate("/")}>{t("results.backToStart")}</Button>
        </Panel>
      )}

      {active.length > 0 && (
        <section className="mt-6 grid gap-4 lg:grid-cols-[1fr_380px]">
          <div className="space-y-3">
            {active.map((j) => {
              const l = live[j.id];
              const status = l?.status ?? j.status;
              const percent = l?.percent ?? j.progress ?? 0;
              return status === "queued" ? (
                <Panel key={j.id} className="flex items-center gap-3 p-4" as="article">
                  <Clock className="size-4 text-muted" aria-hidden />
                  <span className="mono min-w-0 flex-1 truncate text-sm text-ink">{fileName(j.source ?? "")}</span>
                  {j.actor === "ai" && <AiBadge />}
                  <span className="text-xs text-faint">{t("jobs.queued")}</span>
                  <Button size="sm" variant="ghost" onClick={() => api.cancel(j.id).then(refresh)}>{t("job.cancel")}</Button>
                </Panel>
              ) : (
                <JobCard key={j.id} onCancel={() => api.cancel(j.id).then(refresh)} job={{
                  name: fileName(j.source ?? ""), percent, fps: l?.fps ?? 0, etaSeconds: l?.etaSeconds ?? 0,
                  path: `${t("hud.decode")} ${j.backend ?? "…"}, ${(j.rule_ids ?? []).join(", ")}`,
                  speedHistory: l?.speedHistory?.length ? l.speedHistory : [0, 0], byAi: j.actor === "ai",
                }} />
              );
            })}
          </div>
          {running && (
            <Panel className="overflow-hidden">
              <Scene label={t("cadence.jobAria")} className="h-[220px]" camera={{ position: [-4.5, 1.7, 5.3], fov: 36 }}
                     overlay={<div className="mono tabular pointer-events-none absolute bottom-3 right-4 text-xs text-muted">
                       {t("job.frames", {
                         done: Math.round(((live[running.id]?.percent ?? 0) / 100) * (running.duration ?? 0) * 30).toLocaleString(),
                         total: Math.round((running.duration ?? 0) * 30).toLocaleString(),
                       })}
                     </div>}>
                <Cadence inputFps={45} irregularity={0.6} targetFps={30}
                         processedFrames={((live[running.id]?.percent ?? 0) / 100) * (running.duration ?? 0) * 30} />
              </Scene>
            </Panel>
          )}
        </section>
      )}

      {finished.length > 0 && (
        <section className="mt-10">
          <h2 className="text-base font-semibold text-ink">{t("jobs.finished")}</h2>
          <ul className="mt-3 divide-y divide-[var(--line)] glass">
            {finished.map((j) => {
              const Icon = finishedIcon[j.status as keyof typeof finishedIcon] ?? CircleX;
              const color = j.status === "done" ? "var(--ok)" : j.status === "failed" ? "var(--error)" : "var(--text-faint)";
              return (
                <li key={j.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                  <Icon className="size-4 shrink-0" style={{ color }} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="mono truncate text-ink">{fileName(j.source ?? "")}</div>
                    <div className="mono truncate text-xs text-faint">
                      {j.status === "done" ? `→ ${j.output}` : (j.error ?? "").split("\n").pop() || t(`jobs.state.${j.status}`)}
                    </div>
                  </div>
                  {j.actor === "ai" && <AiBadge />}
                  <span className="text-xs text-faint">{t(`jobs.state.${j.status}`)}</span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
