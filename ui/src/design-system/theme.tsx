import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { MotionConfig } from "framer-motion";

export type Theme = "dark" | "light";
export type Accent = "brand" | "aurora";
export type Motion = "full" | "reduced";

interface Appearance {
  theme: Theme;
  accent: Accent;
  motion: Motion;
  setTheme: (t: Theme) => void;
  setAccent: (a: Accent) => void;
  setMotion: (m: Motion) => void;
}

const Ctx = createContext<Appearance | null>(null);

// URL parameters win (screenshots and demos), then the saved choice, then the defaults from the brief.
function initial<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  const fromUrl = new URLSearchParams(window.location.search).get(key);
  if (fromUrl && (allowed as readonly string[]).includes(fromUrl)) return fromUrl as T;
  try {
    const saved = localStorage.getItem(`clipsana.${key}`);
    if (saved && (allowed as readonly string[]).includes(saved)) return saved as T;
  } catch {
    /* storage can be unavailable in locked-down WebView2 profiles */
  }
  return fallback;
}

function persist(key: string, value: string) {
  try {
    localStorage.setItem(`clipsana.${key}`, value);
  } catch {
    /* non-essential */
  }
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => initial("theme", ["dark", "light"] as const, "dark"));
  const [accent, setAccentState] = useState<Accent>(() => initial("accent", ["brand", "aurora"] as const, "brand"));
  const [motion, setMotionState] = useState<Motion>(() => initial("motion", ["full", "reduced"] as const, "full"));

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.accent = accent;
    root.dataset.motion = motion;
  }, [theme, accent, motion]);

  const value = useMemo<Appearance>(
    () => ({
      theme,
      accent,
      motion,
      setTheme: (t) => (persist("theme", t), setThemeState(t)),
      setAccent: (a) => (persist("accent", a), setAccentState(a)),
      setMotion: (m) => (persist("motion", m), setMotionState(m)),
    }),
    [theme, accent, motion],
  );

  return (
    <Ctx.Provider value={value}>
      {/* "user" follows the OS setting; the in-app switch can force reduced motion on top of it. */}
      <MotionConfig reducedMotion={motion === "reduced" ? "always" : "user"}>{children}</MotionConfig>
    </Ctx.Provider>
  );
}

export function useAppearance(): Appearance {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAppearance must be used inside AppearanceProvider");
  return ctx;
}
