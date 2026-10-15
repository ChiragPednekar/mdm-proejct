import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ShieldCheck, ShieldX } from "lucide-react";
import { api, qs } from "../lib/api";
import { useApi, useDebounced } from "../lib/hooks";
import type { FaultCategory, Page, ProductRow, Technician } from "../lib/types";
import { Modal } from "./ui/Modal";
import { Button } from "./ui/primitives";
import { Field, Input, Select, Textarea } from "./ui/Form";
import { useToast } from "./ui/Toast";

const schema = z.object({
  product_id: z.coerce.number({ invalid_type_error: "Select a product" }).int().positive("Select a product"),
  fault_category_id: z.coerce.number({ invalid_type_error: "Select a fault category" }).int().positive("Select a fault category"),
  complaint_description: z.string().trim().min(5, "Describe the complaint (at least 5 characters)").max(2000),
  priority: z.enum(["Low", "Medium", "High", "Critical"]),
  failure_severity: z.enum(["Minor", "Moderate", "Major", "Critical"]),
  assigned_technician_id: z.string().optional(),
});
type Values = z.infer<typeof schema>;
interface Coverage { covered: boolean; warranty_id: number | null; covers_parts: boolean; covers_labor: boolean; reasons: string[] }

export function ServiceRequestForm({ open, onClose, onCreated, productId }: {
  open: boolean; onClose: () => void; onCreated: (id: number) => void; productId?: number;
}) {
  const toast = useToast();
  const faults = useApi<FaultCategory[]>(open ? "/catalog/fault-categories" : null);
  const techs = useApi<Technician[]>(open ? "/technicians?active_only=true" : null);
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 250);
  const products = useApi<Page<ProductRow>>(open && !productId ? `/products${qs({ q: dq, page_size: 10 })}` : null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, watch, reset, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { product_id: productId, priority: "Medium", failure_severity: "Moderate", complaint_description: "", assigned_technician_id: "" },
  });
  const pid = watch("product_id");
  const fid = watch("fault_category_id");

  // Live warranty check, using the same backend rule the request will be recorded with.
  useEffect(() => {
    setCoverage(null);
    if (!pid || !fid || Number.isNaN(Number(pid)) || Number.isNaN(Number(fid))) return;
    api<Coverage>(`/warranties/coverage-check${qs({ product_id: Number(pid), fault_category_id: Number(fid) })}`)
      .then(setCoverage).catch(() => setCoverage(null));
  }, [pid, fid]);

  const onSubmit = async (v: Values) => {
    setServerError(null);
    try {
      const sr = await api<{ service_request_id: number }>("/service-requests", {
        method: "POST",
        json: { ...v, assigned_technician_id: v.assigned_technician_id ? Number(v.assigned_technician_id) : null },
      });
      toast.success(`Service request #${sr.service_request_id} registered`);
      reset();
      onCreated(sr.service_request_id);
    } catch (e) { setServerError(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <Modal open={open} onClose={onClose} title="Register service request" width="lg"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={isSubmitting} onClick={handleSubmit(onSubmit)}>Register request</Button></>}>
      <form noValidate onSubmit={handleSubmit(onSubmit)} className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
        {!productId && (
          <div className="col-span-2 grid grid-cols-2 gap-3 max-md:col-span-1 max-md:grid-cols-1">
            <Field label="Find product">
              <Input aria-label="Find product" placeholder="Serial number or customer" value={q} onChange={(e) => setQ(e.target.value)} />
            </Field>
            <Field label="Product" required error={errors.product_id?.message}>
              <Select aria-label="Product" {...register("product_id")}>
                <option value="">Select…</option>
                {products.data?.items.map((p) => (
                  <option key={p.product_id} value={p.product_id}>{p.serial_number} — {p.model_name} ({p.customer_name})</option>
                ))}
              </Select>
            </Field>
          </div>
        )}
        <Field label="Fault category" required error={errors.fault_category_id?.message}>
          <Select aria-label="Fault category" {...register("fault_category_id")}>
            <option value="">Select…</option>
            {faults.data?.map((f) => <option key={f.fault_category_id} value={f.fault_category_id}>{f.name}</option>)}
          </Select>
        </Field>
        <Field label="Assign technician" hint="Optional; assigning moves the request to Assigned.">
          <Select aria-label="Assign technician" {...register("assigned_technician_id")}>
            <option value="">Unassigned</option>
            {techs.data?.map((t) => <option key={t.technician_id} value={t.technician_id}>{t.full_name} — {t.specialization}</option>)}
          </Select>
        </Field>
        <Field label="Priority"><Select aria-label="Priority" {...register("priority")}>{["Low", "Medium", "High", "Critical"].map((p) => <option key={p}>{p}</option>)}</Select></Field>
        <Field label="Failure severity"><Select aria-label="Failure severity" {...register("failure_severity")}>{["Minor", "Moderate", "Major", "Critical"].map((p) => <option key={p}>{p}</option>)}</Select></Field>
        <div className="col-span-2 max-md:col-span-1">
          <Field label="Complaint" required error={errors.complaint_description?.message}>
            <Textarea aria-label="Complaint" rows={3} {...register("complaint_description")} placeholder="What does the customer report?" />
          </Field>
        </div>
        {coverage && (
          <div className={`col-span-2 flex items-start gap-2 rounded-md px-3 py-2 text-xs max-md:col-span-1 ${coverage.covered ? "bg-ok-soft text-ok" : "bg-canvas text-ink-2"}`}>
            {coverage.covered ? <ShieldCheck className="mt-px size-4 shrink-0" /> : <ShieldX className="mt-px size-4 shrink-0 text-ink-3" />}
            <div><p className="font-medium">{coverage.covered ? "Covered by warranty" : "Not covered by warranty"}</p><p>{coverage.reasons.join(" ")}</p></div>
          </div>
        )}
        {serverError && <p role="alert" className="col-span-2 rounded-md bg-bad-soft px-3 py-2 text-xs text-bad max-md:col-span-1">{serverError}</p>}
      </form>
    </Modal>
  );
}
