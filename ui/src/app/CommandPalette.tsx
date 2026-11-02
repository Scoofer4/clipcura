import * as Dialog from "@radix-ui/react-dialog";
import { Search } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  run: () => void;
}

/** Ctrl+K: every main action reachable by typing a few letters (CLAUDE.md §9). */
export function CommandPalette({ commands, open, onOpenChange }: {
  commands: Command[];
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? commands.filter((c) => `${c.label} ${c.hint ?? ""}`.toLowerCase().includes(q)) : commands;
  }, [commands, query]);

  useEffect(() => { setActive(0); }, [query, open]);
  useEffect(() => { if (!open) setQuery(""); }, [open]);

  const run = (c: Command | undefined) => {
    if (!c) return;
    onOpenChange(false);
    c.run();
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px]" />
        <Dialog.Content
          className="glass fixed left-1/2 top-[18vh] z-50 w-[min(92vw,560px)] -translate-x-1/2 overflow-hidden bg-solid"
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, matches.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            if (e.key === "Enter") { e.preventDefault(); run(matches[active]); }
          }}
        >
          <Dialog.Title className="sr-only">{t("palette.title")}</Dialog.Title>
          <div className="flex items-center gap-3 border-b border-line px-4">
            <Search className="size-4 text-faint" aria-hidden />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("palette.placeholder")}
              aria-label={t("palette.placeholder")}
              role="combobox"
              aria-expanded
              aria-controls="palette-list"
              aria-activedescendant={matches[active] ? `cmd-${matches[active].id}` : undefined}
              className="h-12 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-faint"
            />
            <kbd className="mono rounded border border-line px-1.5 text-[11px] text-faint">Esc</kbd>
          </div>
          <ul id="palette-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
            {matches.length === 0 && <li className="px-3 py-6 text-center text-sm text-faint">{t("palette.empty")}</li>}
            {matches.map((c, i) => (
              <li key={c.id} id={`cmd-${c.id}`} role="option" aria-selected={i === active}
                  onMouseEnter={() => setActive(i)} onClick={() => run(c)}
                  className="flex cursor-pointer items-center gap-3 rounded-[8px] px-3 py-2.5 text-sm text-ink aria-selected:bg-[var(--accent-soft)]">
                <span className="text-muted">{c.icon}</span>
                <span className="flex-1">{c.label}</span>
                {c.hint && <span className="mono truncate text-xs text-faint">{c.hint}</span>}
              </li>
            ))}
          </ul>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
