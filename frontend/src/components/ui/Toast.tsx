import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, AlertCircle, X } from "lucide-react";
import { cx } from "./primitives";

type Toast = { id: number; kind: "success" | "error"; message: string };
const Ctx = createContext<{ push: (kind: Toast["kind"], message: string) => void } | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));
  const push = useCallback((kind: Toast["kind"], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, message }]);
    setTimeout(() => dismiss(id), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div aria-live="polite" className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role="status" className={cx("flex items-start gap-2 rounded-md border bg-surface px-3 py-2.5 shadow-md",
            t.kind === "success" ? "border-ok/30" : "border-bad/30")}>
            {t.kind === "success" ? <CheckCircle2 className="mt-px size-4 shrink-0 text-ok" /> : <AlertCircle className="mt-px size-4 shrink-0 text-bad" />}
            <p className="flex-1 text-[13px] text-ink">{t.message}</p>
            <button aria-label="Dismiss" onClick={() => dismiss(t.id)} className="text-ink-4 hover:text-ink"><X className="size-3.5" /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return {
    success: (m: string) => ctx.push("success", m),
    error: (e: unknown) => ctx.push("error", e instanceof Error ? e.message : String(e)),
  };
}
