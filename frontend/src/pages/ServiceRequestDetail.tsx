import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, ShieldCheck, ShieldX, Wrench } from "lucide-react";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { date, dateTime, money } from "../lib/format";
import type { ServiceRequestDetail as Detail, Technician } from "../lib/types";
import { Async, Badge, Button, Card, KeyValue, PageHeader, StatusBadge, cx, EmptyState } from "../components/ui/primitives";
import { Select } from "../components/ui/Form";
import { ConfirmDialog } from "../components/ui/Modal";
import { useToast } from "../components/ui/Toast";
import { RepairForm } from "../components/RepairForm";

const FLOW = ["Open", "Assigned", "In Progress", "Resolved", "Closed"];
const ACTION_LABEL: Record<string, string> = { Open: "Unassign", Assigned: "Mark assigned", "In Progress": "Start work", Closed: "Close request", Cancelled: "Cancel request" };

function Stepper({ status }: { status: string }) {
  const idx = FLOW.indexOf(status);
  if (status === "Cancelled") return <Badge tone="neutral">Cancelled</Badge>;
  return (
    <ol className="flex items-center gap-1" aria-label="Request progress">
      {FLOW.map((s, i) => (
        <li key={s} className="flex items-center gap-1">
          <span className={cx("flex h-6 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium",
            i < idx ? "bg-accent-soft text-accent" : i === idx ? "bg-accent text-white" : "bg-canvas text-ink-4 ring-1 ring-line")}>
            {i < idx && <Check className="size-3" />}{s}
          </span>
          {i < FLOW.length - 1 && <span className={cx("h-px w-4", i < idx ? "bg-accent" : "bg-line-strong")} />}
        </li>
      ))}
    </ol>
  );
}

