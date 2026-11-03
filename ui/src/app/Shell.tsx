import { Activity, Bot, FolderSearch, Home, Moon, Settings as SettingsIcon, Sun, Command as CommandIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api, hasToken, type Job, type RecentScan } from "../api/client";
import { useEventListener, useEvents } from "../api/events";
import { fileName } from "../api/present";
import { Lockup } from "../design-system/Logo";
import { useAppearance } from "../design-system/theme";
import { CommandPalette, type Command } from "./CommandPalette";

export const LAST_SCAN_KEY = "clipcura.lastScan";

export function lastScanId(): string | null {
  try { return localStorage.getItem(LAST_SCAN_KEY); } catch { return null; }
}

function NavItem({ to, icon, label, badge }: { to: string; icon: React.ReactNode; label: string; badge?: number }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `flex h-10 items-center gap-3 rounded-[var(--radius-control)] px-3 text-sm transition-colors duration-[var(--dur-fast)] ${
          isActive ? "bg-raised text-ink shadow-[inset_2px_0_0_var(--accent-2)]" : "text-muted hover:bg-surface hover:text-ink"}`}
    >
      {icon}
      <span className="flex-1">{label}</span>
      {!!badge && (
        <span className="tabular min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold leading-5 text-[var(--accent-ink)]"
              style={{ background: "var(--accent-solid)" }}>{badge}</span>
      )}
    </NavLink>
  );
}

/** Application frame: navigation, live connection state, command palette. */
export function Shell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const appearance = useAppearance();
  const { connected } = useEvents();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [recent, setRecent] = useState<RecentScan[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);

  const refresh = () => {
    if (!hasToken()) return;
    api.recentScans(6).then(setRecent).catch(() => {});
    api.jobs(50).then(setJobs).catch(() => {});
  };
  useEffect(refresh, []);
  useEventListener(["job.status", "scan.done"], refresh);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const running = jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  const waiting = jobs.filter((j) => j.status === "awaiting_approval").length;
  const last = lastScanId();

  const commands = useMemo<Command[]>(() => [
    { id: "start", label: t("nav.start"), icon: <Home className="size-4" />, run: () => navigate("/") },
    ...(last ? [{ id: "results", label: t("nav.results"), icon: <FolderSearch className="size-4" />, run: () => navigate(`/scans/${last}`) }] : []),
    { id: "jobs", label: t("nav.jobs"), icon: <Activity className="size-4" />, run: () => navigate("/jobs") },
    { id: "activity", label: t("nav.activity"), icon: <Bot className="size-4" />, run: () => navigate("/activity") },
    { id: "settings", label: t("nav.settings"), icon: <SettingsIcon className="size-4" />, run: () => navigate("/settings") },
    ...recent.map((r) => ({
      id: `scan-${r.scan_id}`, label: t("palette.openScan", { name: fileName(r.root) }), hint: r.root,
      icon: <FolderSearch className="size-4" />, run: () => navigate(`/scans/${r.scan_id}`),
    })),
    {
      id: "theme", label: appearance.theme === "dark" ? t("palette.light") : t("palette.dark"),
      icon: appearance.theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />,
      run: () => appearance.setTheme(appearance.theme === "dark" ? "light" : "dark"),
    },
  ], [t, navigate, recent, appearance, last]);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col border-r border-line px-3 py-5 md:flex">
        <div className="px-2"><Lockup size={30} /></div>
        <nav className="mt-8 flex flex-col gap-1" aria-label={t("nav.aria")}>
          <NavItem to="/" icon={<Home className="size-4" aria-hidden />} label={t("nav.start")} />
          {last && <NavItem to={`/scans/${last}`} icon={<FolderSearch className="size-4" aria-hidden />} label={t("nav.results")} />}
          <NavItem to="/jobs" icon={<Activity className="size-4" aria-hidden />} label={t("nav.jobs")} badge={running} />
          <NavItem to="/activity" icon={<Bot className="size-4" aria-hidden />} label={t("nav.activity")} badge={waiting} />
          <NavItem to="/settings" icon={<SettingsIcon className="size-4" aria-hidden />} label={t("nav.settings")} />
        </nav>
        <div className="mt-auto space-y-3 px-2">
          <button type="button" onClick={() => setPaletteOpen(true)}
                  className="flex w-full items-center gap-2 rounded-[var(--radius-control)] border border-line px-3 py-2 text-xs text-muted hover:text-ink">
            <CommandIcon className="size-3.5" aria-hidden />{t("palette.open")}
            <kbd className="mono ml-auto text-[11px] text-faint">Ctrl K</kbd>
          </button>
          <div className="flex items-center gap-2 text-xs text-faint" role="status">
            <span className="size-2 rounded-full" style={{ background: connected ? "var(--ok)" : "var(--human)" }} aria-hidden />
            {connected ? t("nav.live") : t("nav.offline")}
          </div>
        </div>
      </aside>

      {/* Narrow windows: the same destinations as a top bar. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-line px-4 py-3 md:hidden">
          <Lockup size={24} />
          <nav className="ml-auto flex gap-1" aria-label={t("nav.aria")}>
            <NavLink to="/" className="rounded p-2 text-muted" aria-label={t("nav.start")}><Home className="size-4" /></NavLink>
            <NavLink to="/jobs" className="rounded p-2 text-muted" aria-label={t("nav.jobs")}><Activity className="size-4" /></NavLink>
            <NavLink to="/activity" className="rounded p-2 text-muted" aria-label={t("nav.activity")}><Bot className="size-4" /></NavLink>
            <NavLink to="/settings" className="rounded p-2 text-muted" aria-label={t("nav.settings")}><SettingsIcon className="size-4" /></NavLink>
          </nav>
        </header>
        <main className="min-w-0 flex-1 px-6 pb-16 pt-8 md:px-10">
          <Outlet />
        </main>
      </div>
      <CommandPalette commands={commands} open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
