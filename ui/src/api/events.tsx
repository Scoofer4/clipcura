import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { eventsUrl, hasToken, type JobStatus } from "./client";

/** One message from /api/events (see clipcura/core/events.py). */
export interface ApiEvent {
  type: "scan.file" | "scan.done" | "plan.created" | "job.status" | "job.progress" | "audit" | "updates" | "log";
  ts: string;
  [key: string]: unknown;
}

export interface LiveJob {
  status?: JobStatus;
  percent: number;
  fps: number;
  etaSeconds: number | null;
  speedHistory: number[];
}

interface EventsState {
  connected: boolean;
  /** Latest progress and status per job id, from the stream. */
  jobs: Record<string, LiveJob>;
  subscribe: (fn: (e: ApiEvent) => void) => () => void;
}

const Ctx = createContext<EventsState | null>(null);

/**
 * Keeps one WebSocket to the API for the whole app and reconnects with backoff, so every screen sees what
 * happens live, including actions started by an AI assistant or n8n.
 */
export function EventsProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [jobs, setJobs] = useState<Record<string, LiveJob>>({});
  const listeners = useRef(new Set<(e: ApiEvent) => void>());

  useEffect(() => {
    if (!hasToken()) return;
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      ws = new WebSocket(eventsUrl());
      ws.onopen = () => { retry = 0; setConnected(true); };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = window.setTimeout(connect, Math.min(10_000, 500 * 2 ** retry++));
      };
      ws.onmessage = (m) => {
        const e = JSON.parse(m.data) as ApiEvent;
        if (e.type === "job.progress" || e.type === "job.status") {
          const id = e.job_id as string;
          setJobs((prev) => {
            const cur = prev[id] ?? { percent: 0, fps: 0, etaSeconds: null, speedHistory: [] };
            if (e.type === "job.status") return { ...prev, [id]: { ...cur, status: e.status as JobStatus } };
            const fps = Number(e.fps) || 0;
            return {
              ...prev,
              [id]: {
                ...cur,
                percent: Number(e.percent) || 0,
                fps,
                etaSeconds: (e.eta_s as number | null) ?? null,
                speedHistory: fps ? [...cur.speedHistory.slice(-39), fps] : cur.speedHistory,
              },
            };
          });
        }
        listeners.current.forEach((fn) => fn(e));
      };
    };
    connect();
    return () => { closed = true; window.clearTimeout(timer); ws?.close(); };
  }, []);

  const value = useMemo<EventsState>(() => ({
    connected,
    jobs,
    subscribe: (fn) => { listeners.current.add(fn); return () => listeners.current.delete(fn); },
  }), [connected, jobs]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useEvents(): EventsState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useEvents must be used inside EventsProvider");
  return ctx;
}

/** Run `fn` for every event of the given types (stable across renders). */
export function useEventListener(types: ApiEvent["type"][], fn: (e: ApiEvent) => void) {
  const { subscribe } = useEvents();
  const ref = useRef(fn);
  ref.current = fn;
  const key = types.join(",");
  useEffect(() => subscribe((e) => { if (key.split(",").includes(e.type)) ref.current(e); }), [subscribe, key]);
}
