import { Download, ExternalLink, RefreshCw, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type UpdateStatus, type UpdateTask } from "../api/client";
import { useEventListener } from "../api/events";
import { Button } from "../design-system/Button";
import { Switch } from "../design-system/Controls";
import { ProgressBar } from "../design-system/Progress";
import { useToast } from "./toast";

/**
 * New versions and missing parts (#22). Nothing is checked, downloaded or installed until a person says so:
 * the first start asks about the daily check, and every download starts from a button.
 */
export function useUpdates() {
  const { t } = useTranslation();
  const toast = useToast();
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const refresh = useCallback(() => { api.updates().then(setStatus).catch(() => {}); }, []);
  useEffect(refresh, [refresh]);
  useEventListener(["updates"], refresh);
  const act = useCallback(async (fn: () => Promise<unknown>) => {
    try {
      const result = await fn();
      if (result && typeof result === "object" && "current" in result) setStatus(result as UpdateStatus);
      else refresh();
    } catch (e) { toast(t("updates.failed"), e instanceof Error ? e.message : String(e)); }
  }, [refresh, t, toast]);
  return { status, act };
}

function TaskProgress({ task, label }: { task: UpdateTask; label: string }) {
  const { t } = useTranslation();
  if (task.state === "running") return <div className="w-48"><ProgressBar value={task.progress * 100} label={label} running /></div>;
  if (task.state === "failed") return <p className="text-xs text-[var(--error)]">{t("updates.taskFailed", { error: task.error })}</p>;
  return null;
}

/** Download, then install (installer) or switch (portable copy). */
function NewVersionActions({ status, act }: ReturnType<typeof useUpdates> & { status: UpdateStatus }) {
  const { t } = useTranslation();
  const toast = useToast();
  const latest = status.latest!;
  const install = () => act(async () => {
    const r = await api.installUpdate();
    if (r.action === "unpacked") toast(t("updates.unpacked"), r.path);
    return r;
  });
  if (!latest.package) return <p className="text-xs text-muted">{t("updates.fromSource")}</p>;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <a href={latest.url} target="_blank" rel="noreferrer"
         className="inline-flex items-center gap-1 text-[13px] text-muted underline decoration-[var(--line-strong)] underline-offset-4 hover:text-ink">
        {t("updates.whatsNew")}<ExternalLink className="size-3" aria-hidden />
      </a>
      {status.download.state === "ready"
        ? <Button size="sm" onClick={install} icon={<RotateCcw className="size-3.5" aria-hidden />}>
            {t(status.kind === "installed" ? "updates.runInstaller" : "updates.switch")}
          </Button>
        : <Button size="sm" onClick={() => act(api.downloadUpdate)} loading={status.download.state === "running"}
                  icon={<Download className="size-3.5" aria-hidden />}>{t("updates.download")}</Button>}
      <TaskProgress task={status.download} label={t("updates.downloading")} />
    </div>
  );
}

function PartRow({ name, body, task, installed, action, onAction }: {
  name: string; body: string; task: UpdateTask; installed: boolean; action: string; onAction: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
      <div className="min-w-0 flex-1">
        <p className="text-sm text-ink">{name}</p>
        <p className="mt-0.5 text-xs text-muted">{installed ? t("updates.installed") : body}</p>
      </div>
      {!installed && <>
        <TaskProgress task={task} label={name} />
        <Button size="sm" variant="secondary" onClick={onAction} loading={task.state === "running"}
                icon={<Download className="size-3.5" aria-hidden />}>{action}</Button>
      </>}
    </div>
  );
}

