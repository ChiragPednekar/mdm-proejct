import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import { PackagePlus, Pencil, Plus, SlidersHorizontal } from "lucide-react";
import { api, ApiError, qs } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useList } from "../lib/useList";
import { useAuth } from "../lib/auth";
import { dateTime, money, number } from "../lib/format";
import type { Component, Page, Part } from "../lib/types";
import { Async, Badge, Button, Card, KeyValue, PageHeader, StatTile, Tabs } from "../components/ui/primitives";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { Checkbox, Field, FilterBar, FilterSelect, Input, SearchInput, Select } from "../components/ui/Form";
import { Modal } from "../components/ui/Modal";
import { CHART, ChartCard } from "../components/ui/Chart";
import { useToast } from "../components/ui/Toast";

const partSchema = z.object({
  part_number: z.string().trim().regex(/^[A-Za-z0-9-]{3,40}$/, "3–40 letters, digits or dashes"),
  part_name: z.string().trim().min(2, "Name is required").max(120),
  component_id: z.string().optional(),
  unit_cost: z.coerce.number({ invalid_type_error: "Enter a cost" }).min(0, "Must be ≥ 0"),
  selling_price: z.union([z.literal(""), z.coerce.number().min(0, "Must be ≥ 0")]).optional(),
  initial_stock: z.coerce.number().int().min(0, "Must be ≥ 0"),
  reorder_level: z.coerce.number().int().min(0, "Must be ≥ 0"),
  supplier_name: z.string().max(120).optional(),
});
type PartValues = z.infer<typeof partSchema>;