export default function ServiceRequestDetail() {
  const { id } = useParams();
  const toast = useToast();
  const state = useApi<Detail>(`/service-requests/${id}`);
  const techs = useApi<Technician[]>("/technicians?active_only=true");
  const [tech, setTech] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [form, setForm] = useState<"repair" | "complete" | null>(null);

  const patch = async (json: Record<string, unknown>, label: string) => {
    setBusy(label);
    try { await api(`/service-requests/${id}`, { method: "PATCH", json }); toast.success(`${label}: done`); state.reload(); }
    catch (e) { toast.error(e); } finally { setBusy(null); setConfirm(null); }
  };

  return (
    <Async state={state}>
      {(sr) => (
        <>
          <Link to="/service-requests" className="mb-2 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink"><ArrowLeft className="size-3" /> Service requests</Link>
          <PageHeader title={`Service request #${sr.service_request_id}`}
            description={<span>{sr.fault_category.name} · reported {dateTime(sr.reported_at)}</span>}
            actions={<Stepper status={sr.request_status} />} />
          <div className="grid grid-cols-3 gap-4 max-lg:grid-cols-1">
            <div className="col-span-2 space-y-4 max-lg:col-span-1">
              <Card title="Complaint">
                <p className="mb-3 text-ink">{sr.complaint_description}</p>
                <KeyValue cols={3} items={[
                  ["Priority", <StatusBadge value={sr.priority} />], ["Severity", <StatusBadge value={sr.failure_severity} />],
                  ["Status", <StatusBadge value={sr.request_status} />],
                  ["Product", <Link className="text-accent hover:underline" to={`/products/${sr.product.product_id}`}>{sr.product.serial_number}</Link>],
                  ["Model", `${sr.product.manufacturer} ${sr.product.model_name}`], ["Customer", `${sr.product.customer_name}`],
                  ["Technician", sr.technician?.full_name ?? "Unassigned"], ["Resolved", dateTime(sr.resolution_date)],
                  ["Fault flags", [sr.fault_category.is_customer_induced && "customer-induced", sr.fault_category.is_wear_and_tear && "wear & tear", !sr.fault_category.counts_as_failure && "non-failure visit"].filter(Boolean).join(", ") || "—"],
                ]} />
                {sr.resolution_summary && <p className="mt-3 rounded-md bg-ok-soft px-3 py-2 text-xs text-ok">Resolution: {sr.resolution_summary}</p>}
              </Card>
              <Card title="Repair attempts" subtitle="Each attempt is kept separately from the original complaint." bodyClass="p-0"
                actions={sr.can_record_repair && <Button size="sm" icon={<Wrench className="size-3.5" />} onClick={() => setForm("repair")}>Record repair</Button>}>
                {sr.repairs.length === 0 ? <EmptyState title="No repairs recorded" hint="Assign a technician, then record the diagnosis, actions and parts used." /> : (
                  <ol className="divide-y divide-line">
                    {sr.repairs.map((r) => (
                      <li key={r.repair_id} className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">Attempt {r.attempt_number}</span><StatusBadge value={r.outcome} />
                          {r.repeat_failure && <Badge tone="warn" title="Product had a repair within the repeat window before this complaint">Repeat failure</Badge>}
                          <span className="text-xs text-ink-3">{r.technician_name} · {dateTime(r.repair_date)}</span>
                          <span className="ml-auto tabular font-medium">{money(r.total_cost)}</span>
                        </div>
                        <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                          <div><dt className="inline text-ink-3">Diagnosis: </dt><dd className="inline">{r.diagnosis}</dd></div>
                          <div><dt className="inline text-ink-3">Component: </dt><dd className="inline">{r.component_name ?? "—"}</dd></div>
                          <div><dt className="inline text-ink-3">Root cause: </dt><dd className="inline">{r.root_cause ?? "—"}</dd></div>
                          <div><dt className="inline text-ink-3">Action: </dt><dd className="inline">{r.repair_action}</dd></div>
                        </dl>
                        {r.parts.length > 0 && (
                          <table className="mt-2 w-full text-xs">
                            <thead><tr className="text-left text-ink-4"><th className="font-medium">Part</th><th className="text-right font-medium">Qty</th><th className="text-right font-medium">Unit cost at repair</th><th className="text-right font-medium">Line</th></tr></thead>
                            <tbody>{r.parts.map((p) => (
                              <tr key={p.part_id}><td><span className="font-mono">{p.part_number}</span> {p.part_name}</td>
                                <td className="text-right tabular">{p.quantity_used}</td><td className="text-right tabular">{money(p.unit_cost_at_repair)}</td>
                                <td className="text-right tabular">{money(p.line_total)}</td></tr>))}</tbody>
                          </table>
                        )}
                        <p className="mt-1 text-right text-[11px] text-ink-3">Labor {money(r.labor_cost)} · Parts {money(r.parts_cost)}</p>
                      </li>
                    ))}
                  </ol>
                )}
              </Card>
            </div>
            <div className="space-y-4">
              <Card title="Workflow">
                <div className="space-y-3">
                  {(sr.request_status === "Open" || sr.request_status === "Assigned") && (
                    <div>
                      <label className="mb-1 block text-xs font-medium text-ink-2" htmlFor="assign">{sr.technician ? "Reassign technician" : "Assign technician"}</label>
                      <div className="flex gap-2">
                        <Select id="assign" value={tech} onChange={(e) => setTech(e.target.value)}>
                          <option value="">Select…</option>
                          {techs.data?.map((t) => <option key={t.technician_id} value={t.technician_id}>{t.full_name} — {t.specialization}</option>)}
                        </Select>
                        <Button disabled={!tech} loading={busy === "Assign"} onClick={() => patch({ assigned_technician_id: Number(tech) }, "Assign")}>Assign</Button>
                      </div>
                    </div>
                  )}
                  {sr.can_complete && <Button variant="primary" className="w-full" onClick={() => setForm("complete")}>Complete &amp; resolve…</Button>}
                  <div className="flex flex-wrap gap-2">
                    {sr.allowed_transitions.filter((t) => t !== "Assigned").map((t) => (
                      <Button key={t} size="sm" variant={t === "Cancelled" ? "danger" : "secondary"} loading={busy === t}
                        onClick={() => (t === "Cancelled" || t === "Closed" ? setConfirm(t) : patch({ request_status: t }, ACTION_LABEL[t] ?? t))}>
                        {sr.request_status === "Resolved" && t === "In Progress" ? "Reopen" : ACTION_LABEL[t] ?? t}
                      </Button>
                    ))}
                  </div>
                  {sr.allowed_transitions.length === 0 && !sr.can_complete && <p className="text-xs text-ink-3">This request is {sr.request_status.toLowerCase()}; no further actions.</p>}
                </div>
              </Card>
              <Card title="Warranty decision">
                <div className={cx("mb-3 flex items-start gap-2 rounded-md px-3 py-2 text-xs", sr.warranty_covered ? "bg-ok-soft text-ok" : "bg-canvas text-ink-2")}>
                  {sr.warranty_covered ? <ShieldCheck className="size-4 shrink-0" /> : <ShieldX className="size-4 shrink-0 text-ink-3" />}
                  <div><p className="font-medium">{sr.warranty_covered ? "Covered" : "Not covered"}</p><p>{sr.coverage_notes}</p></div>
                </div>
                {sr.warranty ? <KeyValue items={[
                  ["Warranty", `#${sr.warranty.warranty_id} ${sr.warranty.warranty_type}`], ["Now", <StatusBadge value={sr.warranty.effective_status} />],
                  ["Period", `${date(sr.warranty.start_date)} – ${date(sr.warranty.end_date)}`],
                  ["Terms", [sr.warranty.covers_parts && "parts", sr.warranty.covers_labor && "labor"].filter(Boolean).join(" + ")],
                ]} /> : <p className="text-xs text-ink-3">No warranty was in force when the complaint was reported.</p>}
                <p className="mt-2 text-[11px] text-ink-4">Decision recorded at intake from warranty dates, terms and fault-category exclusions.</p>
              </Card>
              <Card title="Costs">
                <KeyValue items={[["Labor", money(sr.costs.labor)], ["Parts", money(sr.costs.parts)], ["Total", <b>{money(sr.costs.total)}</b>],
                  ["Warranty-borne", money(sr.costs.warranty)], ["Customer pays", <b>{money(sr.costs.customer)}</b>]]} />
              </Card>
            </div>
          </div>
          {form && (
            <RepairForm key={form} requestId={sr.service_request_id} mode={form} open onClose={() => setForm(null)} hasRepairs={sr.repairs.length > 0}
              defaultTechnicianId={sr.technician?.technician_id} onDone={() => { setForm(null); state.reload(); }} />
          )}
          <ConfirmDialog open={!!confirm} danger={confirm === "Cancelled"} title={confirm === "Cancelled" ? "Cancel service request" : "Close service request"}
            confirmLabel={confirm === "Cancelled" ? "Cancel request" : "Close request"} loading={busy === confirm}
            message={confirm === "Cancelled" ? "Cancelling is final. Requests with recorded repairs cannot be cancelled." : "Closing is final; the request can no longer be reopened or edited."}
            onCancel={() => setConfirm(null)} onConfirm={() => patch({ request_status: confirm }, ACTION_LABEL[confirm!] ?? confirm!)} />
        </>
      )}
    </Async>
  );
}
