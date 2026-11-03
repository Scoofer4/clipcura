import { CircleCheck, CircleX, LoaderCircle, MessageSquarePlus, Send, Settings as SettingsIcon, Square, TriangleAlert, Wrench } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, type AssistantConversation, type AssistantStatus, type TranscriptItem } from "../api/client";
import { useEventListener } from "../api/events";
import { useToast } from "../app/toast";
import { Button } from "../design-system/Button";
import { Panel } from "../design-system/Panel";

/** Bold and `code` inside one line of the model's text. React elements only: model output is never HTML. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={i} className="font-semibold text-ink">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={i} className="mono rounded bg-surface px-1 text-[12px]">{part.slice(1, -1)}</code>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/** The little Markdown models use: paragraphs, bullet and numbered lists, bold, code. */
function Rich({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(<Tag key={blocks.length} className={`ml-5 space-y-1 ${list.ordered ? "list-decimal" : "list-disc"}`}>
      {list.items.map((item, i) => <li key={i}>{inline(item)}</li>)}
    </Tag>);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^[*-]\s+(.*)$/);
    const numbered = line.match(/^\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const ordered = !!numbered;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
      continue;
    }
    flush();
    if (!line) continue;
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    blocks.push(heading
      ? <p key={blocks.length} className="font-semibold text-ink">{inline(heading[1])}</p>
      : <p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="space-y-2 text-sm leading-relaxed text-ink">{blocks}</div>;
}

function ToolStep({ item }: { item: Extract<TranscriptItem, { role: "tool" }> }) {
  const { t } = useTranslation();
  const icon = item.ok === null
    ? <LoaderCircle className="size-3.5 animate-spin text-muted" aria-label={t("assistant.running")} />
    : item.ok
      ? <CircleCheck className="size-3.5" style={{ color: "var(--ok)" }} aria-label={t("assistant.toolOk")} />
      : <CircleX className="size-3.5" style={{ color: "var(--error)" }} aria-label={t("assistant.toolFailed")} />;
  return (
    <details className="group rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2 text-[13px]">
      <summary className="flex cursor-pointer list-none items-center gap-2">
        <Wrench className="size-3.5 shrink-0 text-faint" aria-hidden />
        <span className="mono text-ink">{t(`assistant.tools.${item.name}`, { defaultValue: item.name })}</span>
        {icon}
        <span className="min-w-0 flex-1 truncate text-muted">{item.summary}</span>
      </summary>
      <pre className="mono mt-2 max-h-60 overflow-auto whitespace-pre-wrap text-[11px] text-muted">
        {item.name}({JSON.stringify(item.arguments, null, 1)})
        {item.summary ? `\n→ ${item.summary}` : ""}
      </pre>
    </details>
  );
}

function Item({ item }: { item: TranscriptItem }) {
  const { t } = useTranslation();
  if (item.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] rounded-[14px] rounded-br-[4px] border border-line bg-raised px-4 py-2.5 text-sm text-ink">
        <p className="whitespace-pre-wrap break-words">{item.text}</p>
        {item.details && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-muted hover:text-ink">{t("assistant.sentDetails")}</summary>
            <pre className="mono mt-1 max-h-60 overflow-auto whitespace-pre-wrap text-[11px] text-muted">{item.details}</pre>
          </details>
        )}
      </div>
    );
  }
  if (item.role === "tool") return <ToolStep item={item} />;
  if (item.role === "error") {
    return (
      <p className="flex items-start gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--error)_45%,transparent)] px-3 py-2 text-sm text-ink" role="alert">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" style={{ color: "var(--error)" }} aria-hidden />{item.text}
      </p>
    );
  }
  return <div className="max-w-[92%]"><Rich text={item.text} /></div>;
}

