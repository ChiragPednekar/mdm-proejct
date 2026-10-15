import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { Info } from "lucide-react";
import { useApi } from "../lib/hooks";
import { money, number, pct } from "../lib/format";
import type { Metric } from "../lib/types";
import { Async, Card, PageHeader, StatTile } from "../components/ui/primitives";
import { CHART, ChartCard } from "../components/ui/Chart";
import { DataTable } from "../components/ui/DataTable";

interface Summary {
  metrics: Metric[];
  top_components: { component_name: string; repair_count: number; repeat_repairs: number; total_repair_cost: number }[];
  top_models: { manufacturer: string; model_name: string; product_category: string; repairs: number; registered_units: number; repairs_per_100_units: number }[];
  low_stock: { part_id: number; part_number: string; part_name: string; stock_quantity: number; reorder_level: number; shortfall: number }[];
}
interface Trends {
  monthly_activity: { month: string; service_requests: number; completed_repairs: number }[];
  warranty_expenditure: { month: string; warranty_cost: number; customer_cost: number }[];
  failures_by_category: { category: string; failures: number }[];
  top_defects: { fault_category: string; component: string; occurrences: number }[];
  failures_by_component: { component: string; failures: number }[];
  risk_distribution: { risk_level: string; products: number }[];
}

const monthLabel = (m: string) => {
  const [y, mo] = m.split("-");
  return new Date(Number(y), Number(mo) - 1).toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
};
const kfmt = (v: number) => (v >= 100000 ? `${(v / 100000).toFixed(1)}L` : v >= 1000 ? `${Math.round(v / 1000)}k` : String(v));

function MetricTile({ m }: { m: Metric }) {
  let value: string = number(m.value);
  let sub: string | undefined;
  if (m.key === "warranty_expenditure") { value = money(m.value); sub = `${money(m.last_12_months as number)} in last 12 months`; }
  if (m.key === "repeat_failure_rate") { value = pct(m.value); sub = `${m.numerator} of ${m.denominator} failures (365 d)`; }
  if (m.key === "active_warranties") sub = `${m.products} products covered`;
  if (m.key === "expired_warranties") sub = `${m.products_without_cover} products without cover`;
  if (m.key === "high_risk_products") sub = `${m.medium} medium risk`;
  const tone = m.key === "low_stock_parts" && (m.value ?? 0) > 0 ? "warn" : m.key === "high_risk_products" && (m.value ?? 0) > 0 ? "bad" : undefined;
  return (
    <StatTile label={m.label} value={value} sub={sub} tone={tone} title={`Definition: ${m.definition}`} />
  );
}

