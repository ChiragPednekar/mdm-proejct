import { forwardRef, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { Search } from "lucide-react";
import { cx } from "./primitives";

const control = "h-8 rounded-md border border-line-strong bg-surface px-2.5 text-[13px] text-ink placeholder:text-ink-4 focus:border-accent focus:outline-none disabled:bg-canvas aria-[invalid=true]:border-bad";

/** Full width unless the caller supplies its own width utility. */
const width = (className?: string) => (/(^|\s)(max-)?w-/.test(className ?? "") ? "" : "w-full");

export function Field({ label, error, hint, children, htmlFor, required }: {
  label: string; error?: string; hint?: ReactNode; children: ReactNode; htmlFor?: string; required?: boolean;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-ink-2">
        {label}{required && <span className="text-bad"> *</span>}
      </label>
      {children}
      {error ? <p role="alert" className="mt-1 text-[11px] text-bad">{error}</p> : hint ? <p className="mt-1 text-[11px] text-ink-3">{hint}</p> : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} {...p} className={cx(control, width(className), className)} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...p }, ref) {
  return <select ref={ref} {...p} className={cx(control, width(className), "pr-7", className)}>{children}</select>;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} {...p} className={cx(control, width(className), "h-auto min-h-[72px] py-1.5", className)} />;
});

export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: string }>(function Checkbox({ label, ...p }, ref) {
  return (
    <label className="inline-flex items-center gap-2 text-[13px] text-ink-2">
      <input ref={ref} type="checkbox" {...p} className="size-3.5 accent-[var(--color-accent)]" />
      {label}
    </label>
  );
});

export function SearchInput({ value, onChange, placeholder = "Search…", className }: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string }) {
  return (
    <div className={cx("relative", className)}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-4" />
      <input aria-label={placeholder} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={cx(control, "w-full pl-8")} />
    </div>
  );
}

/** Small labelled select used in filter bars. */
export function FilterSelect({ label, value, onChange, options, allLabel = "All" }: {
  label: string; value: string; onChange: (v: string) => void; options: (string | { value: string; label: string })[]; allLabel?: string;
}) {
  return (
    <Select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="w-auto min-w-[130px]">
      <option value="">{label}: {allLabel}</option>
      {options.map((o) => typeof o === "string"
        ? <option key={o} value={o}>{o}</option>
        : <option key={o.value} value={o.value}>{o.label}</option>)}
    </Select>
  );
}

export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">{children}</div>;
}
