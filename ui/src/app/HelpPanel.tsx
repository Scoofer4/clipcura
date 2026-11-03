import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "framer-motion";
import { Lightbulb, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export type HelpScreen = "start" | "results" | "jobs" | "activity" | "log" | "settings" | "about";

interface Key { key: string; does: string }

/** Which help belongs to the current route. */
export function helpScreenFor(pathname: string): HelpScreen {
  if (pathname.startsWith("/scans/")) return "results";
  const first = pathname.split("/")[1] as HelpScreen;
  return (["jobs", "activity", "log", "settings", "about"] as const).includes(first as never) ? first : "start";
}

function Keys({ items }: { items: Key[] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
      {items.map((k) => (
        <div key={k.key} className="contents">
          <dt><kbd className="mono rounded-md border border-line bg-surface px-1.5 py-0.5 text-[11px] text-ink">{k.key}</kbd></dt>
          <dd className="text-muted">{k.does}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Help for the screen on display (owner request 2026-11-03): what it is for, the steps in order, what is good to
 * know and the keys. A sheet from the right edge, so the screen it explains stays in view.
 */
export function HelpPanel({ screen, open, onOpenChange }: {
  screen: HelpScreen;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  const base = `help.screens.${screen}`;
  const steps = t(`${base}.steps`, { returnObjects: true, defaultValue: [] }) as string[];
  const tips = t(`${base}.tips`, { returnObjects: true, defaultValue: [] }) as string[];
  const keys = [
    ...(t(`${base}.keys`, { returnObjects: true, defaultValue: [] }) as Key[]),
    ...(t("help.global", { returnObjects: true }) as Key[]),
  ];

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild>
              <motion.div className="fixed inset-0 z-40 bg-black/35"
                          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
            </Dialog.Overlay>
            <Dialog.Content asChild aria-describedby={undefined}>
              <motion.aside
                className="glass fixed inset-y-3 right-3 z-50 flex w-[min(92vw,420px)] flex-col overflow-hidden bg-solid"
                initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
                transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
              >
                <header className="flex items-start gap-3 border-b border-line px-6 py-5">
                  <Dialog.Title className="flex-1 text-lg font-semibold text-ink">
                    {t("help.title", { screen: t(`${base}.name`) })}
                  </Dialog.Title>
                  <Dialog.Close className="rounded-md p-1.5 text-muted hover:bg-surface hover:text-ink" aria-label={t("help.close")}>
                    <X className="size-4" aria-hidden />
                  </Dialog.Close>
                </header>

                <div className="flex-1 space-y-7 overflow-y-auto px-6 py-6">
                  <section>
                    <h3 className="text-sm font-semibold text-ink">{t("help.purpose")}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-muted">{t(`${base}.purpose`)}</p>
                  </section>

                  {steps.length > 0 && (
                    <section>
                      <h3 className="text-sm font-semibold text-ink">{t("help.steps")}</h3>
                      {/* A real sequence, so the steps are numbered. */}
                      <ol className="mt-3 space-y-3">
                        {steps.map((step, i) => (
                          <li key={step} className="flex gap-3 text-sm leading-relaxed text-muted">
                            <span className="mono tabular mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-[var(--accent-ink)]"
                                  style={{ background: "var(--accent-solid)" }} aria-hidden>{i + 1}</span>
                            <span>{step}</span>
                          </li>
                        ))}
                      </ol>
                    </section>
                  )}

                  {tips.length > 0 && (
                    <section>
                      <h3 className="text-sm font-semibold text-ink">{t("help.tips")}</h3>
                      <ul className="mt-3 space-y-2.5">
                        {tips.map((tip) => (
                          <li key={tip} className="flex gap-2.5 text-sm leading-relaxed text-muted">
                            <Lightbulb className="mt-0.5 size-4 shrink-0 text-faint" aria-hidden />
                            <span>{tip}</span>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  <section>
                    <h3 className="text-sm font-semibold text-ink">{t("help.keys")}</h3>
                    <div className="mt-3"><Keys items={keys} /></div>
                  </section>
                </div>

                {screen !== "about" && (
                  <footer className="border-t border-line px-6 py-4">
                    <Link to="/about" onClick={() => onOpenChange(false)}
                          className="text-sm text-muted underline-offset-4 hover:text-ink hover:underline">
                      {t("help.about")}
                    </Link>
                  </footer>
                )}
              </motion.aside>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}
