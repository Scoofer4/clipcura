import { useId } from "react";

export type LogoConcept = "viewfinder" | "pulse" | "cube" | "monogram";
export const LOGO_CONCEPTS: LogoConcept[] = ["viewfinder", "pulse", "cube", "monogram"];

/**
 * Logo concepts for owner review. 64-unit grid, strokes sized to stay legible at 16 px (tray icon).
 * Colours come from the active accent tokens, so every concept previews in both accents.
 */
export function LogoMark({ concept, size = 64, title }: { concept: LogoConcept; size?: number; title?: string }) {
  const id = useId().replace(/:/g, "");
  const grad = `g${id}`;
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
      {concept === "viewfinder" && (
        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          {/* Camera viewfinder corners: the frame of a shot. */}
          <path d="M8 21V13a5 5 0 0 1 5-5h8M43 8h8a5 5 0 0 1 5 5v8M8 43v8a5 5 0 0 0 5 5h8M56 43v8a5 5 0 0 1-5 5h-8"
                stroke="var(--text)" strokeWidth="4.5" />
          {/* The check: the clip inside the frame is edit-ready. */}
          <path d="M19 33l9 9 17-20" stroke={`url(#${grad})`} strokeWidth="6.5" />
        </g>
      )}
      {concept === "pulse" && (
        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          {/* A film frame whose heartbeat ends in a check: "sana" is Latin for healthy. */}
          <rect x="6" y="11" width="52" height="42" rx="9" stroke="var(--text)" strokeWidth="4.5" />
          <path d="M13 35h9l4-8 6 14 5-9h4l9-11" stroke={`url(#${grad})`} strokeWidth="5.5" />
        </g>
      )}
      {concept === "cube" && (
        <g strokeLinejoin="round">
          {/* Isometric cube, a family nod to the Metaverse Media mark. */}
          <path d="M32 5l24 13.5L32 32 8 18.5z" fill="var(--line-strong)" />
          <path d="M8 18.5L32 32v27L8 45.5z" fill="var(--accent-1)" />
          <path d="M56 18.5L32 32v27l24-13.5z" fill="var(--accent-2)" />
          <path d="M18 37l10 9 19-21" fill="none" stroke="#fff" strokeWidth="5.5" strokeLinecap="round" />
        </g>
      )}
      {concept === "monogram" && (
        <g strokeLinecap="round">
          {/* A "C" left open on the right, where playback starts. */}
          <path d="M47.6 16.4A22 22 0 1 0 47.6 47.6" fill="none" stroke={`url(#${grad})`} strokeWidth="7" />
          <path d="M28 23.5l13.5 8.5L28 40.5z" fill="var(--text)" strokeLinejoin="round" stroke="var(--text)" strokeWidth="2" />
        </g>
      )}
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

export function Lockup({ concept, size = 40 }: { concept: LogoConcept; size?: number }) {
  return (
    <span className="inline-flex items-center gap-3">
      <LogoMark concept={concept} size={size} />
      <Wordmark size={size * 0.72} />
    </span>
  );
}
