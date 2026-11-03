import type { ReactNode } from "react";
import { CircleCheck, CircleX, Hand, Wrench } from "lucide-react";
import { motion } from "framer-motion";
import type { FileStatus } from "./Chip";
import { AnimatedNumber } from "./Motion";

export function Panel({ children, className = "", as: Tag = "section", id }: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
  id?: string;
}) {
  return <Tag id={id} className={`glass ${className}`}>{children}</Tag>;
}

const tone: Record<FileStatus, { color: string; Icon: typeof CircleCheck }> = {
  ok: { color: "var(--ok)", Icon: CircleCheck },
  fixable: { color: "var(--fixable)", Icon: Wrench },
  needs_human: { color: "var(--human)", Icon: Hand },
  error: { color: "var(--error)", Icon: CircleX },
};

/** Summary of a scan: the count is the content, so it gets the size; the label explains it. */
export function StatCard({ status, count, label, hint, active, onClick }: {
  status: FileStatus;
  count: number;
  label: string;
  hint: string;
  active?: boolean;
  onClick?: () => void;
}) {
  const { color, Icon } = tone[status];
  return (
    <motion.button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      whileTap={{ scale: 0.985 }}
      className="glass group relative h-full w-full overflow-hidden p-4 text-left transition-[border-color] duration-[var(--dur-fast)] hover:border-line-strong aria-pressed:border-line-strong"
    >
      {/* Coloured rail on the left edge, like a channel strip meter. */}
      <span className="absolute inset-y-3 left-0 w-[3px] rounded-r" style={{ background: color }} aria-hidden />
      <div className="flex items-center gap-2 text-sm text-muted">
        <Icon className="size-4" style={{ color }} aria-hidden />
        {label}
      </div>
      <div className="tabular mt-2 text-[40px] font-semibold leading-none tracking-tight text-ink">
        <AnimatedNumber value={count} />
      </div>
      <div className="mt-2 text-xs text-faint">{hint}</div>
    </motion.button>
  );
}
