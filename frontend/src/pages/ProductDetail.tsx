import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Line, LineChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ArrowLeft, ClipboardPlus, ShieldPlus } from "lucide-react";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useAuth } from "../lib/auth";
import { date, dateTime, money, prob } from "../lib/format";
import type { Prediction, Repair, Warranty } from "../lib/types";
import { Async, Badge, Button, Card, EmptyState, KeyValue, PageHeader, StatTile, StatusBadge } from "../components/ui/primitives";
import { DataTable } from "../components/ui/DataTable";
import { CHART, ChartCard } from "../components/ui/Chart";
import { useToast } from "../components/ui/Toast";
import { PredictionPanel } from "../components/PredictionCard";
import { ServiceRequestForm } from "../components/ServiceRequestForm";
import { ExtendWarrantyModal } from "../components/ExtendWarrantyModal";

interface Profile {
  product: { product_id: number; serial_number: string; purchase_date: string; purchase_price: string; installation_date: string | null; product_status: string };
  model: { manufacturer: string; model_name: string; product_category: string; standard_warranty_months: number; release_year: number };
  customer: { customer_id: number; full_name: string; email: string | null; phone: string | null; address: string | null; city: string | null };
  warranties: Warranty[];
  coverage: { covered_today: boolean; covered_until: string | null };
  stats: { service_requests: number; open_requests: number; repairs: number; total_repair_cost: number; warranty_cost: number; customer_cost: number; repeat_repairs: number };
  latest_prediction: Prediction | null;
}
interface History {
  timeline: {
    service_request_id: number; reported_at: string; fault_category: string; complaint_description: string; priority: string;
    failure_severity: string; request_status: string; technician_name: string | null; warranty_covered: boolean | null;
    coverage_notes: string | null; resolution_date: string | null; resolution_summary: string | null; repairs: Repair[];
  }[];
  components_replaced: { component_name: string; part_number: string; part_name: string; quantity: number; cost: number; last_replaced: string }[];
  predictions: Prediction[];
}

