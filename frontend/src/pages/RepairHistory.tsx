import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis } from "recharts";
import { qs } from "../lib/api";
import { useApi, useDebounced } from "../lib/hooks";
import { date, money, pct } from "../lib/format";
import type { Component, Page, ProductModel } from "../lib/types";
import { Async, Badge, Card, PageHeader, StatTile, StatusBadge, Tabs } from "../components/ui/primitives";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { Checkbox, FilterBar, FilterSelect, Input } from "../components/ui/Form";
import { CHART, ChartCard } from "../components/ui/Chart";

interface RepairRow {
  repair_id: number; service_request_id: number; attempt_number: number; repair_date: string; diagnosis: string; outcome: string;
  repeat_failure: boolean; total_cost: number; serial_number: string; manufacturer: string; model_name: string; product_category: string;
  component_name: string | null; technician_name: string; fault_category: string; failure_severity: string; warranty_covered: boolean;
}
interface Defects {
  definitions: Record<string, string>;
  summary: { failure_requests: number; first_time_fix_rate: number | null; first_time_fix_numerator: number; first_time_fix_denominator: number; mean_time_to_repair_days: number | null };
  frequently_replaced_components: { component_name: string; repairs: number; parts_used: number; parts_spend: number }[];
  repeat_products: { product_id: number; serial_number: string; model_name: string; failures: number; first_failure: string; last_failure: string }[];
  recurring_faults: { fault: string; recurrences: number; occurrences: number }[];
  high_cost_models: { manufacturer: string; model_name: string; product_category: string; repairs: number; avg_cost: number; cost_ratio: number }[];
  repeat_components: { component_name: string; repairs: number; repeat_repairs: number; repeat_pct: number }[];
  mttr_by_category: { category: string; avg_days: number; resolved_requests: number }[];
  claims_by_category: { category: string; period: string; covered_claims: number; not_covered: number }[];
}

type F = Record<string, string | boolean>;

