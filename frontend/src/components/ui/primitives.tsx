import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import type { ApiError } from "../../lib/api";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
export function Button({
  variant = "secondary", size = "md", loading, icon, children, className, disabled, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-white hover:bg-accent-hover border border-accent",
    secondary: "bg-surface text-ink border border-line-strong hover:bg-canvas",
    ghost: "text-ink-2 hover:bg-canvas border border-transparent",
    danger: "bg-surface text-bad border border-line-strong hover:bg-bad-soft",
  };
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-[13px]",
        styles[variant], className,
      )}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" /> : icon}
      {children}
    </button>
  );
}

const TONES = {
  neutral: "bg-canvas text-ink-2 ring-line-strong",
  accent: "bg-accent-soft text-accent ring-accent/25",
  ok: "bg-ok-soft text-ok ring-ok/20",
  warn: "bg-warn-soft text-warn ring-warn/25",
  bad: "bg-bad-soft text-bad ring-bad/20",
  info: "bg-info-soft text-info ring-info/20",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded px-1.5 py-px text-[11px] font-medium ring-1 ring-inset whitespace-nowrap", TONES[tone])}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  Open: "info", Assigned: "info", "In Progress": "warn", Resolved: "ok", Closed: "neutral", Cancelled: "neutral",
  Active: "ok", Expired: "neutral", Pending: "info", Voided: "bad", None: "neutral",
  "Under Repair": "warn", Replaced: "neutral", Retired: "neutral",
  Fixed: "ok", "Partially Fixed": "warn", "Not Fixed": "bad", "Unit Replaced": "info", Referred: "neutral",
  Low: "ok", Medium: "warn", High: "bad", Critical: "bad", Major: "warn", Moderate: "neutral", Minor: "neutral",
  Completed: "ok", Failed: "bad", "Insufficient Data": "warn", Running: "info",
  "On Leave": "warn", Inactive: "neutral",
};
export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-ink-4">—</span>;
  return <Badge tone={STATUS_TONE[value] ?? "neutral"}>{value}</Badge>;
}

export function Card({ title, actions, children, className, bodyClass, subtitle }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            <h2 className="text-[13px] font-semibold">{title}</h2>
            {subtitle && <p className="text-xs text-ink-3">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx(bodyClass ?? "p-4")}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 max-w-3xl text-ink-3">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-ink-3">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function EmptyState({ title = "Nothing here yet", hint, action }: { title?: string; hint?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 py-10 text-center">
      <Inbox className="size-5 text-ink-4" />
      <p className="font-medium text-ink-2">{title}</p>
      {hint && <p className="max-w-md text-xs text-ink-3">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError | Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <AlertTriangle className="size-5 text-bad" />
      <p className="font-medium text-ink">Could not load data</p>
      <p className="max-w-md text-xs text-ink-3">{error.message}</p>
      {onRetry && <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={onRetry}>Retry</Button>}
    </div>
  );
}

/** Render loading / error / content for an async state. */
export function Async<T>({ state, children, empty }: {
  state: { data: T | undefined; error: ApiError | null; loading: boolean; reload: () => void };
  children: (data: T) => ReactNode;
  empty?: (data: T) => boolean;
}) {
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (state.data === undefined) return <Spinner />;
  if (empty?.(state.data)) return <EmptyState />;
  return <>{children(state.data)}</>;
}

export function StatTile({ label, value, sub, title, tone }: { label: string; value: ReactNode; sub?: ReactNode; title?: string; tone?: "bad" | "warn" }) {
  return (
    <div title={title} className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-xs font-medium text-ink-3">{label}</p>
      <p className={cx("mt-1 text-xl font-semibold tabular", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-ink-3">{sub}</p>}
    </div>
  );
}

export function KeyValue({ items, cols = 2 }: { items: [ReactNode, ReactNode][]; cols?: 1 | 2 | 3 }) {
  return (
    <dl className={cx("grid gap-x-6 gap-y-2.5", cols === 1 ? "grid-cols-1" : cols === 2 ? "grid-cols-2" : "grid-cols-3")}>
      {items.map(([k, v], i) => (
        <div key={i} className="min-w-0">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-ink-4">{k}</dt>
          <dd className="mt-0.5 truncate text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("-mb-px border-b-2 px-3 py-2 text-[13px] font-medium",
            value === t.id ? "border-accent text-ink" : "border-transparent text-ink-3 hover:text-ink")}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function DemoNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start gap-2 rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-xs text-warn">
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
      <span>{children ?? "Demonstration model trained on synthetic data. Probabilities and metrics are illustrative, not validated real-world results."}</span>
    </div>
  );
}
