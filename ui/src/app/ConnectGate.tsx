import { KeyRound } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { hasToken, setToken } from "../api/client";
import { Button } from "../design-system/Button";
import { Lockup } from "../design-system/Logo";
import { Panel } from "../design-system/Panel";

/**
 * Without a token the API answers nothing, so explain how to open Clipcura properly instead of showing a
 * broken app. The desktop window and `clipcura open` pass the token in the URL fragment automatically.
 */
export function ConnectGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [ready, setReady] = useState(hasToken());
  const [value, setValue] = useState("");
  if (ready) return <>{children}</>;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim()) { setToken(value.trim()); setReady(true); }
  };
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <Panel className="w-full max-w-[520px] p-8">
        <Lockup size={34} />
        <h1 className="mt-6 text-xl font-semibold text-ink">{t("connect.title")}</h1>
        <p className="mt-2 text-sm text-muted">{t("connect.body")}</p>
        <pre className="mono mt-4 rounded-[var(--radius-control)] border border-line bg-surface p-3 text-[13px] text-ink">clipcura open</pre>
        <form onSubmit={submit} className="mt-6 flex gap-2">
          <label htmlFor="token" className="sr-only">{t("connect.token")}</label>
          <input id="token" type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off"
                 placeholder={t("connect.token")}
                 className="mono h-10 min-w-0 flex-1 rounded-[var(--radius-control)] border border-line bg-surface px-3 text-[13px] text-ink outline-none focus:border-[var(--accent-2)]" />
          <Button type="submit" icon={<KeyRound className="size-4" aria-hidden />}>{t("connect.connect")}</Button>
        </form>
      </Panel>
    </div>
  );
}
