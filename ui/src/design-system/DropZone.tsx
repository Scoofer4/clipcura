import { motion, useReducedMotion } from "framer-motion";
import { FolderOpen } from "lucide-react";
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useTranslation } from "react-i18next";
import { FrameStack } from "../visuals/FrameStack";
import { Scene } from "../visuals/Scene";
import { Button } from "./Button";

/** SMPTE-style timecode at 30 fps: the drop zone reads as a live viewfinder. */
function useTimecode(running: boolean): string {
  const [frames, setFrames] = useState(0);
  useEffect(() => {
    if (!running) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      setFrames(Math.floor(((now - start) / 1000) * 30));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running]);
  const f = frames % 30;
  const s = Math.floor(frames / 30);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}:${pad(f)}`;
}

function Corner({ className }: { className: string }) {
  return (
    <span aria-hidden className={`absolute size-7 border-[var(--corner)] transition-[border-color] duration-[var(--dur-base)] ${className}`} />
  );
}

const VIDEO = /\.(mp4|mov|m4v|mts|m2ts|mkv|avi|mxf|insv|insp)$/i;

/**
 * Screen 1's single main action. Everything inside is the target: drop a folder anywhere on it, or click the
 * 3D frames / the button to pick one. Hovering a folder over it pulls the loose frames into register.
 */
export function DropZone({ onFiles, gpuBusy = false, forceActive = false }: {
  onFiles?: (files: File[]) => void;
  /** A job is using the GPU: the 3D frames hold still. */
  gpuBusy?: boolean;
  /** Kitchen sink only: show the drag-over state without dragging. */
  forceActive?: boolean;
}) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const active = dragging || forceActive;
  const timecode = useTimecode(!reduced && !gpuBusy);

  const accept = (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((f) => VIDEO.test(f.name));
    if (files.length) onFiles?.(files);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    accept(e.dataTransfer.files);
  };
  const choose = () => input.current?.click();

  return (
    <motion.div
      role="region"
      aria-label={t("drop.aria")}
      onDragEnter={(e) => (e.preventDefault(), setDragging(true))}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
      }}
      onDrop={onDrop}
      animate={{ scale: active ? 1.006 : 1 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      style={{
        ["--corner" as string]: active ? "var(--accent-2)" : "var(--line-strong)",
        boxShadow: active ? "0 0 0 1px var(--accent-2), 0 0 70px -12px var(--accent-glow)" : undefined,
      }}
      className="glass relative isolate flex min-h-[380px] flex-col items-center justify-center overflow-hidden px-8 pb-10 pt-6 text-center"
    >
      <Corner className="left-5 top-5 rounded-tl-lg border-l-2 border-t-2" />
      <Corner className="right-5 top-5 rounded-tr-lg border-r-2 border-t-2" />
      <Corner className="bottom-5 left-5 rounded-bl-lg border-b-2 border-l-2" />
      <Corner className="bottom-5 right-5 rounded-br-lg border-b-2 border-r-2" />

      <div className="mono tabular absolute left-9 top-8 flex items-center gap-2 text-xs text-muted">
        <span className="size-2 rounded-full" style={{ background: active ? "var(--accent-2)" : "var(--ok)" }} aria-hidden />
        {active ? t("drop.receiving") : t("drop.ready")}
      </div>
      <div className="mono tabular absolute right-9 top-8 text-xs text-faint" aria-hidden>{timecode}</div>

      {/* The 3D frames are part of the control: clicking them opens the folder picker. */}
      <button type="button" onClick={choose} tabIndex={-1} aria-hidden
              className="h-[190px] w-full max-w-[620px] cursor-pointer" title={t("drop.choose")}>
        <Scene label={t("drop.visual")} paused={gpuBusy} className="h-full w-full"
               camera={{ position: [0, 0.55, 4.5], fov: 34 }}>
          <FrameStack aligned={active} />
        </Scene>
      </button>

      <h2 className="mt-2 text-[28px] font-semibold leading-tight tracking-tight text-ink">
        {active ? t("drop.titleActive") : t("drop.title")}
      </h2>
      <p className="mt-2 max-w-[46ch] text-sm text-muted">{t("drop.body")}</p>
      <div className="mt-6 flex items-center gap-3">
        <Button variant="primary" size="lg" icon={<FolderOpen className="size-4" aria-hidden />} onClick={choose}>
          {t("drop.choose")}
        </Button>
        <span className="text-xs text-faint">{t("drop.formats")}</span>
      </div>
      {/* Browser folder picker for the web build; the desktop window swaps in the native Windows dialog. */}
      <input
        ref={input}
        type="file"
        className="hidden"
        multiple
        // @ts-expect-error -- non-standard but supported by Chromium/WebView2
        webkitdirectory=""
        onChange={(e: ChangeEvent<HTMLInputElement>) => (accept(e.target.files), (e.target.value = ""))}
      />
    </motion.div>
  );
}
