import { useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./ui/Modal";
import { Button } from "./ui/primitives";
import { Checkbox, Field, Input, Select, Textarea } from "./ui/Form";
import { useToast } from "./ui/Toast";

export function ExtendWarrantyModal({ warrantyId, onClose, onDone }: { warrantyId: number | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [months, setMonths] = useState(12);
  const [type, setType] = useState<"Extended" | "Accidental Damage Protection">("Extended");
  const [terms, setTerms] = useState({ covers_parts: true, covers_labor: true, covers_wear_and_tear: false, covers_accidental_damage: false });
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const valid = months >= 1 && months <= 60;

  const submit = async () => {
    if (!valid || warrantyId === null) return;
    setBusy(true); setErr(null);
    try {
      const w = await api<{ warranty_id: number; start_date: string; end_date: string }>(`/warranties/${warrantyId}/extend`, {
        method: "POST", json: { months, warranty_type: type, ...terms, coverage_details: details || null },
      });
      toast.success(`Warranty #${w.warranty_id} created: ${w.start_date} → ${w.end_date}`);
      onDone();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };

  return (
    <Modal open={warrantyId !== null} onClose={onClose} title={`Extend warranty #${warrantyId ?? ""}`}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!valid} onClick={submit}>Create extension</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Length (months)" required error={valid ? undefined : "Between 1 and 60 months"}>
          <Input aria-label="Length in months" type="number" min={1} max={60} value={months} onChange={(e) => setMonths(Number(e.target.value))} />
        </Field>
        <Field label="Type">
          <Select aria-label="Extension type" value={type} onChange={(e) => setType(e.target.value as typeof type)}>
            <option>Extended</option><option>Accidental Damage Protection</option>
          </Select>
        </Field>
        <div className="col-span-2 grid grid-cols-2 gap-2">
          {(Object.keys(terms) as (keyof typeof terms)[]).map((k) => (
            <Checkbox key={k} label={k.replace("covers_", "Covers ").replace(/_/g, " ")} checked={terms[k]} onChange={(e) => setTerms({ ...terms, [k]: e.target.checked })} />
          ))}
        </div>
        <div className="col-span-2"><Field label="Coverage details"><Textarea aria-label="Coverage details" value={details} onChange={(e) => setDetails(e.target.value)} /></Field></div>
        <p className="col-span-2 text-[11px] text-ink-3">The extension starts the day after the product's latest coverage ends. Lapsed coverage cannot be extended.</p>
        {err && <p role="alert" className="col-span-2 rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{err}</p>}
      </div>
    </Modal>
  );
}