/** Apply one live event to the transcript the same way the service builds it (clipcura/assistant/chat.py). */
function applyEvent(items: TranscriptItem[], e: Record<string, unknown>): TranscriptItem[] {
  switch (e.kind) {
    case "text": {
      const last = items[items.length - 1];
      if (last?.role === "assistant") return [...items.slice(0, -1), { ...last, text: last.text + String(e.delta) }];
      return [...items, { role: "assistant", text: String(e.delta) }];
    }
    case "tool": {
      const next = [...items];
      next[Number(e.index)] = { role: "tool", name: String(e.name), arguments: (e.arguments ?? {}) as Record<string, unknown>, ok: null, summary: "" };
      return next;
    }
    case "tool_done": {
      const next = [...items];
      const step = next[Number(e.index)];
      if (step?.role === "tool") next[Number(e.index)] = { ...step, ok: Boolean(e.ok), summary: String(e.summary ?? "") };
      return next;
    }
    case "error":
      return [...items, { role: "error", text: String(e.text) }];
    default:
      return items;
  }
}

/** Built-in assistant (#27): give Clipcura tasks in plain words; a model on your Ollama server does them with the
 *  same tools and limits as an assistant connected over MCP. */
export function AssistantScreen() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const current = params.get("c");
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [conv, setConv] = useState<AssistantConversation | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const loadStatus = () => api.assistant().then(setStatus).catch(() => {});
  const loadConv = (id: string) => api.conversation(id).then(setConv).catch(() => setConv(null));
  useEffect(() => { void loadStatus(); }, []);
  // Ask the server once on opening, so an unreachable Ollama shows before a task is typed, not after.
  const [reach, setReach] = useState<{ ok: boolean; error?: string } | null>(null);
  const checkReach = () => {
    setReach(null);
    api.testAssistant().then(() => setReach({ ok: true })).catch((e) => setReach({ ok: false, error: e instanceof Error ? e.message : String(e) }));
  };
  const ready = !!(status?.enabled && status.url && status.model);
  useEffect(() => { if (ready) checkReach(); }, [ready]);
  useEffect(() => { if (current) void loadConv(current); else setConv(null); }, [current]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [conv?.transcript.length, conv?.busy]);

  useEventListener(["assistant"], (e) => {
    if (e.kind === "start" || e.kind === "done") void loadStatus();
    if (!current || e.conversation !== current) return;
    if (e.kind === "done") { void loadConv(current); return; }
    setConv((c) => c && { ...c, busy: true, transcript: applyEvent(c.transcript, e) });
  });

  const send = async (text: string) => {
    const task = text.trim();
    if (!task || sending || conv?.busy) return;
    setSending(true);
    try {
      const { conversation } = await api.ask(task, i18n.language, current ?? undefined);
      setDraft("");
      if (conversation !== current) setParams({ c: conversation });
      else void loadConv(conversation);
    } catch (err) {
      toast(t("assistant.sendFailed"), err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
      input.current?.focus();
    }
  };
  const onSubmit = (e: FormEvent) => { e.preventDefault(); void send(draft); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(draft); }
  };

  const host = (() => { try { return status?.url ? new URL(status.url).host : ""; } catch { return status?.url ?? ""; } })();
  const examples = t("assistant.examples", { returnObjects: true }) as string[];

  if (status && !ready) {
    return (
      <div className="mx-auto max-w-[980px]">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink">{t("nav.assistant")}</h1>
        <Panel className="mt-6 p-10 text-center">
          <h2 className="text-lg font-semibold text-ink">{t("assistant.offTitle")}</h2>
          <p className="mx-auto mt-2 max-w-[60ch] text-sm text-muted">{t("assistant.offBody")}</p>
          <Button className="mt-5" variant="primary" icon={<SettingsIcon className="size-4" aria-hidden />}
                  onClick={() => navigate("/settings#assistant")}>{t("assistant.openSettings")}</Button>
        </Panel>
      </div>
    );
  }

  return (
    <div className="mx-auto grid max-w-[1180px] gap-6 lg:grid-cols-[240px_1fr]">
      <aside className="order-2 lg:order-1">
        <Button variant="secondary" className="w-full" icon={<MessageSquarePlus className="size-4" aria-hidden />}
                onClick={() => { setParams({}); input.current?.focus(); }}>{t("assistant.new")}</Button>
        {!!status?.conversations.length && (
          <nav aria-label={t("assistant.history")} className="mt-4">
            <h2 className="px-1 text-xs text-faint">{t("assistant.history")}</h2>
            <ul className="mt-2 space-y-1">
              {status.conversations.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => setParams({ c: c.id })} aria-current={c.id === current || undefined}
                          className={`flex w-full items-center gap-2 rounded-[var(--radius-control)] px-2 py-1.5 text-left text-[13px] ${
                            c.id === current ? "bg-raised text-ink" : "text-muted hover:bg-surface hover:text-ink"}`}>
                    {c.busy && <LoaderCircle className="size-3.5 shrink-0 animate-spin" aria-label={t("assistant.running")} />}
                    <span className="min-w-0 flex-1 truncate">{c.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </aside>

      <section className="order-1 flex min-h-[70vh] flex-col lg:order-2">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink">{t("nav.assistant")}</h1>
        <p className="mt-1 max-w-[75ch] text-sm text-muted">{t("assistant.intro")}</p>

        <Panel className="mt-6 flex flex-1 flex-col p-5">
          {reach && !reach.ok && (
            <div role="alert" className="mb-4 flex flex-wrap items-start gap-3 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--human)_50%,transparent)] px-3 py-2 text-sm">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" style={{ color: "var(--human)" }} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-ink">{t("assistant.unreachable")}</p>
                <p className="mono mt-0.5 break-words text-xs text-muted">{reach.error}</p>
              </div>
              <Button size="sm" variant="secondary" onClick={checkReach}>{t("assistant.retry")}</Button>
            </div>
          )}
          <div className="flex-1 space-y-4" aria-live="polite">
            {!conv && (
              <div className="py-6">
                <p className="text-sm text-muted">{t("assistant.examplesTitle")}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {examples.map((ex) => (
                    <button key={ex} type="button" onClick={() => { setDraft(ex); input.current?.focus(); }}
                            className="rounded-full border border-line bg-surface px-3 py-1.5 text-left text-[13px] text-muted hover:border-[var(--line-strong)] hover:text-ink">
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {conv?.transcript.map((item, i) => <Item key={i} item={item} />)}
            {conv?.busy && conv.transcript[conv.transcript.length - 1]?.role !== "assistant" && (
              <p className="flex items-center gap-2 text-sm text-muted">
                <LoaderCircle className="size-4 animate-spin" aria-hidden />{t("assistant.thinking")}
              </p>
            )}
            <div ref={end} />
          </div>

          <form onSubmit={onSubmit} className="mt-5 border-t border-line pt-4">
            <label htmlFor="assistant-input" className="sr-only">{t("assistant.inputLabel")}</label>
            <textarea id="assistant-input" ref={input} rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey}
                      placeholder={t("assistant.placeholder")} maxLength={8000}
                      className="w-full resize-y rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-[var(--accent-2)]" />
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <p className="min-w-0 flex-1 text-xs text-faint">{t("assistant.where", { host, model: status?.model ?? "" })}</p>
              {conv?.busy ? (
                <Button variant="secondary" icon={<Square className="size-3.5" aria-hidden />}
                        onClick={() => current && api.stopAssistant(current)}>{t("assistant.stop")}</Button>
              ) : (
                <Button type="submit" variant="primary" loading={sending} disabled={!draft.trim()}
                        icon={<Send className="size-4" aria-hidden />}>{t("assistant.send")}</Button>
              )}
            </div>
          </form>
        </Panel>
      </section>
    </div>
  );
}

/** "Explain" next to a failure: starts a conversation with its details and opens it. Hidden while the assistant
 *  is off. */
export function useExplain(): ((what: Parameters<typeof api.explain>[0]) => Promise<void>) | null {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();
  const [on, setOn] = useState(false);
  useEffect(() => { api.assistant().then((s) => setOn(!!(s.enabled && s.url && s.model))).catch(() => {}); }, []);
  if (!on) return null;
  return async (what) => {
    try {
      const { conversation } = await api.explain(what, i18n.language);
      navigate(`/assistant?c=${conversation}`);
    } catch (err) {
      toast(t("assistant.sendFailed"), err instanceof Error ? err.message : String(err));
    }
  };
}
