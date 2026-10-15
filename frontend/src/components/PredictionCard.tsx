import { dateTime, prob } from "../lib/format";
import type { Prediction } from "../lib/types";
import { Badge, StatusBadge } from "./ui/primitives";

export function PredictionPanel({ p }: { p: Prediction }) {
  const max = Math.max(0.01, ...(p.explanation_details ?? []).map((c) => Math.abs(c.contribution)));
  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-ink-4">Failure probability · next {p.prediction_horizon_days} days</p>
          <p className="text-2xl font-semibold tabular">{prob(p.failure_probability)}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <StatusBadge value={p.risk_level} />
          {p.model_classification === "demonstration"
            ? <Badge tone="warn" title="Trained on synthetic demonstration data">Demonstration model</Badge>
            : <Badge tone="ok">Validated model</Badge>}
        </div>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-canvas" aria-hidden>
        <div className={`h-full ${p.risk_level === "High" ? "bg-bad" : p.risk_level === "Medium" ? "bg-warn" : "bg-accent"}`}
          style={{ width: `${Math.max(2, p.failure_probability * 100)}%` }} />
      </div>
      {p.explanation_details && p.explanation_details.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-ink-4">Contributing factors <span className="normal-case tracking-normal">(percentage points)</span></p>
          <ul className="space-y-1.5">
            {p.explanation_details.map((c) => (
              <li key={c.feature} className="grid grid-cols-[1fr_90px_64px] items-center gap-2 text-xs">
                <span className="truncate text-ink-2" title={`Typical value: ${String(c.typical_value)}`}>
                  {c.label} <span className="text-ink-4">= {typeof c.value === "number" ? Math.round(c.value * 100) / 100 : String(c.value ?? "n/a")}</span>
                </span>
                <span className="relative h-1.5 rounded bg-canvas">
                  <span className={`absolute top-0 h-full rounded ${c.contribution > 0 ? "left-1/2 bg-bad/70" : "right-1/2 bg-ok/70"}`}
                    style={{ width: `${(Math.abs(c.contribution) / max) * 50}%` }} />
                </span>
                <span className={`text-right tabular ${c.contribution > 0 ? "text-bad" : "text-ok"}`}>{c.contribution > 0 ? "+" : ""}{(c.contribution * 100).toFixed(1)} pp</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs leading-relaxed text-ink-3">{p.explanation}</p>
      <p className="text-[11px] text-ink-4">Generated {dateTime(p.prediction_date)} · model {p.model_version}</p>
    </div>
  );
}
