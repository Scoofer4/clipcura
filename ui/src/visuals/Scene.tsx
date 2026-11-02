import { Canvas } from "@react-three/fiber";
import { useReducedMotion } from "framer-motion";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Color } from "three";
import { useAppearance } from "../design-system/theme";

/**
 * Shared shell for every 3D visual (see docs/design-system.md, "Motion and 3D").
 *
 * - Renders continuously only while visible, motion is allowed and no job needs the GPU; otherwise it draws
 *   one still frame that still explains the idea.
 * - Asks for the low-power GPU: on hybrid laptops the UI then runs on the integrated GPU and leaves the
 *   discrete one free for decoding and encoding.
 */

interface SceneState {
  live: boolean;
  colors: Palette;
}

export interface Palette {
  accent1: Color;
  accent2: Color;
  accent3: Color;
  body: Color;
  line: Color;
  muted: Color;
  isDark: boolean;
}

const SceneCtx = createContext<SceneState | null>(null);

export function useScene(): SceneState {
  const ctx = useContext(SceneCtx);
  if (!ctx) throw new Error("3D visuals must be rendered inside <Scene>");
  return ctx;
}

function readPalette(isDark: boolean): Palette {
  const css = getComputedStyle(document.documentElement);
  const get = (name: string) => new Color(css.getPropertyValue(name).trim() || "#888888");
  return {
    accent1: get("--accent-1"),
    accent2: get("--accent-2"),
    accent3: get("--accent-3"),
    body: new Color(isDark ? "#222830" : "#3a414b"),   // light theme: dark frames read as objects on a pale page
    line: new Color(isDark ? "#ffffff" : "#ffffff"),
    muted: new Color(isDark ? "#6c7682" : "#8d97a3"),
    isDark,
  };
}

/** Accent and theme colours from the CSS tokens, re-read whenever the appearance changes. */
function usePalette(): Palette {
  const { theme, accent } = useAppearance();
  const [palette, setPalette] = useState(() => readPalette(theme === "dark"));
  useEffect(() => {
    // The provider writes data-theme/data-accent in its own effect; read on the next frame.
    const id = requestAnimationFrame(() => setPalette(readPalette(theme === "dark")));
    return () => cancelAnimationFrame(id);
  }, [theme, accent]);
  return palette;
}

export function Scene({ children, label, camera, paused = false, className = "", overlay }: {
  children: ReactNode;
  label: string;
  camera: { position: [number, number, number]; fov: number };
  /** True while a job runs: the GPU belongs to the transcode. */
  paused?: boolean;
  className?: string;
  overlay?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const [visible, setVisible] = useState(true);
  const colors = usePalette();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: 0.05 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const live = visible && !paused && !reduced;
  const state = useMemo(() => ({ live, colors }), [live, colors]);

  return (
    <div ref={ref} className={`relative ${className}`} role="img" aria-label={label}>
      <Canvas
        frameloop={live ? "always" : "demand"}
        dpr={[1, 1.75]}
        camera={camera}
        gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
      >
        <SceneCtx.Provider value={state}>
          <ambientLight intensity={colors.isDark ? 0.55 : 0.9} />
          <directionalLight position={[3, 4, 5]} intensity={colors.isDark ? 1.3 : 1.1} />
          <pointLight position={[-3, -1, 3]} intensity={6} distance={12} color={colors.accent2} />
          {children}
        </SceneCtx.Provider>
      </Canvas>
      {overlay}
    </div>
  );
}
