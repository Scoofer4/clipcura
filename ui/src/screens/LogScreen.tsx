import { Copy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type LogEntry, type LogLevel } from "../api/client";
import { useEventListener } from "../api/events";
import { useToast } from "../app/toast";
import { Button } from "../design-system/Button";
import { Segmented } from "../design-system/Controls";
import { Panel } from "../design-system/Panel";

const RANK: Record<LogEntry["level"], number> = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 3 };
const MIN: Record<LogLevel, number> = { info: 1, warning: 2, error: 3 };
const TONE: Record<LogEntry["level"], string> = {
  DEBUG: "var(--text-faint)", INFO: "var(--text-muted)", WARNING: "var(--fixable)", ERROR: "var(--error)", CRITICAL: "var(--error)",
};

function asText(e: LogEntry): string {
  return `${e.ts} ${e.level} ${e.process}[${e.pid}] ${e.source}: ${e.message}${e.exc ? `\n${e.exc}` : ""}`;
}

/** The log (#26): what every part of Clipcura did and where something went wrong, live. Assistants read the
 *  same entries through MCP (get_logs). */
export function LogScreen() {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const [level, setLevel] = useState<LogLevel>("warning");
  const [query, setQuery] = useState("");
  const [text, setText] = useState("");
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [folder, setFolder] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => { const id = window.setTimeout(() => setText(query.trim()), 250); return () => window.clearTimeout(id); }, [query]);
  useEffect(() => {
    api.logs(level, text).then((r) => { setEntries(r.entries); setFolder(r.folder); setLoaded(true); }).catch(() => setLoaded(true));
  }, [level, text]);
  useEventListener(["log"], (e) => {
    const entry = e.entry as LogEntry;
    const hay = `${entry.message} ${entry.exc ?? ""}`.toLowerCase();
    if (RANK[entry.level] >= MIN[level] && (!text || hay.includes(text.toLowerCase()))) {
      setEntries((prev) => [entry, ...prev].slice(0, 500));
    }
  });

  const day = useMemo(() => new Date().toDateString(), []);
  const when = (ts: string) => {
    const d = new Date(ts);
    return d.toLocaleString(i18n.language, d.toDateString() === day
      ? { hour: "2-digit", minute: "2-digit", second: "2-digit" }
      : { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };
  const copy = async (value: string, what: string) => {
    try { await navigator.clipboard.writeText(value); toast(t("log.copied"), what); }
    catch { toast(t("log.copyFailed")); }
  };

  return (
    <div className="mx-auto max-w-[1100px]">
      <h1 className="text-[28px] font-semibold tracking-tight text-ink">{t("log.title")}</h1>
      <p className="mt-1 max-w-[75ch] text-sm text-muted">{t("log.intro")}</p>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Segmented label={t("log.level")} value={level} onChange={setLevel}
                   options={[{ value: "error", label: t("log.errors") }, { value: "warning", label: t("log.warnings") },
                             { value: "info", label: t("log.everything") }]} />
        <label htmlFor="log-search" className="sr-only">{t("log.search")}</label>
        <input id="log-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("log.search")}
               className="h-9 min-w-[220px] flex-1 rounded-[var(--radius-control)] border border-line bg-surface px-3 text-[13px] text-ink outline-none focus:border-[var(--accent-2)]" />
        <Button size="sm" variant="secondary" icon={<Copy className="size-3.5" aria-hidden />} disabled={!entries.length}
                onClick={() => copy(entries.map(asText).reverse().join("\n"), t("log.copiedCount", { count: entries.length }))}>
          {t("log.copyShown")}
        </Button>
      </div>

      <Panel className="mt-4 overflow-hidden">
        {loaded && entries.length === 0 && <p className="p-6 text-sm text-muted">{t(`log.empty.${level}`)}</p>}
        <ol aria-label={t("log.title")} aria-live="polite" className="divide-y divide-[var(--line)]">
          {entries.map((e, i) => (
            <li key={`${e.ts}-${e.pid}-${i}`} className="grid grid-cols-[auto_auto_1fr] items-baseline gap-x-3 px-4 py-2 text-[13px]"
                style={{ borderLeft: `3px solid ${RANK[e.level] >= 2 ? TONE[e.level] : "transparent"}` }}>
              <time dateTime={e.ts} className="mono tabular text-xs text-faint">{when(e.ts)}</time>
              <span className="mono text-[11px] font-medium" style={{ color: TONE[e.level] }}>{t(`log.levels.${e.level}`)}</span>
              <div className="min-w-0">
                <p className="break-words text-ink">{e.message}</p>
                <p className="mono mt-0.5 text-[11px] text-faint">{t(`log.process.${e.process}`, { defaultValue: e.process })} · {e.source}</p>
                {e.exc && (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-xs text-muted hover:text-ink">{t("log.details")}</summary>
                    <pre className="mono mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded-[var(--radius-control)] bg-surface p-2 text-[11px] text-muted">{e.exc}</pre>
                  </details>
                )}
              </div>
            </li>
          ))}
        </ol>
      </Panel>

      {folder && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-faint">
          {t("log.folder")} <span className="mono break-all text-muted">{folder}</span>
          <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" aria-hidden />} onClick={() => copy(folder, folder)}>
            {t("log.copyPath")}
          </Button>
        </p>
      )}
    </div>
  );
}
