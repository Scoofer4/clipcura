import { useId } from "react";

/**
 * Clipsana logo (owner's choice, 2026-11-02): a "C" left open on the right, where playback starts.
 * 64-unit grid with strokes that stay legible at 16 px (tray icon). The arc follows the active accent.
 */
export function LogoMark({ size = 64, title }: { size?: number; title?: string }) {
  const grad = `g${useId().replace(/:/g, "")}`;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role={title ? "img" : undefined}
         aria-hidden={title ? undefined : true} aria-label={title}>
      <defs>
        <linearGradient id={grad} x1="6" y1="58" x2="58" y2="6" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--accent-1)" />
          <stop offset="0.55" stopColor="var(--accent-2)" />
          <stop offset="1" stopColor="var(--accent-3)" />
        </linearGradient>
      </defs>
      <path d="M47.6 16.4A22 22 0 1 0 47.6 47.6" fill="none" stroke={`url(#${grad})`} strokeWidth="7" strokeLinecap="round" />
      <path d="M28 23.5l13.5 8.5L28 40.5z" fill="var(--text)" stroke="var(--text)" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

export function Wordmark({ size = 28 }: { size?: number }) {
  return (
    <span className="font-semibold text-ink" style={{ fontSize: size, letterSpacing: "-0.035em", lineHeight: 1 }}>
      clipsana
    </span>
  );
}

export function Lockup({ size = 40 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-3">
      <LogoMark size={size} />
      <Wordmark size={size * 0.72} />
    </span>
  );
}
