import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { LiveToast, ToastProvider, ToastViewport } from "../design-system/Controls";

interface ToastMsg { id: number; title: string; description?: string }
const Ctx = createContext<(title: string, description?: string) => void>(() => {});

let next = 1;

/** App-wide notifications. The action name and the toast use the same words ("Fix" -> "Fixed"). */
export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastMsg[]>([]);
  const show = useCallback((title: string, description?: string) => {
    setItems((list) => [...list.slice(-3), { id: next++, title, description }]);
  }, []);
  return (
    <Ctx.Provider value={show}>
      <ToastProvider swipeDirection="right">
        {children}
        {items.map((m) => (
          <LiveToast key={m.id} open title={m.title} description={m.description}
                     onOpenChange={(o) => !o && setItems((list) => list.filter((x) => x.id !== m.id))} />
        ))}
        <ToastViewport />
      </ToastProvider>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
