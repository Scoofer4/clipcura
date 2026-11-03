import { Copy, FolderPlus, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, type AppConfig, type Profile, type SystemReport } from "../api/client";
import { useToast } from "../app/toast";
import { Button } from "../design-system/Button";
import { Segmented, Switch } from "../design-system/Controls";
import { Panel } from "../design-system/Panel";
import { useAppearance } from "../design-system/theme";
import { setLanguage, type Language } from "../i18n";
import { UpdatesSection } from "../app/updates";
import { AssistantSettings } from "../app/AssistantSettings";
import { ProfileEditor } from "./ProfileEditor";

function Section({ id, title, intro, children }: { id?: string; title: string; intro?: string; children: React.ReactNode }) {
  return (
    <Panel className="scroll-mt-6 p-6" id={id}>
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      {intro && <p className="mt-1 max-w-[70ch] text-sm text-muted">{intro}</p>}
      <div className="mt-4">{children}</div>
    </Panel>
  );
}

function Stepper({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="flex items-center justify-between gap-4 text-sm text-ink">
      {label}
      <span className="flex items-center gap-1">
        <Button size="sm" variant="secondary" aria-label={`${label} −`} disabled={value <= 1} onClick={() => onChange(value - 1)}>−</Button>
        <span className="mono tabular w-8 text-center">{value}</span>
        <Button size="sm" variant="secondary" aria-label={`${label} +`} disabled={value >= 4} onClick={() => onChange(value + 1)}>+</Button>
      </span>
    </label>
  );
}

