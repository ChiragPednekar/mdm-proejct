import { AlertTriangle, BrainCircuit, CircleSlash } from "lucide-react";
import type { ModelStatus } from "../lib/useModelStatus";

export function ModelBanner({ status }: { status: ModelStatus | undefined }) {
  if (!status) return null;
  if (status.state === "unavailable") {
    return (
      <div role="status" className="mb-4 flex items-start gap-2 rounded-md border border-line-strong bg-surface px-3 py-2.5 text-xs text-ink-2">
        <CircleSlash className="mt-px size-4 shrink-0 text-ink-3" />
        <div><p className="font-medium text-ink">Prediction model unavailable</p><p>{status.reason} The rest of the application keeps working; no probabilities are shown until a model is trained.</p></div>
      </div>
    );
  }
  if (status.state === "demonstration") {
    return (
      <div role="status" className="mb-4 flex items-start gap-2 rounded-md border border-warn/30 bg-warn-soft px-3 py-2.5 text-xs text-warn">
        <AlertTriangle className="mt-px size-4 shrink-0" />
        <div><p className="font-medium">Demonstration model · {status.active_run?.model_version}</p><p>{status.description}</p></div>
      </div>
    );
  }
  return (
    <div role="status" className="mb-4 flex items-start gap-2 rounded-md border border-ok/30 bg-ok-soft px-3 py-2.5 text-xs text-ok">
      <BrainCircuit className="mt-px size-4 shrink-0" />
      <div><p className="font-medium">Validated model · {status.active_run?.model_version}</p><p>{status.description}</p></div>
    </div>
  );
}
