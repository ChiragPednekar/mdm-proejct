import { useState } from "react";
import { qs } from "../lib/api";
import { useApi, useDebounced } from "../lib/hooks";
import type { Customer, Page } from "../lib/types";
import { Input } from "./ui/Form";

/** Type-ahead customer selector backed by GET /customers?q=. */
export function CustomerPicker({ value, onChange, invalid }: { value: Customer | null; onChange: (c: Customer | null) => void; invalid?: boolean }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const dq = useDebounced(q, 200);
  const res = useApi<Page<Customer>>(open ? `/customers${qs({ q: dq, page_size: 8 })}` : null);
  if (value) {
    return (
      <div className="flex h-8 items-center justify-between rounded-md border border-line-strong bg-canvas px-2.5">
        <span className="truncate">{value.full_name} <span className="text-ink-3">· {value.phone ?? value.email}</span></span>
        <button type="button" className="text-xs font-medium text-accent" onClick={() => onChange(null)}>Change</button>
      </div>
    );
  }
  return (
    <div className="relative">
      <Input aria-label="Search customer" placeholder="Search customer by name, email or phone" value={q} aria-invalid={invalid}
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} onChange={(e) => setQ(e.target.value)} />
      {open && (
        <ul role="listbox" className="absolute z-10 mt-1 max-h-60 w-full overflow-y-auto rounded-md border border-line bg-surface shadow-md">
          {res.loading && <li className="px-3 py-2 text-xs text-ink-3">Searching…</li>}
          {res.data?.items.length === 0 && <li className="px-3 py-2 text-xs text-ink-3">No customers found — add one on the Customers page.</li>}
          {res.data?.items.map((c) => (
            <li key={c.customer_id} role="option" aria-selected={false} onMouseDown={() => onChange(c)}
              className="cursor-pointer px-3 py-1.5 hover:bg-accent-soft">
              <p>{c.full_name}</p>
              <p className="text-[11px] text-ink-3">{[c.phone, c.email, c.city].filter(Boolean).join(" · ")}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