export default function Dashboard() {
  const summary = useApi<Summary>("/dashboard/summary");
  const trends = useApi<Trends>("/dashboard/trends?months=12");
  const nav = useNavigate();

  return (
    <>
      <PageHeader title="Executive dashboard"
        description="Live figures computed from the database on every load. Hover a tile for its exact definition." />
      <Async state={summary}>
        {(s) => (
          <div className="mb-4 grid grid-cols-5 gap-3 max-xl:grid-cols-3 max-md:grid-cols-2">
            {s.metrics.map((m) => <MetricTile key={m.key} m={m} />)}
          </div>
        )}
      </Async>

      <Async state={trends}>
        {(t) => (
          <div className="mb-4 grid grid-cols-2 gap-4 max-lg:grid-cols-1">
            <ChartCard title="Service requests vs completed repairs" subtitle="Last 12 months">
              <LineChart data={t.monthly_activity} margin={{ left: -10, right: 12 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="month" tickFormatter={monthLabel} tick={CHART.axis} tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} tick={CHART.axis} tickLine={false} axisLine={false} />
                <Tooltip labelFormatter={(l) => monthLabel(String(l))} />
                <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                <Line isAnimationActive={false} dataKey="service_requests" name="Service requests" stroke={CHART.navy} strokeWidth={2} dot={false} />
                <Line isAnimationActive={false} dataKey="completed_repairs" name="Completed repairs" stroke={CHART.accent} strokeWidth={2} dot={false} />
              </LineChart>
            </ChartCard>
            <ChartCard title="Repair expenditure" subtitle="Warranty-borne vs customer-paid, per month">
              <BarChart data={t.warranty_expenditure} margin={{ left: -4, right: 12 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="month" tickFormatter={monthLabel} tick={CHART.axis} tickLine={false} axisLine={false} />
                <YAxis tickFormatter={kfmt} tick={CHART.axis} tickLine={false} axisLine={false} />
                <Tooltip formatter={(v) => money(Number(v))} labelFormatter={(l) => monthLabel(String(l))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar isAnimationActive={false} dataKey="warranty_cost" name="Warranty" stackId="c" fill={CHART.accent} />
                <Bar isAnimationActive={false} dataKey="customer_cost" name="Customer" stackId="c" fill={CHART.muted} />
              </BarChart>
            </ChartCard>
            <ChartCard title="Failures by product category" subtitle="All failure-category service requests" empty={!t.failures_by_category.length}>
              <BarChart data={t.failures_by_category} layout="vertical" margin={{ left: 30, right: 16 }}>
                <CartesianGrid stroke={CHART.grid} horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={CHART.axis} tickLine={false} axisLine={false} />
                <YAxis type="category" dataKey="category" tick={CHART.axis} tickLine={false} axisLine={false} width={100} />
                <Tooltip />
                <Bar isAnimationActive={false} dataKey="failures" name="Failures" fill={CHART.navy} barSize={16} />
              </BarChart>
            </ChartCard>
            <ChartCard title="Failure distribution by component" subtitle="Repair attempts touching each component" height={260} empty={!t.failures_by_component.length}>
              <BarChart data={t.failures_by_component} margin={{ left: 16, right: 12, bottom: 44 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="component" tick={{ ...CHART.axis, fontSize: 10 }} interval={0} angle={-35} textAnchor="end" tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} tick={CHART.axis} tickLine={false} axisLine={false} />
                <Tooltip />
                <Bar isAnimationActive={false} dataKey="failures" name="Repairs" fill={CHART.accent} barSize={18} />
              </BarChart>
            </ChartCard>
            <Card title="Top recurring defects" subtitle="Fault category × component, first repair attempts" bodyClass="p-0">
              <DataTable dense rows={t.top_defects} rowKey={(r) => r.fault_category + r.component}
                columns={[
                  { key: "f", header: "Fault", render: (r) => r.fault_category },
                  { key: "c", header: "Component", render: (r) => r.component },
                  { key: "n", header: "Occurrences", align: "right", render: (r) => r.occurrences },
                ]} />
            </Card>
            <ChartCard title="Risk distribution" subtitle="Current prediction per product (configurable bands)"
              empty={!t.risk_distribution.some((r) => r.products > 0)}>
              <BarChart data={t.risk_distribution} margin={{ left: -10, right: 12 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="risk_level" tick={CHART.axis} tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} tick={CHART.axis} tickLine={false} axisLine={false} />
                <Tooltip />
                <Bar isAnimationActive={false} dataKey="products" name="Products" barSize={44}>
                  {t.risk_distribution.map((r) => (
                    <Cell key={r.risk_level} fill={r.risk_level === "High" ? CHART.bad : r.risk_level === "Medium" ? CHART.warn : CHART.accent2} />
                  ))}
                </Bar>
              </BarChart>
            </ChartCard>
          </div>
        )}
      </Async>

      <Async state={summary}>
        {(s) => (
          <div className="grid grid-cols-3 gap-4 max-xl:grid-cols-1">
            <Card title="Components with most failures" bodyClass="p-0">
              <DataTable dense rows={s.top_components} rowKey={(r) => r.component_name} columns={[
                { key: "c", header: "Component", render: (r) => r.component_name },
                { key: "n", header: "Repairs", align: "right", render: (r) => r.repair_count },
                { key: "r", header: "Repeat", align: "right", render: (r) => r.repeat_repairs },
                { key: "$", header: "Cost", align: "right", render: (r) => money(r.total_repair_cost) },
              ]} />
            </Card>
            <Card title="Models with highest repair frequency" bodyClass="p-0">
              <DataTable dense rows={s.top_models} rowKey={(r) => r.manufacturer + r.model_name} columns={[
                { key: "m", header: "Model", render: (r) => <span>{r.manufacturer} <span className="text-ink-3">{r.model_name}</span></span> },
                { key: "n", header: "Repairs", align: "right", render: (r) => r.repairs },
                { key: "u", header: "Per 100 units", align: "right", render: (r) => r.repairs_per_100_units },
              ]} />
            </Card>
            <Card title="Spare parts below reorder level" bodyClass="p-0"
              actions={<button className="text-xs font-medium text-accent hover:underline" onClick={() => nav("/inventory?low=1")}>View inventory</button>}>
              <DataTable dense rows={s.low_stock} rowKey={(r) => r.part_id} emptyTitle="All parts above reorder level" columns={[
                { key: "p", header: "Part", render: (r) => <span className="font-mono text-xs">{r.part_number}</span> },
                { key: "n", header: "Name", render: (r) => <span className="text-ink-2">{r.part_name}</span> },
                { key: "s", header: "Stock / reorder", align: "right", render: (r) => <span className={r.stock_quantity === 0 ? "text-bad font-medium" : "text-warn"}>{r.stock_quantity} / {r.reorder_level}</span> },
              ]} />
            </Card>
          </div>
        )}
      </Async>
      <p className="mt-4 flex items-center gap-1.5 text-[11px] text-ink-4"><Info className="size-3" /> Repeat-failure rate, warranty expenditure and risk metrics use the definitions shown on hover; risk bands are set in Settings.</p>
    </>
  );
}
