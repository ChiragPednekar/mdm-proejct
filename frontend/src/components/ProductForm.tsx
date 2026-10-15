import { useMemo, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Wand2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApi } from "../lib/hooks";
import type { Customer, ProductModel } from "../lib/types";
import { Modal } from "./ui/Modal";
import { Button } from "./ui/primitives";
import { Checkbox, Field, Input, Select } from "./ui/Form";
import { useToast } from "./ui/Toast";
import { CustomerPicker } from "./CustomerPicker";

const today = () => new Date().toISOString().slice(0, 10);
const schema = z.object({
  category: z.string().min(1, "Choose a category"),
  manufacturer: z.string().min(1, "Choose a manufacturer"),
  product_model_id: z.coerce.number({ invalid_type_error: "Choose a model" }).int().positive("Choose a model"),
  serial_number: z.string().trim().regex(/^[A-Za-z0-9-]{4,40}$/, "4–40 letters, digits or dashes").or(z.literal("")),
  customer: z.custom<Customer>((v) => !!v, "Select the owning customer"),
  purchase_date: z.string().min(1, "Purchase date is required").refine((d) => d <= today(), "Cannot be in the future"),
  purchase_price: z.coerce.number({ invalid_type_error: "Enter a price" }).min(0, "Must be ≥ 0"),
  installation_date: z.string().optional(),
  register_manufacturer_warranty: z.boolean(),
}).refine((v) => !v.installation_date || v.installation_date >= v.purchase_date, {
  path: ["installation_date"], message: "Cannot be before the purchase date",
});
type Values = z.infer<typeof schema>;

export function ProductForm({ open, onClose, onCreated, presetCustomer }: {
  open: boolean; onClose: () => void; onCreated: (productId: number) => void; presetCustomer?: Customer | null;
}) {
  const toast = useToast();
  const models = useApi<ProductModel[]>(open ? "/catalog/product-models" : null);
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, watch, setValue, control, reset, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { category: "", manufacturer: "", serial_number: "", purchase_date: today(), installation_date: "",
      register_manufacturer_warranty: true, customer: presetCustomer ?? undefined },
  });
  const category = watch("category");
  const manufacturer = watch("manufacturer");
  const modelId = watch("product_model_id");
  const all = models.data ?? [];
  const categories = useMemo(() => [...new Set(all.map((m) => m.product_category))].sort(), [all]);
  const makers = useMemo(() => [...new Set(all.filter((m) => m.product_category === category).map((m) => m.manufacturer))].sort(), [all, category]);
  const choices = all.filter((m) => m.product_category === category && m.manufacturer === manufacturer);
  const selected = all.find((m) => m.product_model_id === Number(modelId));

  const generate = async () => {
    if (!modelId) return setError("product_model_id", { message: "Choose a model first" });
    try {
      const r = await api<{ serial_number: string }>(`/products/serial-suggestion?product_model_id=${modelId}`);
      setValue("serial_number", r.serial_number, { shouldValidate: true });
    } catch (e) { toast.error(e); }
  };

  const onSubmit = async (v: Values) => {
    setServerError(null);
    try {
      const res = await api<{ product: { product_id: number; serial_number: string } }>("/products", {
        method: "POST",
        json: {
          product_model_id: v.product_model_id, customer_id: v.customer.customer_id, serial_number: v.serial_number || null,
          purchase_date: v.purchase_date, purchase_price: v.purchase_price.toFixed(2),
          installation_date: v.installation_date || null, register_manufacturer_warranty: v.register_manufacturer_warranty,
        },
      });
      toast.success(`Registered ${res.product.serial_number}`);
      reset();
      onCreated(res.product.product_id);
    } catch (e) {
      if (e instanceof ApiError && e.code === "integrity_error") setError("serial_number", { message: e.message });
      else setServerError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Register product" width="lg"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={isSubmitting} onClick={handleSubmit(onSubmit)}>Register product</Button></>}>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
        <Field label="Owner (customer)" required error={errors.customer?.message as string | undefined}>
          <Controller control={control} name="customer" render={({ field }) => (
            <CustomerPicker value={field.value ?? null} onChange={field.onChange} invalid={!!errors.customer} />
          )} />
        </Field>
        <Field label="Category" required error={errors.category?.message}>
          <Select aria-label="Category" {...register("category", { onChange: () => { setValue("manufacturer", ""); setValue("product_model_id", NaN); } })}>
            <option value="">Select…</option>
            {categories.map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Field>
        <Field label="Manufacturer" required error={errors.manufacturer?.message}>
          <Select aria-label="Manufacturer" disabled={!category} {...register("manufacturer", { onChange: () => setValue("product_model_id", NaN) })}>
            <option value="">Select…</option>
            {makers.map((m) => <option key={m}>{m}</option>)}
          </Select>
        </Field>
        <Field label="Model" required error={errors.product_model_id?.message}
          hint={selected ? `${selected.standard_warranty_months}-month standard warranty · released ${selected.release_year}` : undefined}>
          <Select aria-label="Model" disabled={!manufacturer} {...register("product_model_id")}>
            <option value="">Select…</option>
            {choices.map((m) => <option key={m.product_model_id} value={m.product_model_id}>{m.model_name}</option>)}
          </Select>
        </Field>
        <Field label="Serial number" error={errors.serial_number?.message} hint="Leave blank to auto-generate a unique serial.">
          <div className="flex gap-2">
            <Input aria-label="Serial number" className="font-mono uppercase" {...register("serial_number")} aria-invalid={!!errors.serial_number} />
            <Button type="button" icon={<Wand2 className="size-3.5" />} onClick={generate}>Generate</Button>
          </div>
        </Field>
        <Field label="Purchase price (₹)" required error={errors.purchase_price?.message}>
          <Input aria-label="Purchase price" type="number" step="0.01" min="0" {...register("purchase_price")} aria-invalid={!!errors.purchase_price} />
        </Field>
        <Field label="Purchase date" required error={errors.purchase_date?.message}>
          <Input aria-label="Purchase date" type="date" max={today()} {...register("purchase_date")} />
        </Field>
        <Field label="Installation date" error={errors.installation_date?.message} hint="For installed appliances (optional).">
          <Input aria-label="Installation date" type="date" {...register("installation_date")} />
        </Field>
        <div className="col-span-2 max-md:col-span-1">
          <Checkbox label="Register the standard manufacturer warranty from the purchase date" {...register("register_manufacturer_warranty")} />
        </div>
        {serverError && <p role="alert" className="col-span-2 rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{serverError}</p>}
      </form>
    </Modal>
  );
}
