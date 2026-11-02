import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  loading?: boolean;
  /** Keyboard shortcut shown inside the button, e.g. "F". */
  kbd?: string;
}

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-5 text-[15px] gap-2.5",
};

const variants: Record<Variant, string> = {
  // The primary action is the only element allowed to carry the accent gradient and its glow.
  primary:
    "text-[var(--accent-ink)] [background:var(--accent-solid)] shadow-[0_8px_24px_-10px_var(--accent-glow)] " +
    "hover:shadow-[0_10px_32px_-8px_var(--accent-glow)] hover:brightness-110",
  secondary: "bg-raised text-ink border border-line hover:border-line-strong",
  ghost: "text-muted hover:text-ink hover:bg-surface",
  danger: "text-error border border-[color-mix(in_srgb,var(--error)_45%,transparent)] hover:bg-[color-mix(in_srgb,var(--error)_10%,transparent)]",
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = "secondary", size = "md", icon, loading, kbd, children, className = "", disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={
        "inline-flex select-none items-center justify-center rounded-[var(--radius-control)] font-medium " +
        "transition-[box-shadow,filter,background-color,border-color,color] duration-[var(--dur-fast)] " +
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none disabled:hover:brightness-100 " +
        `${sizes[size]} ${variants[variant]} ${className}`
      }
      {...rest}
    >
      {loading ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
      {kbd && (
        <kbd className="mono ml-1 rounded-[5px] border border-current/25 px-1.5 text-[11px] leading-5 opacity-75">
          {kbd}
        </kbd>
      )}
    </button>
  );
});