function DefectAnalytics({ filters }: { filters: F }) {
  const nav = useNavigate();
  const [windowDays, setWindowDays] = useState("90");
  const { repeat_only: _r, outcome: _o, ...shared } = filters;
  void _r; void _o;
  const state = useApi<Defects>(`/analytics/defects${qs({ ...(shared as Record<string, string>), window_days: windowDays })}`);
  const claims = useMemo(() => {
    const by: Record<string, Record<string, number | string>> = {};
    for (const c of state.data?.claims_by_category ?? []) {
      by[c.period] ??= { period: c.period, covered: 0, rejected: 0 };
      (by[c.period].covered as number) += c.covered_claims;
      (by[c.period].rejected as number) += c.not_covered;
    }
    return Object.values(by);
  }, [state.data]);
  return (
    <Async state={state}>
      {(d) => (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3 max-lg:grid-cols-2">
            <StatTile label="Failure requests (filtered)" value={d.summary.failure_requests} />
            <StatTile label="First-time fix rate" value={pct(d.summary.first_time_fix_rate)} title={d.definitions.first_time_fix_rate}
              sub={`${d.summary.first_time_fix_numerator} of ${d.summary.first_time_fix_denominator} resolved requests`} />
            <StatTile label="Mean time to repair" value={d.summary.mean_time_to_repair_days === null ? "—" : `${d.summary.mean_time_to_repair_days} days`} title={d.definitions.mean_time_to_repair} sub="Reported → resolved" />
            <div className="rounded-lg border border-line bg-surface px-4 py-3">
              <label htmlFor="win" className="text-xs font-medium text-ink-3">Recurrence window (days)</label>
              <Input id="win" type="number" min={1} max={365} value={windowDays} onChange={(e) => setWindowDays(e.target.value)} className="mt-1" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
            <Card title="Frequently replaced components" bodyClass="p-0">
              <DataTable dense rows={d.frequently_replaced_components} rowKey={(r) => r.component_name} columns={[
                { key: "c", header: "Component", render: (r) => r.component_name },
                { key: "r", header: "Repairs", align: "right", render: (r) => r.repairs },
                { key: "p", header: "Parts used", align: "right", render: (r) => r.parts_used },
                { key: "$", header: "Parts spend", align: "right", render: (r) => money(r.parts_spend) },
              ]} />
            </Card>
            <Card title="Components associated with repeat repairs" subtitle="Share of repairs flagged as repeat failures (min. 3 repairs)" bodyClass="p-0">
              <DataTable dense rows={d.repeat_components} rowKey={(r) => r.component_name} columns={[
                { key: "c", header: "Component", render: (r) => r.component_name },
                { key: "r", header: "Repairs", align: "right", render: (r) => r.repairs },
                { key: "x", header: "Repeat", align: "right", render: (r) => r.repeat_repairs },
                { key: "p", header: "Repeat %", align: "right", render: (r) => `${r.repeat_pct}%` },
              ]} />
            </Card>
            <Card title={`Faults recurring within ${windowDays} days`} subtitle={d.definitions.recurring_fault} bodyClass="p-0">
              <DataTable dense rows={d.recurring_faults} rowKey={(r) => r.fault} columns={[
                { key: "f", header: "Fault category", render: (r) => r.fault },
                { key: "o", header: "Occurrences", align: "right", render: (r) => r.occurrences },
                { key: "r", header: "Recurrences", align: "right", render: (r) => r.recurrences },
              ]} />
            </Card>
            <Card title="Models with unusually high repair cost" subtitle={d.definitions.high_cost_model} bodyClass="p-0">
              <DataTable dense rows={d.high_cost_models} rowKey={(r) => r.manufacturer + r.model_name} emptyTitle="No outlier models for these filters" columns={[
                { key: "m", header: "Model", render: (r) => `${r.manufacturer} ${r.model_name}` },
                { key: "n", header: "Repairs", align: "right", render: (r) => r.repairs },
                { key: "a", header: "Avg cost", align: "right", render: (r) => money(r.avg_cost) },
                { key: "x", header: "× fleet avg", align: "right", render: (r) => <span className="font-medium text-warn">{r.cost_ratio}×</span> },
              ]} />
            </Card>
            <Card title="Products with repeated failures" bodyClass="p-0">
              <DataTable dense rows={d.repeat_products} rowKey={(r) => r.product_id} onRowClick={(r) => nav(`/products/${r.product_id}`)} columns={[
                { key: "s", header: "Serial", render: (r) => <span className="font-mono text-xs">{r.serial_number}</span> },
                { key: "m", header: "Model", render: (r) => r.model_name },
                { key: "f", header: "Failures", align: "right", render: (r) => r.failures },
                { key: "l", header: "Latest", render: (r) => date(r.last_failure) },
              ]} />
            </Card>
            <Card title="Average time to repair by category" bodyClass="p-0">
              <DataTable dense rows={d.mttr_by_category} rowKey={(r) => r.category} columns={[
                { key: "c", header: "Category", render: (r) => r.category },
                { key: "n", header: "Resolved", align: "right", render: (r) => r.resolved_requests },
                { key: "d", header: "Avg days", align: "right", render: (r) => r.avg_days },
              ]} />
            </Card>
          </div>
          <ChartCard title="Warranty claims by period" subtitle="Failure requests per quarter, by recorded coverage decision" empty={!claims.length}>
            <BarChart data={claims} margin={{ left: -10, right: 12 }}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="period" tick={CHART.axis} tickLine={false} axisLine={false} />
              <YAxis allowDecimals={false} tick={CHART.axis} tickLine={false} axisLine={false} />
              <Tooltip /><Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar isAnimationActive={false} dataKey="covered" name="Covered" stackId="a" fill={CHART.accent} />
              <Bar isAnimationActive={false} dataKey="rejected" name="Not covered" stackId="a" fill={CHART.muted} />
            </BarChart>
          </ChartCard>
        </div>
      )}
    </Async>
  );
}