export default function ProductDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { hasRole } = useAuth();
  const profile = useApi<Profile>(`/products/${id}`);
  const history = useApi<History>(`/products/${id}/history`);
  const [srOpen, setSrOpen] = useState(false);
  const [extendId, setExtendId] = useState<number | null>(null);
  const [predicting, setPredicting] = useState(false);

  const generate = async () => {
    setPredicting(true);
    try {
      const p = await api<Prediction>(`/predictions/${id}/generate`, { method: "POST" });
      toast.success(`Risk estimate: ${prob(p.failure_probability)} (${p.risk_level})`);
      profile.reload(); history.reload();
    } catch (e) { toast.error(e); } finally { setPredicting(false); }
  };

  return (
    <Async state={profile}>
      {(p) => {
        const canPredict = !["Replaced", "Retired"].includes(p.product.product_status);
        const extendable = p.warranties.filter((w) => w.warranty_status === "Valid" && (w.effective_status === "Active" || w.effective_status === "Pending"));
        return (
          <>
            <Link to="/products" className="mb-2 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink"><ArrowLeft className="size-3" /> Products</Link>
            <PageHeader
              title={p.product.serial_number}
              description={<span>{p.model.manufacturer} {p.model.model_name} · {p.model.product_category} · <StatusBadge value={p.product.product_status} /></span>}
              actions={<>
                {hasRole("admin", "service_manager") && extendable.length > 0 && (
                  <Button icon={<ShieldPlus className="size-3.5" />} onClick={() => setExtendId(extendable[extendable.length - 1].warranty_id)}>Extend warranty</Button>
                )}
                <Button icon={<Activity className="size-3.5" />} loading={predicting} disabled={!canPredict} onClick={generate}>Generate risk prediction</Button>
                <Button variant="primary" icon={<ClipboardPlus className="size-3.5" />} disabled={!canPredict} onClick={() => setSrOpen(true)}>New service request</Button>
              </>} />

            <div className="mb-4 grid grid-cols-5 gap-3 max-lg:grid-cols-3">
              <StatTile label="Service requests" value={p.stats.service_requests} sub={`${p.stats.open_requests} open`} />
              <StatTile label="Repairs" value={p.stats.repairs} sub={`${p.stats.repeat_repairs} flagged as repeat`} />
              <StatTile label="Total repair cost" value={money(p.stats.total_repair_cost)} />
              <StatTile label="Warranty-borne" value={money(p.stats.warranty_cost)} />
              <StatTile label="Customer-paid" value={money(p.stats.customer_cost)} />
            </div>

            <div className="mb-4 grid grid-cols-3 gap-4 max-lg:grid-cols-1">
              <Card title="Unit & owner">
                <KeyValue items={[
                  ["Customer", <Link className="text-accent hover:underline" to={`/customers?q=${encodeURIComponent(p.customer.full_name)}`}>{p.customer.full_name}</Link>],
                  ["Phone", p.customer.phone], ["Email", p.customer.email], ["City", p.customer.city],
                  ["Purchased", date(p.product.purchase_date)], ["Price", money(p.product.purchase_price)],
                  ["Installed", date(p.product.installation_date)], ["Model released", p.model.release_year],
                ]} />
              </Card>
              <Card title="Warranty coverage" subtitle={p.coverage.covered_today ? `Covered until ${date(p.coverage.covered_until)}` : "No coverage in force today"} bodyClass="p-0">
                <DataTable dense rows={p.warranties} rowKey={(w) => w.warranty_id} emptyTitle="No warranties registered" columns={[
                  { key: "t", header: "Type", render: (w) => <span title={w.coverage_details ?? ""}>#{w.warranty_id} {w.warranty_type}</span> },
                  { key: "d", header: "Period", render: (w) => <span className="text-xs">{date(w.start_date)} – {date(w.end_date)}</span> },
                  { key: "s", header: "Status", render: (w) => <StatusBadge value={w.effective_status} /> },
                  { key: "c", header: "Covers", render: (w) => <span className="text-[11px] text-ink-3">{[w.covers_parts && "parts", w.covers_labor && "labor", w.covers_wear_and_tear && "wear", w.covers_accidental_damage && "accidents"].filter(Boolean).join(", ")}</span> },
                ]} />
              </Card>
              <Card title="Latest failure-risk prediction">
                {p.latest_prediction ? <PredictionPanel p={p.latest_prediction} /> : (
                  <EmptyState title="Not scored yet" hint={canPredict ? "Generate a prediction to estimate the probability of another failure." : "Replaced or retired units are not scored."}
                    action={canPredict && <Button size="sm" loading={predicting} onClick={generate}>Generate now</Button>} />
                )}
              </Card>
            </div>

            <Async state={history}>
              {(h) => (
                <div className="grid grid-cols-3 gap-4 max-lg:grid-cols-1">
                  <Card title="Service & repair timeline" className="col-span-2 max-lg:col-span-1" bodyClass="p-0">
                    {h.timeline.length === 0 ? <EmptyState title="No service history" /> : (
                      <ol className="divide-y divide-line">
                        {h.timeline.map((sr) => (
                          <li key={sr.service_request_id} className="px-4 py-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <button onClick={() => nav(`/service-requests/${sr.service_request_id}`)} className="font-medium text-accent hover:underline">SR #{sr.service_request_id}</button>
                              <span className="font-medium">{sr.fault_category}</span>
                              <StatusBadge value={sr.request_status} />
                              <StatusBadge value={sr.failure_severity} />
                              {sr.warranty_covered ? <Badge tone="ok">Warranty</Badge> : <Badge>Chargeable</Badge>}
                              <span className="ml-auto text-xs text-ink-3">{dateTime(sr.reported_at)}</span>
                            </div>
                            <p className="mt-1 text-ink-2">{sr.complaint_description}</p>
                            {sr.repairs.map((r) => (
                              <div key={r.repair_id} className="mt-2 rounded-md border border-line bg-canvas/50 px-3 py-2 text-xs">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="font-medium">Attempt {r.attempt_number}</span><StatusBadge value={r.outcome} />
                                  {r.repeat_failure && <Badge tone="warn">Repeat failure</Badge>}
                                  <span className="text-ink-3">{r.technician_name} · {date(r.repair_date)}</span>
                                  <span className="ml-auto tabular">{money(r.total_cost)}</span>
                                </div>
                                <p className="mt-1 text-ink-2">{r.diagnosis}{r.component_name ? ` — ${r.component_name}` : ""}. {r.repair_action}.</p>
                                {r.parts.length > 0 && <p className="mt-0.5 text-ink-3">Parts: {r.parts.map((x) => `${x.part_name} ×${x.quantity_used}`).join(", ")}</p>}
                              </div>
                            ))}
                          </li>
                        ))}
                      </ol>
                    )}
                  </Card>
                  <div className="space-y-4">
                    <Card title="Components replaced" bodyClass="p-0">
                      <DataTable dense rows={h.components_replaced} rowKey={(c) => c.part_number} emptyTitle="No parts replaced" columns={[
                        { key: "c", header: "Part", render: (c) => <span title={c.part_number}>{c.part_name}</span> },
                        { key: "q", header: "Qty", align: "right", render: (c) => c.quantity },
                        { key: "$", header: "Cost", align: "right", render: (c) => money(c.cost) },
                      ]} />
                    </Card>
                    <ChartCard title="Risk history" subtitle={`${h.predictions.length} stored predictions`} height={160} empty={h.predictions.length < 2}>
                      <LineChart data={[...h.predictions].reverse().map((x) => ({ d: date(x.prediction_date), p: x.failure_probability }))} margin={{ left: -16, right: 8 }}>
                        <CartesianGrid stroke={CHART.grid} vertical={false} />
                        <XAxis dataKey="d" tick={CHART.axis} tickLine={false} axisLine={false} />
                        <YAxis tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={CHART.axis} tickLine={false} axisLine={false} />
                        <Tooltip formatter={(v) => prob(Number(v))} />
                        <Line isAnimationActive={false} dataKey="p" stroke={CHART.accent} strokeWidth={2} dot={{ r: 2 }} name="Probability" />
                      </LineChart>
                    </ChartCard>
                    <Card title="Prediction history" bodyClass="p-0">
                      <DataTable dense rows={h.predictions} rowKey={(x) => x.prediction_id} emptyTitle="No predictions yet" columns={[
                        { key: "d", header: "Date", render: (x) => <span className="text-xs">{dateTime(x.prediction_date)}</span> },
                        { key: "p", header: "Prob.", align: "right", render: (x) => prob(x.failure_probability) },
                        { key: "r", header: "Risk", render: (x) => <StatusBadge value={x.risk_level} /> },
                        { key: "s", header: "", render: (x) => <span className="text-[11px] text-ink-4">{x.prediction_status}</span> },
                      ]} />
                    </Card>
                  </div>
                </div>
              )}
            </Async>
            <ServiceRequestForm open={srOpen} productId={p.product.product_id} onClose={() => setSrOpen(false)}
              onCreated={(sid) => { setSrOpen(false); nav(`/service-requests/${sid}`); }} />
            <ExtendWarrantyModal warrantyId={extendId} onClose={() => setExtendId(null)} onDone={() => { setExtendId(null); profile.reload(); }} />
          </>
        );
      }}
    </Async>
  );
}
