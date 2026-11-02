import * as ToggleGroup from "@radix-ui/react-toggle-group";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as Dialog from "@radix-ui/react-dialog";
import * as Toast from "@radix-ui/react-toast";
import { AnimatePresence, motion } from "framer-motion";
import { CircleCheck, X } from "lucide-react";
import type { ReactNode } from "react";

/** Segmented control (profile picker, theme, accent). Arrow keys move between options. */
export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; hint?: string }[];
  label: string;
}) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v as T)}
      aria-label={label}
      className="inline-flex rounded-[var(--radius-control)] border border-line bg-surface p-1"
    >
      {options.map((o) => (
        <ToggleGroup.Item
          key={o.value}
          value={o.value}
          title={o.hint}
          className="relative h-8 rounded-[7px] px-3 text-[13px] text-muted transition-colors duration-[var(--dur-fast)] hover:text-ink data-[state=on]:text-ink"
        >
          {value === o.value && (
            <motion.span
              layoutId={`seg-${label}`}
              className="absolute inset-0 rounded-[7px] border border-line-strong bg-raised"
              transition={{ type: "spring", stiffness: 520, damping: 38 }}
            />
          )}
          <span className="relative">{o.label}</span>
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

export function Switch({ checked, onChange, label, description }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-6">
      <span>
        <span className="block text-sm text-ink">{label}</span>
        {description && <span className="block text-xs text-faint">{description}</span>}
      </span>
      <SwitchPrimitive.Root
        checked={checked}
        onCheckedChange={onChange}
        className="relative mt-0.5 h-6 w-10 shrink-0 rounded-full border border-line bg-[var(--line)] transition-colors duration-[var(--dur-fast)] data-[state=checked]:border-transparent data-[state=checked]:[background:var(--accent-solid)]"
      >
        <SwitchPrimitive.Thumb className="block size-[18px] translate-x-[2px] rounded-full bg-white shadow transition-transform duration-[var(--dur-fast)] data-[state=checked]:translate-x-[18px]" />
      </SwitchPrimitive.Root>
    </label>
  );
}

export function Modal({ open, onOpenChange, title, description, children, footer }: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild>
              <motion.div className="fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px]"
                          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
            </Dialog.Overlay>
            <Dialog.Content asChild>
              <motion.div
                className="glass fixed left-1/2 top-1/2 z-50 w-[min(92vw,520px)] -translate-x-1/2 -translate-y-1/2 bg-solid p-6"
                initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.97 }}
                transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
              >
                <Dialog.Title className="text-lg font-semibold text-ink">{title}</Dialog.Title>
                {description && <Dialog.Description className="mt-1 text-sm text-muted">{description}</Dialog.Description>}
                <div className="mt-4">{children}</div>
                {footer && <div className="mt-6 flex justify-end gap-2">{footer}</div>}
                <Dialog.Close className="absolute right-3 top-3 rounded-md p-1.5 text-muted hover:bg-surface hover:text-ink" aria-label="Close">
                  <X className="size-4" aria-hidden />
                </Dialog.Close>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}

/** Visual of a toast, shared by the live Radix toast and the static kitchen-sink sample. */
export function ToastBody({ title, description, icon }: { title: string; description?: string; icon?: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 text-ok">{icon ?? <CircleCheck className="size-5" aria-hidden />}</span>
      <div>
        <div className="text-sm font-medium text-ink">{title}</div>
        {description && <div className="mono mt-0.5 text-xs text-muted">{description}</div>}
      </div>
    </div>
  );
}

export function LiveToast({ open, onOpenChange, title, description }: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description?: string;
}) {
  return (
    <Toast.Root open={open} onOpenChange={onOpenChange} duration={4000}
                className="glass w-[360px] bg-solid p-4 data-[state=open]:animate-[toast-in_var(--dur-base)_var(--ease-out)]">
      <Toast.Title asChild><div><ToastBody title={title} description={description} /></div></Toast.Title>
    </Toast.Root>
  );
}

export const ToastProvider = Toast.Provider;
export const ToastViewport = () => (
  <Toast.Viewport className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 outline-none" />
);
