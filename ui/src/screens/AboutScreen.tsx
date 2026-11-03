import { ExternalLink, FileText } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import uiComponents from "../about/ui-components.json";
import { api, type About, type Component } from "../api/client";
import { Button } from "../design-system/Button";
import { Modal } from "../design-system/Controls";
import { LogoMark } from "../design-system/Logo";
import { Panel } from "../design-system/Panel";

function Outbound({ href, children }: { href: string; children: ReactNode }) {
  // The desktop window hands target=_blank links to the default browser.
  return (
    <a href={href} target="_blank" rel="noreferrer"
       className="inline-flex items-center gap-1 text-ink underline decoration-[var(--line-strong)] underline-offset-4 hover:decoration-[var(--accent-2)]">
      {children}<ExternalLink className="size-3 text-faint" aria-hidden />
    </a>
  );
}

/** One block of the credits: a heading, a line on what it covers, then name | version | licence rows. */
function Credits({ title, intro, items }: { title: string; intro?: string; items: Component[] }) {
  const { t } = useTranslation();
  return (
    <section aria-label={title} className="border-t border-line pt-6">
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {intro && <p className="mt-1 text-sm text-muted">{intro}</p>}
      <table className="mt-4 w-full text-sm">
        <thead className="sr-only">
          <tr><th>{t("about.name")}</th><th>{t("about.version")}</th><th>{t("about.licence")}</th></tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.name} className="border-b border-line/60 last:border-0">
              <td className="py-2 pr-4 text-ink">
                {c.url ? <a href={c.url} target="_blank" rel="noreferrer" className="hover:underline">{c.name}</a> : c.name}
              </td>
              <td className="mono tabular py-2 pr-4 text-right text-xs text-faint">{c.version}</td>
              <td className="mono py-2 text-right text-xs text-muted">{c.licence}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** About Clipcura (owner request 2026-11-03): owner and creator first, then licence, authors and what it is built from. */
export function AboutScreen() {
  const { t } = useTranslation();
  const [about, setAbout] = useState<About | null>(null);
  const [error, setError] = useState("");
  const [noticesOpen, setNoticesOpen] = useState(false);
  const [notices, setNotices] = useState<string | null>(null);

  useEffect(() => { api.about().then(setAbout).catch((e: Error) => setError(e.message)); }, []);

  const openNotices = () => {
    setNoticesOpen(true);
    if (notices === null) api.notices().then(setNotices).catch((e: Error) => setNotices(t("about.loadFailed", { error: e.message })));
  };

  const owner = about?.owner.name ?? "Metaverse Media s.r.o.";
  const media = about?.components.filter((c) => c.kind === "media") ?? [];
  const python = about?.components.filter((c) => c.kind === "python") ?? [];

  return (
    <div className="mx-auto max-w-[880px]">
      {/* Title card: the one bold moment of the page, like the opening of a film. */}
      <Panel className="relative overflow-hidden px-8 pb-10 pt-12 text-center">
        <div className="pointer-events-none absolute inset-x-0 -top-24 mx-auto h-64 w-64 rounded-full opacity-40 blur-3xl"
             style={{ background: "radial-gradient(circle, var(--accent-2), transparent 70%)" }} aria-hidden />
        <div className="relative flex flex-col items-center">
          <LogoMark size={96} title="Clipcura" />
          <h1 className="mt-5 text-[44px] font-semibold leading-none tracking-[-0.04em] text-ink">Clipcura</h1>
          <p className="mt-3 text-[15px] text-muted">{t("about.tagline")}</p>
          <p className="mt-8 text-sm text-faint">{t("about.credit")}</p>
          <p className="mono tabular mt-2 text-xs text-faint">
            {t("about.version")} {about?.version ?? "…"}
          </p>
        </div>
      </Panel>

      {error && <p role="alert" className="mt-4 text-sm text-[var(--error)]">{t("about.loadFailed", { error })}</p>}

      <Panel className="mt-4 p-8">
        <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-[max-content_1fr]">
          <dt className="text-sm text-faint">{t("about.owner")}</dt>
          <dd>
            <p className="text-[17px] font-semibold text-ink">{owner}</p>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              {t("about.ownerBody", { owner, licence: about?.licence ?? "Apache-2.0" })}
            </p>
            {about && <p className="mt-2 text-sm"><Outbound href={about.owner.url}>{about.owner.url.replace(/^https?:\/\/(www\.)?/, "")}</Outbound></p>}
          </dd>

          <dt className="text-sm text-faint">{t("about.authors")}</dt>
          <dd className="text-sm text-muted">
            <p>{t("about.authorsBody", { owner })}</p>
            {about && <p className="mt-1"><Outbound href={`${about.source}/graphs/contributors`}>{t("about.contributors")}</Outbound></p>}
          </dd>

          <dt className="text-sm text-faint">{t("about.licence")}</dt>
          <dd className="text-sm">
            {about && <Outbound href={`${about.source}/blob/main/LICENSE`}>{about.licence}</Outbound>}
          </dd>

          <dt className="text-sm text-faint">{t("about.source")}</dt>
          <dd className="text-sm">{about && <Outbound href={about.source}>{about.source.replace(/^https:\/\//, "")}</Outbound>}</dd>

          <dt className="text-sm text-faint">{t("about.package")}</dt>
          <dd className="text-sm text-muted">
            {about && <>
              <p className="text-ink">{t(`about.kind.${about.install.kind}`)}</p>
              <p className="mt-1">{t("about.dataIn")} <span className="mono break-all text-xs">{about.install.data_dir}</span></p>
            </>}
          </dd>
        </dl>
      </Panel>

      <Panel className="mt-4 p-8">
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold tracking-tight text-ink">{t("about.builtWith")}</h2>
            <p className="mt-1 text-sm text-muted">{t("about.builtWithBody")}</p>
          </div>
          <Button onClick={openNotices} icon={<FileText className="size-4" aria-hidden />}>{t("about.licenceTexts")}</Button>
        </div>

        <div className="mt-6 space-y-8">
          {media.map((m) => (
            <section key={m.name} aria-label={t("about.media")} className="border-t border-line pt-6">
              <h3 className="text-base font-semibold text-ink">{t("about.media")}</h3>
              <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="text-[17px] font-semibold text-ink">{m.name}</span>
                <span className="mono tabular text-xs text-faint">{m.version}</span>
                <span className="mono text-xs text-muted">{m.licence}</span>
              </div>
              <p className="mt-2 text-sm text-muted">{t("about.ffmpegNote")}</p>
              <p className="mt-2 flex flex-wrap gap-4 text-sm">
                <Outbound href={m.url}>{t("about.website")}</Outbound>
                {m.source && <Outbound href={m.source}>{t("about.source")}</Outbound>}
              </p>
            </section>
          ))}
          <Credits title={t("about.service")} intro={t("about.serviceBody")} items={python} />
          <Credits title={t("about.interface")} intro={t("about.interfaceBody")} items={uiComponents as Component[]} />
        </div>
      </Panel>

      <p className="mt-6 pb-4 text-center text-xs text-faint">
        {t("about.copyright", { year: new Date().getFullYear(), owner })}
      </p>

      <Modal open={noticesOpen} onOpenChange={setNoticesOpen} wide title={t("about.licenceTextsTitle")}>
        <pre className="mono max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-[var(--radius-control)] border border-line bg-surface p-4 text-[11px] leading-relaxed text-muted">
          {notices ?? t("about.loading")}
        </pre>
      </Modal>
    </div>
  );
}
