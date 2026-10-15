import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useList } from "../lib/useList";
import { useAuth } from "../lib/auth";
import { date } from "../lib/format";
import type { Customer } from "../lib/types";
import { Button, Card, PageHeader } from "../components/ui/primitives";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { Field, FilterBar, FilterSelect, Input, SearchInput } from "../components/ui/Form";
import { ConfirmDialog, Modal } from "../components/ui/Modal";
import { useToast } from "../components/ui/Toast";

export const customerSchema = z.object({
  full_name: z.string().trim().min(2, "Name must have at least 2 characters").max(120),
  email: z.string().trim().email("Enter a valid email").or(z.literal("")),
  phone: z.string().trim().regex(/^\+?[0-9 ()-]{7,20}$/, "Enter a valid phone number").or(z.literal("")),
  address: z.string().trim().max(255).optional(),
  city: z.string().trim().max(80).optional(),
}).refine((v) => v.email || v.phone, { path: ["phone"], message: "Provide a phone number or an email address" });
type Values = z.infer<typeof customerSchema>;

export function CustomerForm({ customer, open, onClose, onSaved }: { customer: Customer | null; open: boolean; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(customerSchema),
    values: { full_name: customer?.full_name ?? "", email: customer?.email ?? "", phone: customer?.phone ?? "",
      address: customer?.address ?? "", city: customer?.city ?? "" },
  });
  const onSubmit = async (v: Values) => {
    setServerError(null);
    const json = { ...v, email: v.email || null, phone: v.phone || null, address: v.address || null, city: v.city || null };
    try {
      if (customer) await api(`/customers/${customer.customer_id}`, { method: "PATCH", json });
      else await api("/customers", { method: "POST", json });
      toast.success(customer ? "Customer updated" : "Customer registered");
      onSaved();
    } catch (e) {
      if (e instanceof ApiError) {
        const fe = e.fieldErrors();
        Object.entries(fe).forEach(([k, m]) => setError(k as keyof Values, { message: m }));
        if (e.code === "integrity_error") setError("email", { message: e.message });
        else if (!Object.keys(fe).length) setServerError(e.message);
      } else setServerError(String(e));
    }
  };
  return (
    <Modal open={open} onClose={onClose} title={customer ? `Edit ${customer.full_name}` : "Register customer"}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={isSubmitting} onClick={handleSubmit(onSubmit)}>Save</Button></>}>
      <form noValidate onSubmit={handleSubmit(onSubmit)} className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><Field label="Full name" required error={errors.full_name?.message} htmlFor="c-name">
          <Input id="c-name" aria-invalid={!!errors.full_name} {...register("full_name")} /></Field></div>
        <Field label="Email" error={errors.email?.message} htmlFor="c-email"><Input id="c-email" type="email" {...register("email")} /></Field>
        <Field label="Phone" error={errors.phone?.message} htmlFor="c-phone"><Input id="c-phone" {...register("phone")} placeholder="+91 98765 43210" /></Field>
        <Field label="Address" htmlFor="c-addr"><Input id="c-addr" {...register("address")} /></Field>
        <Field label="City" htmlFor="c-city"><Input id="c-city" {...register("city")} /></Field>
        <p className="col-span-2 text-[11px] text-ink-3">At least one contact method is required. Contact details are personal data: share only for service purposes.</p>
        {serverError && <p role="alert" className="col-span-2 rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{serverError}</p>}
      </form>
    </Modal>
  );
}

export default function Customers() {
  const nav = useNavigate();
  const toast = useToast();
  const { hasRole } = useAuth();
  const [sp] = useSearchParams();
  const list = useList<Customer>("/customers", { sort: "name", q: sp.get("q") ?? "" });
  const cities = useApi<string[]>("/customers/cities");
  const [editing, setEditing] = useState<Customer | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [deleting, setDeleting] = useState<Customer | null>(null);
  const [busy, setBusy] = useState(false);
  const f = list.filters;

  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    try { await api(`/customers/${deleting.customer_id}`, { method: "DELETE" }); toast.success("Customer deleted"); list.reload(); }
    catch (e) { toast.error(e); } finally { setBusy(false); setDeleting(null); }
  };

  return (
    <>
      <PageHeader title="Customers" description="Registered owners. Select a customer to see their products."
        actions={<Button variant="primary" icon={<Plus className="size-3.5" />} onClick={() => { setEditing(null); setFormOpen(true); }}>Register customer</Button>} />
      <Card bodyClass="p-0">
        <FilterBar>
          <SearchInput className="w-72" placeholder="Name, email or phone" value={String(f.q ?? "")} onChange={(v) => list.set("q", v)} />
          <FilterSelect label="City" value={String(f.city ?? "")} onChange={(v) => list.set("city", v)} options={cities.data ?? []} />
          <FilterSelect label="Sort" allLabel="Name" value={f.sort === "name" ? "" : String(f.sort)} onChange={(v) => list.set("sort", v || "name")}
            options={[{ value: "newest", label: "Newest" }, { value: "requests", label: "Most service requests" }]} />
        </FilterBar>
        <DataTable rows={list.data?.items} loading={list.loading} error={list.error} onRetry={list.reload} rowKey={(c) => c.customer_id}
          onRowClick={(c) => nav(`/products?customer_id=${c.customer_id}`)}
          columns={[
            { key: "n", header: "Name", render: (c) => <span className="font-medium">{c.full_name}</span> },
            { key: "e", header: "Email", render: (c) => c.email ?? <span className="text-ink-4">—</span> },
            { key: "p", header: "Phone", render: (c) => <span className="tabular">{c.phone ?? "—"}</span> },
            { key: "c", header: "City", render: (c) => c.city ?? "—" },
            { key: "pr", header: "Products", align: "right", render: (c) => c.product_count },
            { key: "sr", header: "Service requests", align: "right", render: (c) => c.service_request_count },
            { key: "d", header: "Since", render: (c) => date(c.created_at) },
            { key: "a", header: "", render: (c) => (
              <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                <Button size="sm" variant="ghost" aria-label={`Edit ${c.full_name}`} icon={<Pencil className="size-3.5" />} onClick={() => { setEditing(c); setFormOpen(true); }} />
                {hasRole("admin", "service_manager") && (
                  <Button size="sm" variant="ghost" aria-label={`Delete ${c.full_name}`} icon={<Trash2 className="size-3.5" />} onClick={() => setDeleting(c)} />
                )}
              </div>
            ) },
          ]} />
        {list.data && <Pagination page={list.page} pageSize={list.pageSize} total={list.data.total} onPage={list.setPage} />}
      </Card>
      <CustomerForm open={formOpen} customer={editing} onClose={() => setFormOpen(false)} onSaved={() => { setFormOpen(false); list.reload(); }} />
      <ConfirmDialog open={!!deleting} danger title="Delete customer" confirmLabel="Delete" loading={busy}
        message={<>Delete <b>{deleting?.full_name}</b>? Customers who own registered products cannot be deleted; history is preserved.</>}
        onConfirm={remove} onCancel={() => setDeleting(null)} />
    </>
  );
}
