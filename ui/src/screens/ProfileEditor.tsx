import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api, type Profile, type RuleInfo } from "../api/client";
import { Button } from "../design-system/Button";
import { Modal, Segmented, Switch } from "../design-system/Controls";

// Order and wording follow what people pick by: editing codecs first, then light long-GOP files.
const CODECS = ["dnxhr_hq", "dnxhr_hqx", "prores_422", "auto_h264", "auto_hevc", "libx264", "libx265",
  "h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv"] as const;
// Intra-frame editing codecs carry PCM audio, which MP4 cannot hold (the API refuses the pair as well).
const INTRA = new Set(["dnxhr_hq", "dnxhr_hqx", "prores_422"]);
const LONG_SIDES = [1280, 1920, 2560, 3840, 7680, 99999];
const RATES = ["44100", "48000", "96000"] as const;

const field = "h-10 w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 text-[13px] text-ink outline-none focus:border-[var(--accent-2)] disabled:opacity-60";

function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm text-ink">{label}</label>
      {children}
      {hint && <p className="text-xs text-faint">{hint}</p>}
    </div>
  );
}

/** Editor for one profile (CLAUDE.md §9, screen 6). The API validates again and has the last word. */
export function ProfileEditor({ initial, isNew, onClose, onSaved }: {
  initial: Profile | null;
  isNew: boolean;
  onClose: () => void;
  onSaved: (p: Profile) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [draft, setDraft] = useState<Profile | null>(initial);
  const [rules, setRules] = useState<RuleInfo[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { setDraft(initial); setError(""); }, [initial]);
  useEffect(() => { api.rules().then(setRules).catch(() => {}); }, []);

  if (!draft) return null;
  const set = (patch: Partial<Profile>) => setDraft({ ...draft, ...patch });
  const setOut = (patch: Partial<Profile["output"]>) => setDraft({ ...draft, output: { ...draft.output, ...patch } });
  const toggleRule = (rule: string, on: boolean) => setDraft({
    ...draft,
    rules: { ...draft.rules, disabled: on ? draft.rules.disabled.filter((r) => r !== rule) : [...draft.rules.disabled, rule] },
  });
  const containerClash = INTRA.has(draft.output.codec) && draft.output.container === "mp4";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await api.saveProfile(draft));
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open wide onOpenChange={(open) => !open && onClose()}
           title={isNew ? t("profileEditor.titleNew") : t("profileEditor.title", { name: draft.name })}
           description={t("profileEditor.intro")}>
      <form id={`${id}-form`} onSubmit={submit} className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("profileEditor.name")} hint={isNew ? t("profileEditor.nameHint") : undefined} htmlFor={`${id}-name`}>
            <input id={`${id}-name`} className={`mono ${field}`} value={draft.name} disabled={!isNew} required
                   pattern="[a-z0-9][a-z0-9\-]{0,39}" onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field label={t("profileEditor.label")} htmlFor={`${id}-label`}>
            <input id={`${id}-label`} className={field} value={draft.label} required onChange={(e) => set({ label: e.target.value })} />
          </Field>
          <Field label={t("profileEditor.fps")} hint={t("profileEditor.fpsHint")} htmlFor={`${id}-fps`}>
            <input id={`${id}-fps`} type="number" min={1} max={240} step="any" className={`mono tabular ${field}`}
                   value={draft.fps} onChange={(e) => set({ fps: Number(e.target.value) })} />
          </Field>
          <Field label={t("profileEditor.longSide")} htmlFor={`${id}-size`}>
            <select id={`${id}-size`} className={`mono ${field}`} value={draft.max_long_side}
                    onChange={(e) => set({ max_long_side: Number(e.target.value) })}>
              {[...new Set([...LONG_SIDES, draft.max_long_side])].sort((a, b) => a - b).map((v) => (
                <option key={v} value={v}>{v >= 99999 ? t("profileEditor.noLimit") : `${v} px`}</option>
              ))}
            </select>
          </Field>
        </div>

        <div className="space-y-1.5">
          <span className="block text-sm text-ink">{t("profileEditor.audioRate")}</span>
          <Segmented label={t("profileEditor.audioRate")} value={String(draft.audio_rate) as (typeof RATES)[number]}
                     onChange={(v) => set({ audio_rate: Number(v) })}
                     options={RATES.map((r) => ({ value: r, label: `${Number(r) / 1000} kHz` }))} />
        </div>

        <div className="grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
          <Field label={t("profileEditor.codec")} hint={t(`profileEditor.codecHint.${draft.output.codec}`, { defaultValue: "" }) || undefined}
                 htmlFor={`${id}-codec`}>
            <select id={`${id}-codec`} className={`mono ${field}`} value={draft.output.codec}
                    onChange={(e) => setOut({ codec: e.target.value, ...(INTRA.has(e.target.value) && draft.output.container === "mp4" ? { container: "mov" as const } : {}) })}>
              {CODECS.map((c) => <option key={c} value={c}>{t(`profileEditor.codecName.${c}`, { defaultValue: c })}</option>)}
            </select>
          </Field>
          <div className="space-y-1.5">
            <span className="block text-sm text-ink">{t("profileEditor.container")}</span>
            <Segmented label={t("profileEditor.container")} value={draft.output.container}
                       onChange={(v) => setOut({ container: v })}
                       options={(["mov", "mp4", "mkv"] as const).map((c) => ({ value: c, label: c.toUpperCase() }))} />
            {containerClash && <p className="text-xs text-[var(--human)]">{t("profileEditor.containerClash")}</p>}
          </div>
          <Field label={t("profileEditor.folder")} hint={t("profileEditor.folderHint")} htmlFor={`${id}-folder`}>
            <input id={`${id}-folder`} className={`mono ${field}`} value={draft.output.folder} required
                   onChange={(e) => setOut({ folder: e.target.value })} />
          </Field>
          <Field label={t("profileEditor.suffix")} hint={t("profileEditor.suffixHint")} htmlFor={`${id}-suffix`}>
            <input id={`${id}-suffix`} className={`mono ${field}`} value={draft.output.suffix}
                   onChange={(e) => setOut({ suffix: e.target.value })} />
          </Field>
        </div>

        <fieldset className="border-t border-line pt-4">
          <legend className="text-sm text-ink">{t("profileEditor.rules")}</legend>
          <p className="mt-1 text-xs text-faint">{t("profileEditor.rulesHint")}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {rules.map((r) => {
              const on = !draft.rules.disabled.includes(r.id);
              return (
                <label key={r.id} className="flex items-center gap-2 text-[13px] text-ink">
                  <input type="checkbox" checked={on} onChange={(e) => toggleRule(r.id, e.target.checked)}
                         className="size-4 accent-[var(--accent-2)]" />
                  <span className="mono">{r.id}</span>
                </label>
              );
            })}
          </div>
          <div className="mt-4">
            <Switch checked={draft.rules.vfr_deep_check} onChange={(v) => set({ rules: { ...draft.rules, vfr_deep_check: v } })}
                    label={t("profileEditor.deep")} description={t("profileEditor.deepHint")} />
          </div>
        </fieldset>

        {error && (
          <p role="alert" className="rounded-[var(--radius-control)] border border-[var(--error)] px-3 py-2 text-sm text-ink">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>{t("profileEditor.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={busy || containerClash}>{t("profileEditor.save")}</Button>
        </div>
      </form>
    </Modal>
  );
}