export default function RepairHistory() {
  const nav = useNavigate();
  const [tab, setTab] = useState<"records" | "analytics">("records");
  const [filters, setFilters] = useState<F>({});
  const [page, setPage] = useState(1);
  const debounced = useDebounced(filters, 250);
  const models = useApi<ProductModel[]>("/catalog/product-models");
  const comps = useApi<Component[]>("/catalog/components");
  const makers = useApi<string[]>("/catalog/manufacturers");
  const list = useApi<Page<RepairRow>>(tab === "records" ? `/repairs${qs({ ...(debounced as Record<string, string>), page, page_size: 25 })}` : null);
  const set = (k: string, v: string | boolean) => { setFilters((f) => ({ ...f, [k]: v })); setPage(1); };
  const s = (k: string) => String(filters[k] ?? "");
  return (
    <>
      <PageHeader title="Repair history & defect analytics" description="Every repair attempt with its costs, and the defect patterns behind them." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "records", label: "Repair records" }, { id: "analytics", label: "Defect analytics" }]} />
      <Card bodyClass="p-0" className="mb-4">
        <FilterBar>
          <Input aria-label="From date" type="date" className="w-36" value={s("start_date")} onChange={(e) => set("start_date", e.target.value)} />
          <Input aria-label="To date" type="date" className="w-36" value={s("end_date")} onChange={(e) => set("end_date", e.target.value)} />
          <FilterSelect label="Category" value={s("category")} onChange={(v) => set("category", v)} options={["Laptop", "Refrigerator", "Washing Machine", "Air Conditioner", "Television"]} />
          <FilterSelect label="Manufacturer" value={s("manufacturer")} onChange={(v) => set("manufacturer", v)} options={makers.data ?? []} />
          <FilterSelect label="Model" value={s("product_model_id")} onChange={(v) => set("product_model_id", v)}
            options={(models.data ?? []).filter((m) => (!filters.category || m.product_category === filters.category) && (!filters.manufacturer || m.manufacturer === filters.manufacturer))
              .map((m) => ({ value: String(m.product_model_id), label: `${m.manufacturer} ${m.model_name}` }))} />
          <FilterSelect label="Component" value={s("component_id")} onChange={(v) => set("component_id", v)}
            options={(comps.data ?? []).map((c) => ({ value: String(c.component_id), label: c.component_name }))} />
          <FilterSelect label="Severity" value={s("severity")} onChange={(v) => set("severity", v)} options={["Critical", "Major", "Moderate", "Minor"]} />
          {tab === "records" && <>
            <FilterSelect label="Outcome" value={s("outcome")} onChange={(v) => set("outcome", v)} options={["Fixed", "Partially Fixed", "Not Fixed", "Unit Replaced", "Referred"]} />
            <Checkbox label="Repeat failures only" checked={!!filters.repeat_only} onChange={(e) => set("repeat_only", e.target.checked ? "true" : "")} />
          </>}
        </FilterBar>
        {tab === "records" && <>
          <DataTable rows={list.data?.items} loading={list.loading} error={list.error} onRetry={list.reload} rowKey={(r) => r.repair_id}
            onRowClick={(r) => nav(`/service-requests/${r.service_request_id}`)}
            columns={[
              { key: "d", header: "Date", render: (r) => date(r.repair_date) },
              { key: "sr", header: "SR / attempt", render: (r) => <span className="text-xs">#{r.service_request_id} · {r.attempt_number}</span> },
              { key: "s", header: "Serial", render: (r) => <span className="font-mono text-xs">{r.serial_number}</span> },
              { key: "m", header: "Model", render: (r) => <span>{r.manufacturer} <span className="text-ink-3">{r.model_name}</span></span> },
              { key: "f", header: "Fault", render: (r) => r.fault_category },
              { key: "c", header: "Component", render: (r) => r.component_name ?? "—" },
              { key: "t", header: "Technician", render: (r) => r.technician_name },
              { key: "o", header: "Outcome", render: (r) => <span className="inline-flex gap-1"><StatusBadge value={r.outcome} />{r.repeat_failure && <Badge tone="warn">Repeat</Badge>}</span> },
              { key: "$", header: "Cost", align: "right", render: (r) => money(r.total_cost) },
            ]} />
          {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
        </>}
      </Card>
      {tab === "analytics" && <DefectAnalytics filters={debounced} />}
    </>
  );
}
