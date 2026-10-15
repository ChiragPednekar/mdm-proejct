import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Play } from "lucide-react";
import { api } from "../lib/api";
import { useList } from "../lib/useList";
import { useAuth } from "../lib/auth";
import { useModelStatus } from "../lib/useModelStatus";
import { dateTime, prob } from "../lib/format";
import type { Prediction } from "../lib/types";
import { Badge, Button, Card, PageHeader, StatusBadge } from "../components/ui/primitives";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { Checkbox, FilterBar, FilterSelect, SearchInput } from "../components/ui/Form";
import { Modal } from "../components/ui/Modal";
import { useToast } from "../components/ui/Toast";
import { ModelBanner } from "../components/ModelBanner";
import { PredictionPanel } from "../components/PredictionCard";

export default function Predictions() {
  const nav = useNavigate();
  const toast = useToast();
  const { hasRole } = useAuth();
  const status = useModelStatus();
  const list = useList<Prediction>("/predictions", { current_only: true, sort: "-probability" });
  const [selected, setSelected] = useState<Prediction | null>(null);
  const [busy, setBusy] = useState(false);
  const f = list.filters;
  const s = status.data;

  const scoreAll = async () => {
    setBusy(true);
    try {
      const r = await api<{ generated: number; by_risk_level: Record<string, number> }>("/predictions/generate-batch", { method: "POST" });
      toast.success(`Scored ${r.generated} products: ${Object.entries(r.by_risk_level).map(([k, v]) => `${v} ${k}`).join(", ")}`);
      list.reload();
    } catch (e) { toast.error(e); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Failure predictions" description="Probability that a unit has another qualifying failure within the horizon, with the factors behind each estimate."
        actions={hasRole("admin", "service_manager") && <Button variant="primary" icon={<Play className="size-3.5" />} loading={busy} disabled={!s?.available} onClick={scoreAll}>Score all active products</Button>} />
      <ModelBanner status={s} />
      {s && (
        <div className="mb-4 grid grid-cols-2 gap-3 text-xs max-md:grid-cols-1">
          <div className="rounded-lg border border-line bg-surface px-4 py-3">
            <p className="font-medium text-ink-2">Risk bands (configurable in Settings)</p>
            <p className="mt-1 text-ink-3"><StatusBadge value="Low" /> &lt; {prob(s.risk_bands.medium_min)} ≤ <StatusBadge value="Medium" /> &lt; {prob(s.risk_bands.high_min)} ≤ <StatusBadge value="High" /></p>
          </div>
          <div className="rounded-lg border border-line bg-surface px-4 py-3">
            <p className="font-medium text-ink-2">Model decision threshold (chosen on validation data)</p>
            <p className="mt-1 text-ink-3">{s.decision_threshold === null ? "—" : <>Flag for inspection at ≥ <b className="text-ink">{prob(s.decision_threshold)}</b> — maximises validation F1. Bands are for communication; the threshold is the evaluated operating point.</>}</p>
          </div>
        </div>
      )}
      <Card bodyClass="p-0">
        <FilterBar>
          <SearchInput className="w-64" placeholder="Serial or model" value={String(f.q ?? "")} onChange={(v) => list.set("q", v)} />
          <FilterSelect label="Risk" value={String(f.risk_level ?? "")} onChange={(v) => list.set("risk_level", v)} options={["High", "Medium", "Low"]} />
          <FilterSelect label="Category" value={String(f.category ?? "")} onChange={(v) => list.set("category", v)} options={["Laptop", "Refrigerator", "Washing Machine", "Air Conditioner", "Television"]} />
          <FilterSelect label="Sort" allLabel="Highest probability" value={f.sort === "-probability" ? "" : String(f.sort)} onChange={(v) => list.set("sort", v || "-probability")}
            options={[{ value: "-date", label: "Most recent" }, { value: "probability", label: "Lowest probability" }]} />
          <Checkbox label="Current only (uncheck for full history)" checked={f.current_only === true} onChange={(e) => list.set("current_only", e.target.checked)} />
        </FilterBar>
        <DataTable rows={list.data?.items} loading={list.loading} error={list.error} onRetry={list.reload} rowKey={(p) => p.prediction_id}
          onRowClick={setSelected} emptyTitle="No predictions yet"
          emptyHint={s?.available ? "Use “Score all active products”, or generate one from a product profile." : "Train a model on the Model Performance page first."}
          columns={[
            { key: "s", header: "Serial", render: (p) => <span className="font-mono text-xs">{p.serial_number}</span> },
            { key: "m", header: "Model", render: (p) => p.model_name },
            { key: "c", header: "Category", render: (p) => p.product_category },
            { key: "p", header: "Probability", align: "right", render: (p) => <span className="font-medium">{prob(p.failure_probability)}</span> },
            { key: "r", header: "Risk band", render: (p) => <StatusBadge value={p.risk_level} /> },
            { key: "t", header: "Above threshold", render: (p) => p.above_decision_threshold ? <Badge tone="warn">Inspect</Badge> : <span className="text-xs text-ink-4">No</span> },
            { key: "h", header: "Horizon", render: (p) => `${p.prediction_horizon_days} d` },
            { key: "d", header: "Predicted", render: (p) => <span className="text-xs">{dateTime(p.prediction_date)}</span> },
            { key: "k", header: "Model", render: (p) => <Badge tone={p.model_classification === "demonstration" ? "warn" : "ok"}>{p.model_classification}</Badge> },
            { key: "st", header: "", render: (p) => <span className="text-[11px] text-ink-4">{p.prediction_status}</span> },
          ]} />
        {list.data && <Pagination page={list.page} pageSize={list.pageSize} total={list.data.total} onPage={list.setPage} />}
      </Card>
      <Modal open={!!selected} onClose={() => setSelected(null)} title={`Prediction · ${selected?.serial_number ?? ""}`}
        footer={<Button variant="primary" onClick={() => nav(`/products/${selected!.product_id}`)}>Open product profile</Button>}>
        {selected && <PredictionPanel p={selected} />}
      </Modal>
    </>
  );
}
