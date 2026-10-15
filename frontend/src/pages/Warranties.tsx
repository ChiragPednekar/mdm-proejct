import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Bar, BarChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis } from "recharts";
import { Plus, ShieldOff, ShieldPlus } from "lucide-react";
import { api, qs } from "../lib/api";
import { useApi, useDebounced } from "../lib/hooks";
import { useList } from "../lib/useList";
import { useAuth } from "../lib/auth";
import { date, dateTime, money } from "../lib/format";
import type { Page, ProductRow, Warranty } from "../lib/types";
import { Async, Badge, Button, Card, PageHeader, StatusBadge, Tabs } from "../components/ui/primitives";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { Checkbox, Field, FilterBar, FilterSelect, Input, SearchInput, Select, Textarea } from "../components/ui/Form";
import { ConfirmDialog, Modal } from "../components/ui/Modal";
import { CHART, ChartCard } from "../components/ui/Chart";
import { useToast } from "../components/ui/Toast";
import { ExtendWarrantyModal } from "../components/ExtendWarrantyModal";

type Tab = "all" | "expiring" | "claims" | "spend";

const regSchema = z.object({
  product_id: z.coerce.number({ invalid_type_error: "Select a product" }).int().positive("Select a product"),
  warranty_type: z.enum(["Manufacturer", "Extended", "Accidental Damage Protection"]),
  start_date: z.string().min(1, "Required"),
  end_date: z.string().min(1, "Required"),
  coverage_details: z.string().optional(),
  covers_parts: z.boolean(), covers_labor: z.boolean(), covers_wear_and_tear: z.boolean(), covers_accidental_damage: z.boolean(),
}).refine((v) => v.end_date > v.start_date, { path: ["end_date"], message: "End date must be after start date" });
type RegValues = z.infer<typeof regSchema>;

