import { KeyRound, PlugZap, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type AssistantStatus, type OllamaModel } from "../api/client";
import { Button } from "../design-system/Button";
import { Switch } from "../design-system/Controls";
import { useToast } from "./toast";

const field = "h-10 w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 text-[13px] text-ink outline-none focus:border-[var(--accent-2)]";

function gb(bytes: number): string {
  return bytes ? `${(bytes / 2 ** 30).toFixed(1)} GB` : "";
}

/** Settings → Assistant (#27): which Ollama server, which model, the access key. Nothing is sent anywhere until a
 *  person turns it on. */
export function AssistantSettings() {
  const { t } = useTranslation();
  const toast = useToast();
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [url, setUrl] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [models, setModels] = useState<OllamaModel[] | null>(null);
  const [version, setVersion] = useState("");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.assistant().then((s) => { setStatus(s); setUrl(s.url); setModel(s.model); }).catch(() => {});
  }, []);

  const test = async () => {
    setTesting(true);
    try {
      const r = await api.testAssistant(url.trim(), key || undefined);
      setModels(r.models);
      setVersion(r.version);
      if (!model && r.models.length) setModel(r.models.find((m) => !m.cloud)?.name ?? r.models[0].name);
      toast(t("assistantSettings.connected", { version: r.version }), t("assistantSettings.modelsFound", { count: r.models.length }));
    } catch (e) {
      setModels(null);
      toast(t("assistantSettings.testFailed"), e instanceof Error ? e.message : String(e));
    } finally { setTesting(false); }
  };

  const save = async (enabled: boolean, newKey?: string) => {
    setSaving(true);
    try {
      const s = await api.saveAssistant({ enabled, url: url.trim(), model: model.trim(), key: newKey });
      setStatus(s);
      setKey("");
      toast(t("settings.saved"));
    } catch (e) {
      toast(t("settings.saveFailed"), e instanceof Error ? e.message : String(e));
    } finally { setSaving(false); }
  };

  if (!status) return null;
  const chosen = models?.find((m) => m.name === model);

  return (
    <div className="space-y-5">
      <Switch checked={status.enabled} onChange={(v) => save(v, key || undefined)}
              label={t("assistantSettings.enable")} description={t("assistantSettings.enableHint")} />

      <div className="grid gap-4 border-t border-line pt-4 md:grid-cols-2">
        <label className="block text-sm text-ink">
          {t("assistantSettings.url")}
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://ollama.example.com"
                 className={`mono mt-1 ${field}`} spellCheck={false} autoComplete="off" />
        </label>
        <label className="block text-sm text-ink">
          {t("assistantSettings.key")}
          <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off"
                 placeholder={status.has_key ? t("assistantSettings.keyStored") : t("assistantSettings.keyNone")}
                 className={`mono mt-1 ${field}`} />
          <span className="mt-1 block text-xs text-faint">{t("assistantSettings.keyHint")}</span>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" loading={testing} disabled={!url.trim()} icon={<PlugZap className="size-4" aria-hidden />}
                onClick={test}>{t("assistantSettings.test")}</Button>
        {version && <span className="text-xs text-muted">{t("assistantSettings.connected", { version })}</span>}
      </div>

      <label className="block text-sm text-ink">
        {t("assistantSettings.model")}
        {models ? (
          <select value={model} onChange={(e) => setModel(e.target.value)} className={`mono mt-1 ${field}`}>
            {!models.some((m) => m.name === model) && <option value={model}>{model || "—"}</option>}
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}{m.parameters ? `, ${m.parameters}` : ""}{m.size ? `, ${gb(m.size)}` : ""}{m.vision ? `, ${t("assistantSettings.vision")}` : ""}{m.cloud ? `, ${t("assistantSettings.cloud")}` : ""}
              </option>
            ))}
          </select>
        ) : (
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="qwen3.6:27b" className={`mono mt-1 ${field}`} spellCheck={false} />
        )}
        <span className="mt-1 block text-xs text-faint">{t("assistantSettings.modelHint")}</span>
        {chosen?.cloud && <span className="mt-1 block text-xs text-human">{t("assistantSettings.cloudWarning")}</span>}
      </label>

      <div className="flex flex-wrap gap-2 border-t border-line pt-4">
        <Button variant="primary" loading={saving} icon={<KeyRound className="size-4" aria-hidden />}
                onClick={() => save(status.enabled, key || undefined)}>{t("assistantSettings.save")}</Button>
        {status.has_key && (
          <Button variant="ghost" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => save(status.enabled, "")}>
            {t("assistantSettings.removeKey")}
          </Button>
        )}
      </div>
    </div>
  );
}
