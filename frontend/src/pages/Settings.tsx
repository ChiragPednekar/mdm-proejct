import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useAuth } from "../lib/auth";
import { dateTime } from "../lib/format";
import type { Technician } from "../lib/types";
import { Async, Button, Card, KeyValue, PageHeader, StatusBadge, Tabs } from "../components/ui/primitives";
import { DataTable } from "../components/ui/DataTable";
import { Field, Input, Select } from "../components/ui/Form";
import { Modal } from "../components/ui/Modal";
import { useToast } from "../components/ui/Toast";

type S = { risk_band_medium_min: number; risk_band_high_min: number; prediction_horizon_days: number; repeat_failure_window_days: number; expiring_soon_days: number; dataset_provenance: string };

function General() {
  const toast = useToast();
  const { hasRole } = useAuth();
  const admin = hasRole("admin");
  const state = useApi<S>("/settings");
  const [v, setV] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (state.data) setV(Object.fromEntries(Object.entries(state.data).map(([k, x]) => [k, String(x)]))); }, [state.data]);
  const med = Number(v.risk_band_medium_min), high = Number(v.risk_band_high_min);
  const err = !(med > 0 && med < 1 && high > 0 && high < 1) ? "Bands must be between 0 and 1" : med >= high ? "Medium must start below High" : null;
  const save = async () => {
    setBusy(true);
    try {
      await api("/settings", { method: "PUT", json: { risk_band_medium_min: med, risk_band_high_min: high,
        prediction_horizon_days: Number(v.prediction_horizon_days), repeat_failure_window_days: Number(v.repeat_failure_window_days),
        expiring_soon_days: Number(v.expiring_soon_days) } });
      toast.success("Settings saved"); state.reload();
    } catch (e) { toast.error(e); } finally { setBusy(false); }
  };
  const input = (k: keyof S, label: string, hint: string, step = "1") => (
    <Field label={label} hint={hint}><Input aria-label={label} type="number" step={step} disabled={!admin} value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></Field>
  );
  return (
    <Async state={state}>
      {(s) => (
        <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
          <Card title="Risk bands & prediction" subtitle="Bands label probabilities for communication; they are not the validated decision threshold."
            actions={admin && <Button variant="primary" size="sm" loading={busy} disabled={!!err} onClick={save}>Save</Button>}>
            <div className="grid grid-cols-2 gap-3">
              {input("risk_band_medium_min", "Medium risk from", "Probability (0–1)", "0.01")}
              {input("risk_band_high_min", "High risk from", "Probability (0–1)", "0.01")}
              {input("prediction_horizon_days", "Prediction horizon (days)", "Used for the next training run")}
              {input("repeat_failure_window_days", "Repeat-failure window (days)", "Flags repairs and the dashboard rate")}
              {input("expiring_soon_days", "Expiring-soon window (days)", "Warranty expiry list default")}
              <Field label="Dataset provenance" hint="Set by the seed script; drives demo labelling"><Input aria-label="Dataset provenance" disabled value={s.dataset_provenance} /></Field>
            </div>
            {err && <p role="alert" className="mt-2 text-xs text-bad">{err}</p>}
            {!admin && <p className="mt-2 text-xs text-ink-3">Only administrators can change settings.</p>}
          </Card>
          <Card title="Your account"><AccountInfo /></Card>
        </div>
      )}
    </Async>
  );
}

function AccountInfo() {
  const { user } = useAuth();
  if (!user) return null;
  return <KeyValue items={[["Name", user.full_name], ["Username", user.username], ["Email", user.email], ["Role", user.role.replace("_", " ")]]} />;
}