function RegisterWarranty({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 250);
  const products = useApi<Page<ProductRow>>(open ? `/products${qs({ q: dq, page_size: 10 })}` : null);
  const [err, setErr] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<RegValues>({
    resolver: zodResolver(regSchema),
    defaultValues: { warranty_type: "Extended", covers_parts: true, covers_labor: true, covers_wear_and_tear: false, covers_accidental_damage: false },
  });
  const onSubmit = async (v: RegValues) => {
    setErr(null);
    try { await api("/warranties", { method: "POST", json: v }); toast.success("Warranty registered"); onSaved(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Register warranty" width="lg"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={isSubmitting} onClick={handleSubmit(onSubmit)}>Register</Button></>}>
      <form noValidate className="grid grid-cols-2 gap-3" onSubmit={handleSubmit(onSubmit)}>
        <Field label="Find product"><Input aria-label="Find product" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Serial or customer" /></Field>
        <Field label="Product" required error={errors.product_id?.message}>
          <Select aria-label="Product" {...register("product_id")}>
            <option value="">Select…</option>
            {products.data?.items.map((p) => <option key={p.product_id} value={p.product_id}>{p.serial_number} — {p.customer_name}</option>)}
          </Select>
        </Field>
        <Field label="Type"><Select aria-label="Warranty type" {...register("warranty_type")}>
          <option>Manufacturer</option><option>Extended</option><option>Accidental Damage Protection</option></Select></Field>
        <div />
        <Field label="Start date" required error={errors.start_date?.message}><Input aria-label="Start date" type="date" {...register("start_date")} /></Field>
        <Field label="End date" required error={errors.end_date?.message}><Input aria-label="End date" type="date" {...register("end_date")} /></Field>
        <div className="col-span-2 grid grid-cols-2 gap-2">
          <Checkbox label="Covers parts" {...register("covers_parts")} /><Checkbox label="Covers labor" {...register("covers_labor")} />
          <Checkbox label="Covers wear and tear" {...register("covers_wear_and_tear")} /><Checkbox label="Covers accidental damage" {...register("covers_accidental_damage")} />
        </div>
        <div className="col-span-2"><Field label="Coverage details"><Textarea aria-label="Coverage details" {...register("coverage_details")} /></Field></div>
        {err && <p role="alert" className="col-span-2 rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{err}</p>}
      </form>
    </Modal>
  );
}

function AllWarranties() {
  const nav = useNavigate();
  const toast = useToast();
  const { hasRole } = useAuth();
  const manager = hasRole("admin", "service_manager");
  const list = useList<Warranty>("/warranties", { sort: "end_date" });
  const [extendId, setExtendId] = useState<number | null>(null);
  const [voiding, setVoiding] = useState<Warranty | null>(null);
  const [reason, setReason] = useState("");
  const [regOpen, setRegOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const f = list.filters;
  const doVoid = async () => {
    if (!voiding || reason.trim().length < 5) return;
    setBusy(true);
    try { await api(`/warranties/${voiding.warranty_id}/void`, { method: "POST", json: { reason } }); toast.success("Warranty voided"); list.reload(); }
    catch (e) { toast.error(e); } finally { setBusy(false); setVoiding(null); setReason(""); }
  };
  return (
    <>
      <Card bodyClass="p-0" title="Warranty contracts" subtitle="Status is derived from dates and administrative state, never trusted from a stored flag alone."
        actions={manager && <Button size="sm" variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setRegOpen(true)}>Register warranty</Button>}>
        <FilterBar>
          <SearchInput className="w-64" placeholder="Serial or customer" value={String(f.q ?? "")} onChange={(v) => list.set("q", v)} />
          <FilterSelect label="Status" value={String(f.effective_status ?? "")} onChange={(v) => list.set("effective_status", v)} options={["Active", "Pending", "Expired", "Voided", "Cancelled"]} />
          <FilterSelect label="Type" value={String(f.warranty_type ?? "")} onChange={(v) => list.set("warranty_type", v)} options={["Manufacturer", "Extended", "Accidental Damage Protection"]} />
          <FilterSelect label="Category" value={String(f.category ?? "")} onChange={(v) => list.set("category", v)} options={["Laptop", "Refrigerator", "Washing Machine", "Air Conditioner", "Television"]} />
          <FilterSelect label="Sort" allLabel="Ending soonest" value={f.sort === "end_date" ? "" : String(f.sort)} onChange={(v) => list.set("sort", v || "end_date")}
            options={[{ value: "-end_date", label: "Ending latest" }, { value: "-start_date", label: "Newest" }]} />
        </FilterBar>
        <DataTable rows={list.data?.items} loading={list.loading} error={list.error} onRetry={list.reload} rowKey={(w) => w.warranty_id}
          onRowClick={(w) => nav(`/products/${w.product_id}`)}
          columns={[
            { key: "id", header: "#", render: (w) => <span className="text-ink-3">{w.warranty_id}</span> },
            { key: "s", header: "Serial", render: (w) => <span className="font-mono text-xs">{w.serial_number}</span> },
            { key: "c", header: "Customer", render: (w) => w.customer_name },
            { key: "t", header: "Type", render: (w) => <span>{w.warranty_type}{w.parent_warranty_id && <span className="text-ink-4"> ↳ #{w.parent_warranty_id}</span>}</span> },
            { key: "p", header: "Coverage period", render: (w) => <span className="text-xs">{date(w.start_date)} – {date(w.end_date)}</span> },
            { key: "d", header: "Days left", align: "right", render: (w) => w.effective_status === "Active" ? w.days_remaining : "—" },
            { key: "terms", header: "Covers", render: (w) => <span className="text-[11px] text-ink-3">{[w.covers_parts && "parts", w.covers_labor && "labor", w.covers_wear_and_tear && "wear", w.covers_accidental_damage && "accidents"].filter(Boolean).join(", ")}</span> },
            { key: "st", header: "Status", render: (w) => <StatusBadge value={w.effective_status} /> },
            { key: "a", header: "", render: (w) => manager && w.warranty_status === "Valid" && w.effective_status !== "Expired" ? (
              <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                <Button size="sm" variant="ghost" title="Extend" aria-label={`Extend warranty ${w.warranty_id}`} icon={<ShieldPlus className="size-3.5" />} onClick={() => setExtendId(w.warranty_id)} />
                <Button size="sm" variant="ghost" title="Void" aria-label={`Void warranty ${w.warranty_id}`} icon={<ShieldOff className="size-3.5" />} onClick={() => setVoiding(w)} />
              </div>) : null },
          ]} />
        {list.data && <Pagination page={list.page} pageSize={list.pageSize} total={list.data.total} onPage={list.setPage} />}
      </Card>
      <ExtendWarrantyModal warrantyId={extendId} onClose={() => setExtendId(null)} onDone={() => { setExtendId(null); list.reload(); }} />
      <RegisterWarranty open={regOpen} onClose={() => setRegOpen(false)} onSaved={() => { setRegOpen(false); list.reload(); }} />
      <ConfirmDialog open={!!voiding} danger title={`Void warranty #${voiding?.warranty_id}`} confirmLabel="Void warranty" loading={busy}
        onCancel={() => { setVoiding(null); setReason(""); }} onConfirm={doVoid}
        message={<div className="space-y-2"><p>Voiding stops all future coverage. Past claim decisions are kept.</p>
          <Field label="Reason (min. 5 characters)" required><Textarea aria-label="Void reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field></div>} />
    </>
  );
}

function Expiring() {
  const nav = useNavigate();
  const [days, setDays] = useState("60");
  const state = useApi<{ days: number; items: (Warranty & { phone: string | null; email: string | null; has_follow_on: boolean })[] }>(`/warranties/expiring?days=${days || 60}`);
  return (
    <Card bodyClass="p-0" title="Warranties expiring soon" subtitle="Active coverage ending within the window — candidates for extension offers."
      actions={<Select aria-label="Window" value={days} onChange={(e) => setDays(e.target.value)} className="w-32">
        {["30", "60", "90", "180"].map((d) => <option key={d} value={d}>Next {d} days</option>)}</Select>}>
      <DataTable rows={state.data?.items} loading={state.loading} error={state.error} onRetry={state.reload} rowKey={(w) => w.warranty_id}
        onRowClick={(w) => nav(`/products/${w.product_id}`)} emptyTitle="No warranties expire in this window"
        columns={[
          { key: "s", header: "Serial", render: (w) => <span className="font-mono text-xs">{w.serial_number}</span> },
          { key: "m", header: "Model", render: (w) => w.model_name },
          { key: "c", header: "Customer", render: (w) => w.customer_name },
          { key: "ct", header: "Contact", render: (w) => <span className="text-xs text-ink-3">{w.phone ?? w.email}</span> },
          { key: "t", header: "Type", render: (w) => w.warranty_type },
          { key: "e", header: "Ends", render: (w) => date(w.end_date) },
          { key: "d", header: "Days left", align: "right", render: (w) => <span className={w.days_remaining <= 14 ? "font-medium text-warn" : ""}>{w.days_remaining}</span> },
          { key: "f", header: "Follow-on", render: (w) => w.has_follow_on ? <Badge tone="ok">Extension booked</Badge> : <Badge>None</Badge> },
        ]} />
    </Card>
  );
}

interface Claim { service_request_id: number; reported_at: string; serial_number: string; model_name: string; fault_category: string; warranty_id: number; warranty_type: string; warranty_covered: boolean; coverage_notes: string; request_status: string; warranty_cost: number; total_cost: number }
function Claims() {
  const nav = useNavigate();
  const [covered, setCovered] = useState("");
  const [page, setPage] = useState(1);
  const state = useApi<Page<Claim>>(`/warranties/claims${qs({ covered, page, page_size: 25 })}`);
  return (
    <Card bodyClass="p-0" title="Historical warranty claims" subtitle="Service requests evaluated against a warranty, with the recorded coverage decision.">
      <FilterBar><FilterSelect label="Decision" value={covered} onChange={(v) => { setCovered(v); setPage(1); }}
        options={[{ value: "true", label: "Covered" }, { value: "false", label: "Rejected" }]} /></FilterBar>
      <DataTable rows={state.data?.items} loading={state.loading} error={state.error} onRetry={state.reload} rowKey={(c) => c.service_request_id}
        onRowClick={(c) => nav(`/service-requests/${c.service_request_id}`)}
        columns={[
          { key: "id", header: "SR", render: (c) => `#${c.service_request_id}` },
          { key: "d", header: "Reported", render: (c) => dateTime(c.reported_at) },
          { key: "s", header: "Serial", render: (c) => <span className="font-mono text-xs">{c.serial_number}</span> },
          { key: "f", header: "Fault", render: (c) => c.fault_category },
          { key: "w", header: "Warranty", render: (c) => `#${c.warranty_id} ${c.warranty_type}` },
          { key: "dec", header: "Decision", render: (c) => c.warranty_covered ? <Badge tone="ok">Covered</Badge> : <Badge tone="bad" title={c.coverage_notes}>Rejected</Badge> },
          { key: "n", header: "Reason", className: "whitespace-normal max-w-xs", render: (c) => <span className="line-clamp-1 text-xs text-ink-3" title={c.coverage_notes}>{c.coverage_notes}</span> },
          { key: "wc", header: "Warranty cost", align: "right", render: (c) => money(c.warranty_cost) },
          { key: "tc", header: "Total", align: "right", render: (c) => money(c.total_cost) },
        ]} />
      {state.data && <Pagination page={page} pageSize={25} total={state.data.total} onPage={setPage} />}
    </Card>
  );
}

function Spend() {
  const state = useApi<{ monthly: { month: string; warranty_cost: number; customer_cost: number }[]; by_type: { warranty_type: string; repairs: number; warranty_cost: number; total_cost: number }[]; by_category: { category: string; warranty_cost: number; repairs: number }[] }>("/warranties/expenditure?months=24");
  return (
    <Async state={state}>
      {(d) => (
        <div className="grid grid-cols-3 gap-4 max-lg:grid-cols-1">
          <div className="col-span-2 max-lg:col-span-1">
            <ChartCard title="Monthly repair expenditure" subtitle="Last 24 months: warranty-borne vs customer-paid" height={280} empty={!d.monthly.length}>
              <BarChart data={d.monthly} margin={{ left: 0, right: 12 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="month" tick={CHART.axis} tickLine={false} axisLine={false} />
                <YAxis tick={CHART.axis} tickLine={false} axisLine={false} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <Tooltip formatter={(v) => money(Number(v))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar isAnimationActive={false} dataKey="warranty_cost" name="Warranty" stackId="a" fill={CHART.accent} />
                <Bar isAnimationActive={false} dataKey="customer_cost" name="Customer" stackId="a" fill={CHART.muted} />
              </BarChart>
            </ChartCard>
          </div>
          <div className="space-y-4">
            <Card title="By warranty type" bodyClass="p-0">
              <DataTable dense rows={d.by_type} rowKey={(r) => r.warranty_type} columns={[
                { key: "t", header: "Type", render: (r) => r.warranty_type },
                { key: "n", header: "Repairs", align: "right", render: (r) => r.repairs },
                { key: "w", header: "Warranty cost", align: "right", render: (r) => money(r.warranty_cost) },
              ]} />
            </Card>
            <Card title="By product category" bodyClass="p-0">
              <DataTable dense rows={d.by_category} rowKey={(r) => r.category} columns={[
                { key: "c", header: "Category", render: (r) => r.category },
                { key: "w", header: "Warranty cost", align: "right", render: (r) => money(r.warranty_cost) },
              ]} />
            </Card>
          </div>
        </div>
      )}
    </Async>
  );
}

export default function Warranties() {
  const [tab, setTab] = useState<Tab>("all");
  return (
    <>
      <PageHeader title="Warranty management" description="Registration, extension, expiry tracking, claim decisions and expenditure." />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "all", label: "All warranties" }, { id: "expiring", label: "Expiring soon" },
        { id: "claims", label: "Claims history" }, { id: "spend", label: "Expenditure" },
      ]} />
      {tab === "all" && <AllWarranties />}
      {tab === "expiring" && <Expiring />}
      {tab === "claims" && <Claims />}
      {tab === "spend" && <Spend />}
    </>
  );
}
