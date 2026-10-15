import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { money } from "../lib/format";
import type { Component, Page, Part, Technician } from "../lib/types";
import { Modal } from "./ui/Modal";
import { Button } from "./ui/primitives";
import { Checkbox, Field, Input, Select, Textarea } from "./ui/Form";
import { useToast } from "./ui/Toast";

const OUTCOMES = ["Fixed", "Partially Fixed", "Not Fixed", "Unit Replaced", "Referred"];
type Line = { part_id: string; quantity: number };

function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID().replace(/-/g, "") : `${Date.now()}${Math.random()}`.replace(".", "");
}

/** Record a repair attempt, or complete the request (optionally with a final attempt) in one transaction. */
export function RepairForm({ requestId, mode, open, onClose, onDone, defaultTechnicianId, hasRepairs }: {
  requestId: number; mode: "repair" | "complete"; open: boolean; onClose: () => void; onDone: () => void;
  defaultTechnicianId?: number | null; hasRepairs: boolean;
}) {
  const toast = useToast();
  const techs = useApi<Technician[]>(open ? "/technicians?active_only=true" : null);
  const comps = useApi<Component[]>(open ? "/catalog/components" : null);
  const parts = useApi<Page<Part>>(open ? "/inventory/parts?page_size=100" : null);
  const [includeRepair, setIncludeRepair] = useState(mode === "repair" || !hasRepairs);
  const [v, setV] = useState({ technician_id: String(defaultTechnicianId ?? ""), component_id: "", diagnosis: "", root_cause: "",
    repair_action: "", labor_cost: "0", outcome: mode === "complete" ? "Fixed" : "Fixed", resolution_summary: "" });
  const [lines, setLines] = useState<Line[]>([]);
  const [key] = useState(newKey); // one idempotency key per form instance: retries never double-deduct
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const partMap = useMemo(() => new Map((parts.data?.items ?? []).map((p) => [String(p.part_id), p])), [parts.data]);
  const partOptions = (parts.data?.items ?? []).filter((p) => !v.component_id || String(p.component_id) === v.component_id);
  const partsCost = lines.reduce((s, l) => s + (Number(partMap.get(l.part_id)?.unit_cost ?? 0) * l.quantity), 0);
  const labor = Number(v.labor_cost) || 0;
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });

  const validate = () => {
    const e: Record<string, string> = {};
    if (includeRepair) {
      if (!v.technician_id) e.technician_id = "Select the technician who performed the work";
      if (v.diagnosis.trim().length < 3) e.diagnosis = "Diagnosis is required";
      if (v.repair_action.trim().length < 3) e.repair_action = "Describe the action taken";
      if (!(labor >= 0) || v.labor_cost === "") e.labor_cost = "Enter a labor cost ≥ 0";
      const ids = lines.map((l) => l.part_id);
      lines.forEach((l, i) => {
        const p = partMap.get(l.part_id);
        if (!l.part_id) e[`line${i}`] = "Choose a part";
        else if (ids.indexOf(l.part_id) !== i) e[`line${i}`] = "Part already listed";
        else if (!(l.quantity >= 1)) e[`line${i}`] = "Quantity must be ≥ 1";
        else if (p && l.quantity > p.stock_quantity) e[`line${i}`] = `Only ${p.stock_quantity} in stock`;
      });
    }
    if (mode === "complete" && v.resolution_summary.trim().length < 3) e.resolution_summary = "Summarise the resolution";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = async () => {
    if (!validate()) return;
    setBusy(true); setServerError(null);
    const repair = {
      technician_id: Number(v.technician_id), component_id: v.component_id ? Number(v.component_id) : null,
      diagnosis: v.diagnosis, root_cause: v.root_cause || null, repair_action: v.repair_action,
      labor_cost: labor.toFixed(2), outcome: v.outcome, idempotency_key: key,
      parts: lines.map((l) => ({ part_id: Number(l.part_id), quantity: l.quantity })),
    };
    try {
      if (mode === "repair") await api(`/service-requests/${requestId}/repairs`, { method: "POST", json: repair });
      else await api(`/service-requests/${requestId}/complete`, { method: "POST",
        json: { resolution_summary: v.resolution_summary, final_repair: includeRepair ? repair : null } });
      toast.success(mode === "repair" ? "Repair attempt recorded; inventory updated" : "Service request resolved");
      onDone();
    } catch (e) { setServerError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} width="lg" title={mode === "repair" ? "Record repair attempt" : "Complete service request"}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>{mode === "repair" ? "Save repair" : "Resolve request"}</Button></>}>
      <div className="space-y-3">
        {mode === "complete" && (
          <>
            <Field label="Resolution summary" required error={errors.resolution_summary}>
              <Textarea aria-label="Resolution summary" rows={2} value={v.resolution_summary} onChange={set("resolution_summary")} />
            </Field>
            <Checkbox label="Record a final repair attempt as part of completion" checked={includeRepair} onChange={(e) => setIncludeRepair(e.target.checked)} />
          </>
        )}
        {includeRepair && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Technician" required error={errors.technician_id}>
              <Select aria-label="Technician" value={v.technician_id} onChange={set("technician_id")}>
                <option value="">Select…</option>
                {techs.data?.map((t) => <option key={t.technician_id} value={t.technician_id}>{t.full_name}</option>)}
              </Select>
            </Field>
            <Field label="Component">
              <Select aria-label="Component" value={v.component_id} onChange={set("component_id")}>
                <option value="">None / not component-specific</option>
                {comps.data?.map((c) => <option key={c.component_id} value={c.component_id}>{c.component_name}</option>)}
              </Select>
            </Field>
            <Field label="Diagnosis" required error={errors.diagnosis}><Input aria-label="Diagnosis" value={v.diagnosis} onChange={set("diagnosis")} /></Field>
            <Field label="Root cause"><Input aria-label="Root cause" value={v.root_cause} onChange={set("root_cause")} /></Field>
            <div className="col-span-2"><Field label="Repair action" required error={errors.repair_action}><Textarea aria-label="Repair action" rows={2} value={v.repair_action} onChange={set("repair_action")} /></Field></div>
            <Field label="Labor cost (₹)" required error={errors.labor_cost}><Input aria-label="Labor cost" type="number" min={0} step="0.01" value={v.labor_cost} onChange={set("labor_cost")} /></Field>
            <Field label="Outcome"><Select aria-label="Outcome" value={v.outcome} onChange={set("outcome")}>{OUTCOMES.map((o) => <option key={o}>{o}</option>)}</Select></Field>
            <div className="col-span-2">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-medium text-ink-2">Parts used</span>
                <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => setLines([...lines, { part_id: "", quantity: 1 }])}>Add part</Button>
              </div>
              {lines.length === 0 && <p className="text-xs text-ink-3">No parts. Stock is deducted only when the repair is saved.</p>}
              {lines.map((l, i) => {
                const p = partMap.get(l.part_id);
                return (
                  <div key={i} className="mb-1.5 grid grid-cols-[1fr_80px_100px_28px] items-start gap-2">
                    <div>
                      <Select aria-label={`Part ${i + 1}`} value={l.part_id} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, part_id: e.target.value } : x))}>
                        <option value="">Select part…</option>
                        {partOptions.map((pp) => <option key={pp.part_id} value={pp.part_id} disabled={pp.stock_quantity === 0}>
                          {pp.part_number} — {pp.part_name} ({pp.stock_quantity} in stock)</option>)}
                      </Select>
                      {errors[`line${i}`] && <p className="mt-0.5 text-[11px] text-bad">{errors[`line${i}`]}</p>}
                    </div>
                    <Input aria-label={`Quantity ${i + 1}`} type="number" min={1} value={l.quantity} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, quantity: Number(e.target.value) } : x))} />
                    <span className="pt-1.5 text-right text-xs tabular text-ink-2">{p ? money(Number(p.unit_cost) * l.quantity) : "—"}</span>
                    <Button size="sm" variant="ghost" aria-label="Remove part" icon={<Trash2 className="size-3.5" />} onClick={() => setLines(lines.filter((_, j) => j !== i))} />
                  </div>
                );
              })}
            </div>
            <div className="col-span-2 flex justify-end gap-6 border-t border-line pt-2 text-xs">
              <span className="text-ink-3">Labor <b className="tabular text-ink">{money(labor)}</b></span>
              <span className="text-ink-3">Parts <b className="tabular text-ink">{money(partsCost)}</b></span>
              <span className="text-ink-3">Total <b className="tabular text-ink">{money(labor + partsCost)}</b></span>
            </div>
          </div>
        )}
        {serverError && <p role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{serverError}</p>}
      </div>
    </Modal>
  );
}
