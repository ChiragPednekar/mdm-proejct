import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { useApi } from "../lib/hooks";
import { useList } from "../lib/useList";
import { date, money, prob } from "../lib/format";
import type { ProductRow } from "../lib/types";
import { Button, Card, PageHeader, StatusBadge } from "../components/ui/primitives";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { FilterBar, FilterSelect, SearchInput } from "../components/ui/Form";
import { ProductForm } from "../components/ProductForm";

export default function Products() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const list = useList<ProductRow>("/products", { sort: "newest", customer_id: sp.get("customer_id") ?? undefined });
  const categories = useApi<string[]>("/catalog/categories");
  const makers = useApi<string[]>("/catalog/manufacturers");
  const [open, setOpen] = useState(false);
  const f = list.filters;
  return (
    <>
      <PageHeader title="Product registry" description="Registered units, their owners, warranty coverage and latest failure-risk estimate."
        actions={<Button variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setOpen(true)}>Register product</Button>} />
      <Card bodyClass="p-0">
        <FilterBar>
          <SearchInput className="w-64" placeholder="Serial number or customer" value={String(f.q ?? "")} onChange={(v) => list.set("q", v)} />
          {f.customer_id && <Button size="sm" variant="ghost" onClick={() => list.set("customer_id", undefined)}>Customer #{String(f.customer_id)} ✕</Button>}
          <FilterSelect label="Category" value={String(f.category ?? "")} onChange={(v) => list.set("category", v)} options={categories.data ?? []} />
          <FilterSelect label="Manufacturer" value={String(f.manufacturer ?? "")} onChange={(v) => list.set("manufacturer", v)} options={makers.data ?? []} />
          <FilterSelect label="Status" value={String(f.status ?? "")} onChange={(v) => list.set("status", v)} options={["Active", "Under Repair", "Replaced", "Retired"]} />
          <FilterSelect label="Coverage" value={String(f.coverage ?? "")} onChange={(v) => list.set("coverage", v)} options={["Active", "Expired", "Pending", "None"]} />
          <FilterSelect label="Risk" value={String(f.risk ?? "")} onChange={(v) => list.set("risk", v)} options={["High", "Medium", "Low"]} />
          <FilterSelect label="Sort" allLabel="Newest" value={String(f.sort === "newest" ? "" : f.sort)} onChange={(v) => list.set("sort", v || "newest")}
            options={[{ value: "oldest", label: "Oldest" }, { value: "serial", label: "Serial" }, { value: "risk", label: "Highest risk" }]} />
        </FilterBar>
        <DataTable rows={list.data?.items} loading={list.loading} error={list.error} onRetry={list.reload}
          rowKey={(r) => r.product_id} onRowClick={(r) => nav(`/products/${r.product_id}`)}
          columns={[
            { key: "serial", header: "Serial", render: (r) => <span className="font-mono text-xs font-medium">{r.serial_number}</span> },
            { key: "model", header: "Model", render: (r) => <span>{r.manufacturer} <span className="text-ink-3">{r.model_name}</span></span> },
            { key: "cat", header: "Category", render: (r) => r.product_category },
            { key: "cust", header: "Customer", render: (r) => r.customer_name },
            { key: "date", header: "Purchased", render: (r) => date(r.purchase_date) },
            { key: "price", header: "Price", align: "right", render: (r) => money(r.purchase_price) },
            { key: "status", header: "Status", render: (r) => <StatusBadge value={r.product_status} /> },
            { key: "cov", header: "Warranty", render: (r) => <StatusBadge value={r.coverage_status} /> },
            { key: "risk", header: "Risk", render: (r) => r.risk_level
              ? <span className="inline-flex items-center gap-1.5"><StatusBadge value={r.risk_level} /><span className="tabular text-xs text-ink-3">{prob(r.failure_probability)}</span></span>
              : <span className="text-xs text-ink-4">Not scored</span> },
          ]} />
        {list.data && <Pagination page={list.page} pageSize={list.pageSize} total={list.data.total} onPage={list.setPage} />}
      </Card>
      <ProductForm open={open} onClose={() => setOpen(false)} onCreated={(id) => { setOpen(false); nav(`/products/${id}`); }} />
    </>
  );
}