function Technicians() {
  const toast = useToast();
  const { hasRole } = useAuth();
  const manager = hasRole("admin", "service_manager");
  const state = useApi<Technician[]>("/technicians");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ full_name: "", email: "", specialization: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const valid = form.full_name.trim().length >= 2 && /^\S+@\S+\.\S+$/.test(form.email) && form.specialization.trim().length >= 2;
  const create = async () => {
    setBusy(true); setErr(null);
    try { await api("/technicians", { method: "POST", json: form }); toast.success("Technician added"); setOpen(false); setForm({ full_name: "", email: "", specialization: "" }); state.reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const setStatus = async (t: Technician, employment_status: string) => {
    try { await api(`/technicians/${t.technician_id}`, { method: "PATCH", json: { employment_status } }); toast.success(`${t.full_name}: ${employment_status}`); state.reload(); }
    catch (e) { toast.error(e); }
  };
  return (
    <Card title="Technicians" bodyClass="p-0" actions={manager && <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setOpen(true)}>Add technician</Button>}>
      <DataTable rows={state.data} error={state.error} onRetry={state.reload} rowKey={(t) => t.technician_id} columns={[
        { key: "n", header: "Name", render: (t) => t.full_name }, { key: "e", header: "Email", render: (t) => t.email },
        { key: "s", header: "Specialization", render: (t) => t.specialization },
        { key: "st", header: "Status", render: (t) => manager ? (
          <Select aria-label={`Status of ${t.full_name}`} className="w-32" value={t.employment_status} onChange={(e) => setStatus(t, e.target.value)}>
            <option>Active</option><option>On Leave</option><option>Inactive</option></Select>) : <StatusBadge value={t.employment_status} /> },
      ]} />
      <Modal open={open} onClose={() => setOpen(false)} title="Add technician"
        footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" disabled={!valid} loading={busy} onClick={create}>Add</Button></>}>
        <div className="grid gap-3">
          <Field label="Full name" required><Input aria-label="Technician name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label="Email" required><Input aria-label="Technician email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Specialization" required><Input aria-label="Specialization" value={form.specialization} onChange={(e) => setForm({ ...form, specialization: e.target.value })} /></Field>
          {err && <p role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{err}</p>}
        </div>
      </Modal>
    </Card>
  );
}

function AuditLog() {
  const [entity, setEntity] = useState("");
  const state = useApi<{ audit_log_id: number; timestamp: string; action: string; entity_type: string; entity_id: string | null; details: unknown; username: string | null }[]>(`/audit-logs?limit=200${entity ? `&entity_type=${entity}` : ""}`);
  return (
    <Card title="Audit log" subtitle="Warranty changes, repair completion, inventory movements, predictions and logins." bodyClass="p-0"
      actions={<Select aria-label="Entity type" className="w-48" value={entity} onChange={(e) => setEntity(e.target.value)}>
        <option value="">All entities</option>{["service_request", "repair", "warranty", "part", "product", "customer", "failure_prediction", "model_training_run", "user"].map((x) => <option key={x}>{x}</option>)}</Select>}>
      <DataTable dense rows={state.data} error={state.error} onRetry={state.reload} rowKey={(a) => a.audit_log_id} emptyTitle="No audit entries" columns={[
        { key: "t", header: "When", render: (a) => <span className="text-xs">{dateTime(a.timestamp)}</span> },
        { key: "u", header: "User", render: (a) => a.username ?? "system" },
        { key: "a", header: "Action", render: (a) => <span className="font-mono text-xs">{a.action}</span> },
        { key: "e", header: "Entity", render: (a) => `${a.entity_type}${a.entity_id ? ` #${a.entity_id}` : ""}` },
        { key: "d", header: "Details", className: "whitespace-normal max-w-md", render: (a) => <span className="line-clamp-1 font-mono text-[11px] text-ink-3" title={JSON.stringify(a.details)}>{a.details ? JSON.stringify(a.details) : ""}</span> },
      ]} />
    </Card>
  );
}

export default function SettingsPage() {
  const { hasRole } = useAuth();
  const [tab, setTab] = useState<"general" | "technicians" | "audit">("general");
  const tabs: { id: typeof tab; label: string }[] = [{ id: "general", label: "General" }, { id: "technicians", label: "Technicians" }];
  if (hasRole("admin", "service_manager")) tabs.push({ id: "audit", label: "Audit log" });
  return (
    <>
      <PageHeader title="Settings" description="Risk bands, analytic windows, technicians and the audit trail." />
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      {tab === "general" && <General />}
      {tab === "technicians" && <Technicians />}
      {tab === "audit" && <AuditLog />}
    </>
  );
}