/** Screen 6: folders the app may touch, approvals, concurrency, appearance, profiles and system. */
export function SettingsScreen() {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const appearance = useAppearance();
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [system, setSystem] = useState<SystemReport | null>(null);
  const [newRoot, setNewRoot] = useState("");
  const [editing, setEditing] = useState<{ profile: Profile; isNew: boolean } | null>(null);
  const reloadProfiles = () => api.profiles().then(setProfiles).catch(() => {});
  const removeProfile = async (p: Profile) => {
    try {
      await api.deleteProfile(p.name);
      reloadProfiles();
      toast(t(p.source === "edited" ? "settings.profileReset" : "settings.profileDeleted"), p.name);
    } catch (e) { toast(t("settings.saveFailed"), e instanceof Error ? e.message : String(e)); }
  };

  useEffect(() => {
    if (window.location.hash === "#assistant") window.setTimeout(() => document.getElementById("assistant")?.scrollIntoView(), 50);
    api.config().then(setCfg).catch(() => {});
    reloadProfiles();
    api.system().then(setSystem).catch(() => {});
  }, []);

  const save = async (patch: Parameters<typeof api.patchConfig>[0]) => {
    try { setCfg(await api.patchConfig(patch)); toast(t("settings.saved")); }
    catch (e) { toast(t("settings.saveFailed"), e instanceof Error ? e.message : String(e)); }
  };
  const addRoot = async (e: FormEvent) => {
    e.preventDefault();
    if (!newRoot.trim()) return;
    try { setCfg(await api.addRoot(newRoot.trim())); setNewRoot(""); toast(t("start.allowed")); }
    catch (err) { toast(t("start.allowFailed"), err instanceof Error ? err.message : String(err)); }
  };

  return (
    <div className="mx-auto max-w-[980px] space-y-4">
      <h1 className="text-[28px] font-semibold tracking-tight text-ink">{t("nav.settings")}</h1>

      <Section title={t("settings.folders")} intro={t("settings.foldersIntro")}>
        {cfg && cfg.allowed_roots.length === 0 && <p className="mb-3 text-sm text-human">{t("settings.noFolders")}</p>}
        <ul className="space-y-2">
          {cfg?.allowed_roots.map((r) => (
            <li key={r} className="flex items-center gap-3 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2">
              <span className="mono min-w-0 flex-1 truncate text-[13px] text-ink">{r}</span>
              <Button size="sm" variant="ghost" icon={<Trash2 className="size-4" aria-hidden />}
                      onClick={async () => setCfg(await api.removeRoot(r))}>{t("settings.remove")}</Button>
            </li>
          ))}
        </ul>
        <form onSubmit={addRoot} className="mt-3 flex gap-2">
          <label htmlFor="root" className="sr-only">{t("settings.addFolder")}</label>
          <input id="root" value={newRoot} onChange={(e) => setNewRoot(e.target.value)} placeholder={t("start.pathPlaceholder")}
                 className="mono h-10 min-w-0 flex-1 rounded-[var(--radius-control)] border border-line bg-surface px-3 text-[13px] text-ink outline-none focus:border-[var(--accent-2)]" />
          <Button type="submit" icon={<FolderPlus className="size-4" aria-hidden />}>{t("settings.addFolder")}</Button>
        </form>
      </Section>

      <Section title={t("settings.ai")}>
        {cfg && (
          <div className="space-y-5">
            <Switch checked={cfg.approval_mode} onChange={(v) => save({ approval_mode: v })}
                    label={t("settings.approval")} description={t("settings.approvalHint")} />
            <div className="grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
              <Stepper label={t("settings.gpuJobs")} value={cfg.concurrency.gpu}
                       onChange={(v) => save({ concurrency: { ...cfg.concurrency, gpu: v } })} />
              <Stepper label={t("settings.cpuJobs")} value={cfg.concurrency.cpu}
                       onChange={(v) => save({ concurrency: { ...cfg.concurrency, cpu: v } })} />
            </div>
          </div>
        )}
      </Section>

      <Section id="assistant" title={t("settings.assistant")} intro={t("settings.assistantIntro")}>
        <AssistantSettings />
      </Section>

      <Section title={t("settings.appearance")}>
        <div className="flex flex-wrap gap-3">
          <Segmented label={t("settings.theme")} value={appearance.theme} onChange={appearance.setTheme}
                     options={[{ value: "dark", label: t("settings.dark") }, { value: "light", label: t("settings.light") }]} />
          <Segmented label={t("settings.accent")} value={appearance.accent} onChange={appearance.setAccent}
                     options={[{ value: "brand", label: t("settings.brand") }, { value: "aurora", label: t("settings.aurora") }]} />
          <Segmented label={t("settings.language")} value={i18n.language as Language} onChange={setLanguage}
                     options={[{ value: "en", label: "English" }, { value: "cs", label: "Čeština" }]} />
        </div>
        <div className="mt-5 border-t border-line pt-4">
          <Switch checked={appearance.motion === "full"} onChange={(v) => appearance.setMotion(v ? "full" : "reduced")}
                  label={t("settings.motion")} description={t("settings.motionHint")} />
        </div>
        {cfg && (
          <div className="mt-5 border-t border-line pt-4">
            <Segmented label={t("settings.interface")} value={cfg.interface} onChange={(v) => save({ interface: v })}
                       options={[{ value: "window", label: t("settings.interfaceWindow") },
                                 { value: "browser", label: t("settings.interfaceBrowser") }]} />
            <p className="mt-2 max-w-[70ch] text-xs text-muted">{t("settings.interfaceHint")}</p>
          </div>
        )}
      </Section>

      <Section title={t("settings.updates")} intro={t("settings.updatesIntro")}>
        <UpdatesSection />
      </Section>

      <Section title={t("settings.profiles")} intro={t("settings.profilesIntro")}>
        <ul className="grid gap-3 md:grid-cols-3">
          {profiles.map((p) => (
            <li key={p.name} className="flex flex-col rounded-[var(--radius-control)] border border-line bg-surface p-3">
              <div className="flex items-center gap-2">
                <span className="mono text-sm text-ink">{p.name}</span>
                {p.source !== "builtin" && (
                  <span className="rounded-full border border-line px-1.5 text-[11px] text-muted">{t(`settings.source.${p.source}`)}</span>
                )}
              </div>
              <div className="mt-0.5 text-xs text-muted">{p.label}</div>
              <div className="mono tabular mt-2 text-xs text-faint">{p.fps} fps, ≤{p.max_long_side} px, {p.output.codec}, {p.audio_rate / 1000} kHz</div>
              <div className="mt-3 flex flex-wrap gap-1.5 pt-1">
                <Button size="sm" variant="secondary" icon={<Pencil className="size-3.5" aria-hidden />}
                        aria-label={t("settings.editProfile", { name: p.name })} onClick={() => setEditing({ profile: p, isNew: false })}>
                  {t("settings.edit")}
                </Button>
                <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" aria-hidden />}
                        aria-label={t("settings.duplicateProfile", { name: p.name })}
                        onClick={() => setEditing({ profile: { ...p, name: `${p.name}-copy`.slice(0, 40), label: `${p.label} (2)`, source: "user" }, isNew: true })}>
                  {t("settings.duplicate")}
                </Button>
                {p.source !== "builtin" && (
                  <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" aria-hidden />}
                          aria-label={t(p.source === "edited" ? "settings.resetProfile" : "settings.deleteProfile", { name: p.name })}
                          onClick={() => removeProfile(p)}>
                    {t(p.source === "edited" ? "settings.reset" : "settings.delete")}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-3">
          <Button variant="secondary" icon={<Plus className="size-4" aria-hidden />}
                  onClick={() => profiles[0] && setEditing({ profile: { ...profiles[0], name: "", label: "", source: "user" }, isNew: true })}>
            {t("settings.newProfile")}
          </Button>
        </div>
        {editing && (
          <ProfileEditor initial={editing.profile} isNew={editing.isNew} onClose={() => setEditing(null)}
                         onSaved={(p) => { setEditing(null); reloadProfiles(); toast(t("settings.profileSaved"), p.name); }} />
        )}
      </Section>

      <Section title={t("settings.system")} intro={t("settings.systemIntro")}>
        {system && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted">{t("settings.backend")}</dt><dd className="mono text-ink">{system.backend}</dd>
            <dt className="text-muted">{t("hud.paths")}</dt>
            <dd className="mono text-ink">{t("hud.decode")} {system.paths.decode}, {t("hud.scale")} {system.paths.scale}, {t("hud.tonemap")} {system.paths.tonemap}</dd>
            <dt className="text-muted">CPU</dt><dd className="mono text-ink">{system.system.cpu}</dd>
            <dt className="text-muted">GPU</dt><dd className="mono text-ink">{system.system.gpus.map((g) => g.name).join(", ") || "—"}</dd>
            <dt className="text-muted">ffmpeg</dt><dd className="mono text-ink">{system.ffmpeg?.version ?? "—"}</dd>
          </dl>
        )}
      </Section>
    </div>
  );
}
