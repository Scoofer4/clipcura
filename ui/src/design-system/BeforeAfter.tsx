import { useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Same frame before and after the fix, split by a vertical handle. The handle is a real range input, so it
 * works with the keyboard (arrow keys) and screen readers, not only with a mouse.
 */
export function BeforeAfter({ before, after, aspect }: { before: string; after: string; aspect: number }) {
  const { t } = useTranslation();
  const [split, setSplit] = useState(50);
  return (
    <div className="relative overflow-hidden rounded-[var(--radius-control)] border border-line bg-bg-deep"
         style={{ aspectRatio: String(aspect) }}>
      <img src={after} alt={t("detail.after")} className="absolute inset-0 h-full w-full object-contain" />
      <img src={before} alt={t("detail.before")} className="absolute inset-0 h-full w-full object-contain"
           style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }} />
      <div className="pointer-events-none absolute inset-y-0 w-px bg-white/85 shadow-[0_0_0_1px_rgb(0_0_0/0.25)]"
           style={{ left: `${split}%` }} aria-hidden>
        <span className="absolute top-1/2 size-7 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/80 bg-black/45 backdrop-blur" />
      </div>
      <span className="mono absolute left-2 top-2 rounded bg-black/55 px-1.5 py-0.5 text-[11px] text-white">{t("detail.before")}</span>
      <span className="mono absolute right-2 top-2 rounded bg-black/55 px-1.5 py-0.5 text-[11px] text-white">{t("detail.after")}</span>
      <input type="range" min={0} max={100} value={split} onChange={(e) => setSplit(Number(e.target.value))}
             aria-label={t("detail.compare")} className="absolute inset-0 h-full w-full cursor-ew-resize opacity-0" />
    </div>
  );
}