function PartForm({ part, open, onClose, onSaved }: { part: Part | null; open: boolean; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const comps = useApi<Component[]>(open ? "/catalog/components" : null);
  const [err, setErr] = useState<string | null>(null);
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<PartValues>({
    resolver: zodResolver(partSchema),
    values: { part_number: part?.part_number ?? "", part_name: part?.part_name ?? "", component_id: part?.component_id ? String(part.component_id) : "",
      unit_cost: Number(part?.unit_cost ?? 0), selling_price: part?.selling_price ? Number(part.selling_price) : "", initial_stock: 0,
      reorder_level: part?.reorder_level ?? 5, supplier_name: part?.supplier_name ?? "" },
  });
  const onSubmit = async (v: PartValues) => {
    setErr(null);
    const common = { part_name: v.part_name, component_id: v.component_id ? Number(v.component_id) : null, unit_cost: v.unit_cost.toFixed(2),
      selling_price: v.selling_price === "" || v.selling_price === undefined ? null : Number(v.selling_price).toFixed(2),
      reorder_level: v.reorder_level, supplier_name: v.supplier_name || null };
    try {
      if (part) await api(`/inventory/parts/${part.part_id}`, { method: "PATCH", json: common });
      else await api("/inventory/parts", { method: "POST", json: { ...common, part_number: v.part_number, initial_stock: v.initial_stock } });
      toast.success(part ? "Part updated" : "Part registered");
      onSaved();
    } catch (e) {
      if (e instanceof ApiError && e.code === "integrity_error") setError("part_number", { message: e.message });
      else setErr(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <Modal open={open} onClose={onClose} title={part ? `Edit ${part.part_number}` : "Register part"}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={isSubmitting} onClick={handleSubmit(onSubmit)}>Save</Button></>}>
      <form noValidate onSubmit={handleSubmit(onSubmit)} className="grid grid-cols-2 gap-3">
        <Field label="Part number" required error={errors.part_number?.message}><Input aria-label="Part number" disabled={!!part} className="font-mono" {...register("part_number")} /></Field>
        <Field label="Name" required error={errors.part_name?.message}><Input aria-label="Part name" {...register("part_name")} /></Field>
        <Field label="Component"><Select aria-label="Component" {...register("component_id")}><option value="">None</option>
          {comps.data?.map((c) => <option key={c.component_id} value={c.component_id}>{c.component_name}</option>)}</Select></Field>
        <Field label="Supplier"><Input aria-label="Supplier" {...register("supplier_name")} /></Field>
        <Field label="Unit cost (₹)" required error={errors.unit_cost?.message} hint={part ? "Affects future repairs only; past repairs keep their recorded cost." : undefined}>
          <Input aria-label="Unit cost" type="number" step="0.01" {...register("unit_cost")} /></Field>
        <Field label="Selling price (₹)" error={errors.selling_price?.message}><Input aria-label="Selling price" type="number" step="0.01" {...register("selling_price")} /></Field>
        <Field label="Reorder level" required error={errors.reorder_level?.message}><Input aria-label="Reorder level" type="number" {...register("reorder_level")} /></Field>
        {!part && <Field label="Opening stock" error={errors.initial_stock?.message}><Input aria-label="Opening stock" type="number" {...register("initial_stock")} /></Field>}
        {err && <p role="alert" className="col-span-2 rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{err}</p>}
      </form>
    </Modal>
  );
}

function AdjustModal({ part, onClose, onSaved }: { part: Part | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [type, setType] = useState<"Restock" | "Adjustment">("Restock");
  const [qty, setQty] = useState("10");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const n = Number(qty);
  const after = (part?.stock_quantity ?? 0) + (Number.isFinite(n) ? n : 0);
  const invalid = !Number.isInteger(n) || n === 0 || (type === "Restock" && n < 0) || after < 0 || reason.trim().length < 3;
  const submit = async () => {
    if (!part || invalid) return;
    setBusy(true); setErr(null);
    try { await api(`/inventory/parts/${part.part_id}/adjust`, { method: "POST", json: { quantity_change: n, transaction_type: type, reason } });
      toast.success(`Stock for ${part.part_number} is now ${after}`); onSaved(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <Modal open={!!part} onClose={onClose} title={`Adjust stock · ${part?.part_number ?? ""}`} width="sm"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={invalid} onClick={submit}>Record</Button></>}>
      <div className="space-y-3">
        <Field label="Transaction"><Select aria-label="Transaction type" value={type} onChange={(e) => setType(e.target.value as typeof type)}>
          <option value="Restock">Restock (goods received)</option><option value="Adjustment">Adjustment (count correction / write-off)</option></Select></Field>
        <Field label="Quantity change" error={after < 0 ? "Stock cannot become negative" : type === "Restock" && n < 0 ? "A restock must be positive" : undefined}
          hint={`Current ${part?.stock_quantity} → after ${after}`}>
          <Input aria-label="Quantity change" type="number" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Reason" required><Input aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. PO-2291 received" /></Field>
        {err && <p role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{err}</p>}
      </div>
    </Modal>
  );
}

interface PartDetail { part: Part; usage: { repair_id: number; service_request_id: number; repair_date: string; serial_number: string; quantity_used: number; unit_cost_at_repair: number; line_total: number }[];
  monthly_consumption: { month: string; consumed: number }[]; transactions: Txn[] }
interface Txn { inventory_transaction_id: number; created_at: string; transaction_type: string; quantity_change: number; stock_after: number; repair_id: number | null; reason: string | null; username: string | null; part_number?: string; part_name?: string }

function PartDrawer({ partId, onClose }: { partId: number | null; onClose: () => void }) {
  const state = useApi<PartDetail>(partId ? `/inventory/parts/${partId}` : null);
  return (
    <Modal open={partId !== null} onClose={onClose} title="Part usage & history" width="lg">
      <Async state={state}>
        {(d) => (
          <div className="space-y-4">
            <KeyValue cols={3} items={[["Part", <span className="font-mono">{d.part.part_number}</span>], ["Name", d.part.part_name], ["Component", d.part.component_name],
              ["Stock", <b className={d.part.low_stock ? "text-warn" : ""}>{d.part.stock_quantity}</b>], ["Reorder level", d.part.reorder_level], ["Unit cost", money(d.part.unit_cost)]]} />
            <ChartCard title="Consumption (last 12 months)" height={150} empty={!d.monthly_consumption.length}>
              <BarChart data={d.monthly_consumption} margin={{ left: -20, right: 8 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} /><XAxis dataKey="month" tick={CHART.axis} tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} tick={CHART.axis} tickLine={false} axisLine={false} /><Tooltip />
                <Bar isAnimationActive={false} dataKey="consumed" name="Units used" fill={CHART.accent} barSize={16} />
              </BarChart>
            </ChartCard>
            <Card title="Used in repairs" bodyClass="p-0">
              <DataTable dense rows={d.usage} rowKey={(u) => u.repair_id} emptyTitle="Not used in any repair yet" columns={[
                { key: "d", header: "Date", render: (u) => dateTime(u.repair_date) }, { key: "sr", header: "SR", render: (u) => `#${u.service_request_id}` },
                { key: "s", header: "Serial", render: (u) => <span className="font-mono text-xs">{u.serial_number}</span> },
                { key: "q", header: "Qty", align: "right", render: (u) => u.quantity_used },
                { key: "c", header: "Cost at repair", align: "right", render: (u) => money(u.unit_cost_at_repair) },
              ]} />
            </Card>
            <Card title="Stock ledger" bodyClass="p-0"><TxnTable rows={d.transactions} /></Card>
          </div>
        )}
      </Async>
    </Modal>
  );
}

function TxnTable({ rows, showPart }: { rows: Txn[] | undefined; showPart?: boolean }) {
  return (
    <DataTable dense rows={rows} rowKey={(t) => t.inventory_transaction_id} columns={[
      { key: "d", header: "When", render: (t) => <span className="text-xs">{dateTime(t.created_at)}</span> },
      ...(showPart ? [{ key: "p", header: "Part", render: (t: Txn) => <span className="font-mono text-xs">{t.part_number}</span> }] : []),
      { key: "t", header: "Type", render: (t) => <Badge tone={t.transaction_type === "Repair Consumption" ? "info" : t.transaction_type === "Adjustment" ? "warn" : "ok"}>{t.transaction_type}</Badge> },
      { key: "q", header: "Change", align: "right", render: (t) => <span className={t.quantity_change < 0 ? "text-bad" : "text-ok"}>{t.quantity_change > 0 ? "+" : ""}{t.quantity_change}</span> },
      { key: "a", header: "Stock after", align: "right", render: (t) => t.stock_after },
      { key: "r", header: "Reference", render: (t) => <span className="text-xs text-ink-3">{t.repair_id ? `Repair #${t.repair_id}` : t.reason}</span> },
      { key: "u", header: "By", render: (t) => <span className="text-xs text-ink-3">{t.username ?? "system"}</span> },
    ]} />
  );
}

function Ledger() {
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const state = useApi<Page<Txn>>(`/inventory/transactions${qs({ transaction_type: type, page, page_size: 30 })}`);
  return (
    <Card bodyClass="p-0" title="Inventory transaction history" subtitle="Every stock movement; stock_quantity always equals the sum of this ledger.">
      <FilterBar><FilterSelect label="Type" value={type} onChange={(v) => { setType(v); setPage(1); }} options={["Initial Stock", "Restock", "Repair Consumption", "Adjustment"]} /></FilterBar>
      {state.error ? <TxnTable rows={undefined} /> : <TxnTable rows={state.data?.items} showPart />}
      {state.data && <Pagination page={page} pageSize={30} total={state.data.total} onPage={setPage} />}
    </Card>
  );
}

function CostAnalysis() {
  const state = useApi<{ by_part: { part_id: number; part_number: string; part_name: string; component_name: string; total_quantity_used: number; total_cost_at_repair: number }[];
    by_component: { component_name: string; quantity: number; cost: number }[]; stock_value: { value: number; units: number } }>("/inventory/cost-analysis");
  return (
    <Async state={state}>
      {(d) => (
        <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
          <div className="col-span-2 grid grid-cols-3 gap-3 max-lg:col-span-1">
            <StatTile label="Stock on hand (at cost)" value={money(d.stock_value.value)} sub={`${number(d.stock_value.units)} units`} />
            <StatTile label="Lifetime parts spend" value={money(d.by_component.reduce((s, c) => s + c.cost, 0))} />
            <StatTile label="Units consumed" value={number(d.by_component.reduce((s, c) => s + c.quantity, 0))} />
          </div>
          <ChartCard title="Parts spend by component" height={300}>
            <BarChart data={d.by_component.slice(0, 12)} layout="vertical" margin={{ left: 40, right: 16 }}>
              <CartesianGrid stroke={CHART.grid} horizontal={false} />
              <XAxis type="number" tick={CHART.axis} tickFormatter={(v) => `${Math.round(v / 1000)}k`} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="component_name" width={120} tick={CHART.axis} tickLine={false} axisLine={false} />
              <Tooltip formatter={(v) => money(Number(v))} />
              <Bar isAnimationActive={false} dataKey="cost" name="Spend" fill={CHART.navy} barSize={12} />
            </BarChart>
          </ChartCard>
          <Card title="Top parts by spend" bodyClass="p-0">
            <DataTable dense rows={d.by_part} rowKey={(r) => r.part_id} columns={[
              { key: "p", header: "Part", render: (r) => <span><span className="font-mono text-xs">{r.part_number}</span> <span className="text-ink-3">{r.part_name}</span></span> },
              { key: "q", header: "Used", align: "right", render: (r) => r.total_quantity_used },
              { key: "$", header: "Spend", align: "right", render: (r) => money(r.total_cost_at_repair) },
            ]} />
          </Card>
        </div>
      )}
    </Async>
  );
}

export default function Inventory() {
  const [sp] = useSearchParams();
  const { hasRole } = useAuth();
  const manager = hasRole("admin", "service_manager");
  const [tab, setTab] = useState<"parts" | "ledger" | "costs">("parts");
  const list = useList<Part>("/inventory/parts", { low_stock: sp.get("low") ? true : undefined, sort: "part_number" });
  const comps = useApi<Component[]>("/catalog/components");
  const low = useApi<unknown[]>("/inventory/low-stock");
  const [editing, setEditing] = useState<Part | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [adjusting, setAdjusting] = useState<Part | null>(null);
  const [detail, setDetail] = useState<number | null>(null);
  const f = list.filters;
  const refresh = () => { list.reload(); low.reload(); };
  return (
    <>
      <PageHeader title="Spare-parts inventory" description="Stock levels, reorder alerts, consumption by repair and cost analysis."
        actions={manager && <Button variant="primary" icon={<Plus className="size-3.5" />} onClick={() => { setEditing(null); setFormOpen(true); }}>Register part</Button>} />
      {low.data && low.data.length > 0 && (
        <button onClick={() => { setTab("parts"); list.set("low_stock", true); }}
          className="mb-4 flex w-full items-center gap-2 rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-left text-xs text-warn">
          <PackagePlus className="size-4" /> <b>{low.data.length} part(s)</b> are at or below their reorder level. Show them →
        </button>
      )}
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "parts", label: "Parts" }, { id: "ledger", label: "Transactions" }, { id: "costs", label: "Cost analysis" }]} />
      {tab === "parts" && (
        <Card bodyClass="p-0">
          <FilterBar>
            <SearchInput className="w-64" placeholder="Part number, name or supplier" value={String(f.q ?? "")} onChange={(v) => list.set("q", v)} />
            <FilterSelect label="Component" value={String(f.component_id ?? "")} onChange={(v) => list.set("component_id", v)}
              options={(comps.data ?? []).map((c) => ({ value: String(c.component_id), label: c.component_name }))} />
            <FilterSelect label="Sort" allLabel="Part number" value={f.sort === "part_number" ? "" : String(f.sort)} onChange={(v) => list.set("sort", v || "part_number")}
              options={[{ value: "shortfall", label: "Closest to reorder" }, { value: "stock", label: "Lowest stock" }, { value: "cost", label: "Highest cost" }]} />
            <Checkbox label="Low stock only" checked={!!f.low_stock} onChange={(e) => list.set("low_stock", e.target.checked || undefined)} />
          </FilterBar>
          <DataTable rows={list.data?.items} loading={list.loading} error={list.error} onRetry={list.reload} rowKey={(p) => p.part_id}
            onRowClick={(p) => setDetail(p.part_id)} columns={[
              { key: "n", header: "Part number", render: (p) => <span className="font-mono text-xs font-medium">{p.part_number}</span> },
              { key: "m", header: "Name", render: (p) => p.part_name },
              { key: "c", header: "Component", render: (p) => p.component_name ?? "—" },
              { key: "s", header: "Supplier", render: (p) => <span className="text-ink-3">{p.supplier_name ?? "—"}</span> },
              { key: "u", header: "Unit cost", align: "right", render: (p) => money(p.unit_cost) },
              { key: "q", header: "Stock", align: "right", render: (p) => <span className={p.stock_quantity === 0 ? "font-semibold text-bad" : p.low_stock ? "font-semibold text-warn" : ""}>{p.stock_quantity}</span> },
              { key: "r", header: "Reorder at", align: "right", render: (p) => p.reorder_level },
              { key: "st", header: "", render: (p) => p.low_stock ? <Badge tone={p.stock_quantity === 0 ? "bad" : "warn"}>{p.stock_quantity === 0 ? "Out of stock" : "Reorder"}</Badge> : null },
              { key: "a", header: "", render: (p) => manager ? (
                <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                  <Button size="sm" variant="ghost" aria-label={`Adjust stock ${p.part_number}`} title="Restock / adjust" icon={<SlidersHorizontal className="size-3.5" />} onClick={() => setAdjusting(p)} />
                  <Button size="sm" variant="ghost" aria-label={`Edit ${p.part_number}`} title="Edit" icon={<Pencil className="size-3.5" />} onClick={() => { setEditing(p); setFormOpen(true); }} />
                </div>) : null },
            ]} />
          {list.data && <Pagination page={list.page} pageSize={list.pageSize} total={list.data.total} onPage={list.setPage} />}
        </Card>
      )}
      {tab === "ledger" && <Ledger />}
      {tab === "costs" && <CostAnalysis />}
      <PartForm open={formOpen} part={editing} onClose={() => setFormOpen(false)} onSaved={() => { setFormOpen(false); refresh(); }} />
      <AdjustModal key={adjusting?.part_id ?? 0} part={adjusting} onClose={() => setAdjusting(null)} onSaved={() => { setAdjusting(null); refresh(); }} />
      <PartDrawer partId={detail} onClose={() => setDetail(null)} />
    </>
  );
}
