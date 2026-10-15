import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button, cx } from "./primitives";

export function Modal({ open, onClose, title, children, footer, width = "md" }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; width?: "sm" | "md" | "lg";
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input,select,textarea,button")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-ink/30 p-4 pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className={cx("w-full rounded-lg border border-line bg-surface shadow-lg", width === "sm" ? "max-w-sm" : width === "md" ? "max-w-xl" : "max-w-3xl")}>
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button aria-label="Close" onClick={onClose} className="rounded p-1 text-ink-3 hover:bg-canvas"><X className="size-4" /></button>
        </header>
        <div className="px-4 py-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel = "Confirm", danger, loading, onConfirm, onCancel }: {
  open: boolean; title: string; message: ReactNode; confirmLabel?: string; danger?: boolean; loading?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <Modal open={open} onClose={onCancel} title={title} width="sm"
      footer={<>
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>{confirmLabel}</Button>
      </>}>
      <div className="text-ink-2">{message}</div>
    </Modal>
  );
}