/** Settings: the daily check, Check now, and the parts Clipcura can restore. */
export function UpdatesSection() {
  const { t, i18n } = useTranslation();
  const updates = useUpdates();
  const { status, act } = updates;
  if (!status) return null;
  const checked = status.last_check
    ? new Date(status.last_check).toLocaleString(i18n.language, { dateStyle: "medium", timeStyle: "short" }) : null;
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink">
        Clipcura <span className="mono tabular">{status.current}</span>
        <span className="text-muted"> · {t(`about.kind.${status.kind}`)}</span>
      </p>
      <Switch checked={status.consent === true} onChange={(v) => act(() => api.updateSettings(v))}
              label={t("updates.daily")} description={t("updates.dailyHint")} />
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="secondary" onClick={() => act(api.checkUpdates)} loading={status.checking}
                icon={<RefreshCw className="size-3.5" aria-hidden />}>{t("updates.checkNow")}</Button>
        <p className="text-xs text-muted" aria-live="polite">
          {status.error ?? (status.latest ? t("updates.available", { version: status.latest.version })
            : checked ? t("updates.upToDate", { when: checked }) : t("updates.neverChecked"))}
        </p>
      </div>
      {status.latest && <NewVersionActions {...updates} status={status} />}
      <PartRow name="Microsoft Edge WebView2" body={t("updates.webview2Missing")} task={status.webview2}
               installed={status.webview2.installed} action={t("updates.installWebview2")} onAction={() => act(api.installWebview2)} />
      {status.webview2.state === "ready" && status.can_restart && (
        <Button size="sm" variant="secondary" onClick={() => act(api.restart)}>{t("updates.restart")}</Button>
      )}
      <PartRow name="FFmpeg" body={t("updates.ffmpegMissing")} task={status.ffmpeg}
               installed={status.ffmpeg.installed} action={t("updates.restoreFfmpeg")} onAction={() => act(api.restoreFfmpeg)} />
    </div>
  );
}

/** One line above every screen when something needs a decision: missing FFmpeg first, then the first-start
 *  question, then a new version, then the missing window engine. */
export function UpdateBanner() {
  const { t } = useTranslation();
  const updates = useUpdates();
  const { status, act } = updates;
  const [dismissed, setDismissed] = useState<string | null>(null);
  if (!status) return null;

  let key: string, tone: string, text: string, actions: React.ReactNode;
  if (!status.ffmpeg.installed) {
    key = "ffmpeg"; tone = "var(--error)"; text = t("updates.bannerFfmpeg");
    actions = <>
      <TaskProgress task={status.ffmpeg} label="FFmpeg" />
      <Button size="sm" onClick={() => act(api.restoreFfmpeg)} loading={status.ffmpeg.state === "running"}
              icon={<Download className="size-3.5" aria-hidden />}>{t("updates.restoreFfmpeg")}</Button>
    </>;
  } else if (status.consent === null) {
    key = "consent"; tone = "var(--accent-2)"; text = t("updates.bannerConsent");
    actions = <>
      <Button size="sm" onClick={() => act(() => api.updateSettings(true))}>{t("updates.yesDaily")}</Button>
      <Button size="sm" variant="ghost" onClick={() => act(() => api.updateSettings(false))}>{t("updates.noThanks")}</Button>
    </>;
  } else if (status.latest) {
    key = `v${status.latest.version}`; tone = "var(--accent-2)"; text = t("updates.bannerNew", { version: status.latest.version });
    actions = <NewVersionActions {...updates} status={status} />;
  } else if (!status.webview2.installed) {
    key = "webview2"; tone = "var(--human)"; text = t("updates.bannerWebview2");
    actions = <>
      <TaskProgress task={status.webview2} label="WebView2" />
      <Button size="sm" variant="secondary" onClick={() => act(api.installWebview2)} loading={status.webview2.state === "running"}
              icon={<Download className="size-3.5" aria-hidden />}>{t("updates.installWebview2")}</Button>
    </>;
  } else if (status.webview2.state === "ready" && status.can_restart) {
    key = "webview2-ready"; tone = "var(--ok)"; text = t("updates.bannerWebview2Ready");
    actions = <Button size="sm" onClick={() => act(api.restart)}>{t("updates.restart")}</Button>;
  } else return null;
  if (dismissed === key) return null;

  return (
    // Below the Help button and as wide as the screens' content, so it reads as part of the page, not chrome.
    <div role="status" className="mx-auto mb-6 mt-8 flex max-w-[980px] flex-wrap items-center gap-3 rounded-[var(--radius-control)] border border-line bg-surface px-4 py-3 pr-2 backdrop-blur"
         style={{ borderLeft: `3px solid ${tone}` }}>
      <p className="min-w-0 flex-1 text-sm text-ink">{text}</p>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
      {key !== "ffmpeg" && key !== "consent" && (
        <Button size="sm" variant="ghost" aria-label={t("updates.dismiss")} onClick={() => setDismissed(key)}
                icon={<X className="size-3.5" aria-hidden />} />
      )}
    </div>
  );
}
