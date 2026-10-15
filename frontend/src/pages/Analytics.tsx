import { useEffect, useState } from "react";
import { Copy, Download, Play } from "lucide-react";
import { api, qs } from "../lib/api";
import { useApi } from "../lib/hooks";
import { Async, Badge, Button, Card, EmptyState, ErrorState, PageHeader, Spinner, cx } from "../components/ui/primitives";
import { Field, Input, Select } from "../components/ui/Form";
import { useToast } from "../components/ui/Toast";
import type { ApiError } from "../lib/api";

interface Param { name: string; type: "int" | "date" | "choice" | "str"; default: string | number; label: string; choices: string[] | null; minimum: number | null; maximum: number | null }
interface Report { name: string; title: string; description: string; concepts: string[]; sql: string; params: Param[] }
interface Result { name: string; sql: string; params: Record<string, string>; columns: string[]; rows: Record<string, unknown>[]; row_count: number }

function toCsv(r: Result): string {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [r.columns.join(","), ...r.rows.map((row) => r.columns.map((c) => esc(row[c])).join(","))].join("\n");
}

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-IN") : v.toLocaleString("en-IN", { maximumFractionDigits: 4 });
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return new Date(v).toLocaleString("en-GB");
  return String(v);
}

function ReportRunner({ report }: { report: Report }) {
  const toast = useToast();
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async (vals: Record<string, string>) => {
    setLoading(true); setError(null);
    try { setResult(await api<Result>(`/analytics/${report.name}${qs(vals)}`)); }
    catch (e) { setError(e as ApiError); setResult(null); } finally { setLoading(false); }
  };
  useEffect(() => {
    const init = Object.fromEntries(report.params.map((p) => [p.name, String(p.default)]));
    setValues(init); setResult(null); run(init);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report.name]);

  const download = () => {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([toCsv(result)], { type: "text/csv" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${report.name}.csv` });
    a.click(); URL.revokeObjectURL(url);
  };

  return (
    <div className="min-w-0 space-y-4">
      <Card title={report.title} subtitle={report.description}>
        <div className="mb-3 flex flex-wrap gap-1">{report.concepts.map((c) => <Badge key={c} tone="info">{c}</Badge>)}</div>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); run(values); }}>
          {report.params.map((p) => (
            <Field key={p.name} label={p.label}>
              {p.type === "choice" ? (
                <Select aria-label={p.label} value={values[p.name] ?? ""} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} className="w-44">
                  {p.choices?.map((c) => <option key={c}>{c}</option>)}
                </Select>
              ) : (
                <Input aria-label={p.label} className="w-40" type={p.type === "int" ? "number" : p.type === "date" ? "date" : "text"}
                  min={p.minimum ?? undefined} max={p.maximum ?? undefined} value={values[p.name] ?? ""}
                  onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} />
              )}
            </Field>
          ))}
          <Button type="submit" variant="primary" icon={<Play className="size-3.5" />} loading={loading}>Run query</Button>
          {result && <Button type="button" icon={<Download className="size-3.5" />} onClick={download}>Export CSV</Button>}
        </form>
      </Card>
      <Card title="Parameterized SQL" subtitle="Executed with bound parameters (:name) — user input never reaches the SQL text."
        actions={<Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />} onClick={() => { navigator.clipboard?.writeText(report.sql); toast.success("SQL copied"); }}>Copy</Button>}>
        <pre className="overflow-x-auto rounded-md bg-ink px-4 py-3 font-mono text-[12px] leading-relaxed text-[#d7e3ea]">{report.sql}</pre>
      </Card>
      <Card title="Result" subtitle={result ? `${result.row_count} row(s)` : undefined} bodyClass="p-0">
        {error ? <ErrorState error={error} onRetry={() => run(values)} /> : !result ? <Spinner /> : result.rows.length === 0 ? <EmptyState title="Query returned no rows" /> : (
          <div className={cx("max-h-[520px] overflow-auto", loading && "opacity-60")}>
            <table className="w-full text-left text-[12px]">
              <thead className="sticky top-0 bg-canvas"><tr>{result.columns.map((c) => <th key={c} className="border-b border-line px-3 py-2 font-mono text-[11px] font-medium text-ink-3">{c}</th>)}</tr></thead>
              <tbody>{result.rows.map((r, i) => (
                <tr key={i} className="border-b border-line last:border-0">{result.columns.map((c) => (
                  <td key={c} className={cx("px-3 py-1.5 whitespace-nowrap", typeof r[c] === "number" && "text-right tabular")}>{fmtCell(r[c])}</td>))}</tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export default function Analytics() {
  const catalog = useApi<Report[]>("/analytics/reports");
  const [selected, setSelected] = useState<string>("");
  return (
    <>
      <PageHeader title="Analytics & SQL reports" description="DBMS demonstration: each report is a real parameterized query or view over the operational database." />
      <Async state={catalog}>
        {(reports) => {
          const current = reports.find((r) => r.name === selected) ?? reports[0];
          return (
            <div className="grid grid-cols-[260px_minmax(0,1fr)] gap-4 max-lg:grid-cols-1">
              <nav className="h-fit rounded-lg border border-line bg-surface p-1.5" aria-label="Reports">
                {reports.map((r, i) => (
                  <button key={r.name} onClick={() => setSelected(r.name)}
                    className={cx("flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left", current.name === r.name ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-canvas")}>
                    <span className="mt-px w-5 shrink-0 text-[11px] tabular text-ink-4">{String(i + 1).padStart(2, "0")}</span>
                    <span className="text-[13px] font-medium leading-snug">{r.title}</span>
                  </button>
                ))}
                <p className="px-2.5 pb-1 pt-2 text-[11px] text-ink-4">Backed by 10 SQL views (e.g. <span className="font-mono">v_repair_costs</span>). Full catalogue: dbms_documentation/SQL_QUERIES.md</p>
              </nav>
              <ReportRunner report={current} />
            </div>
          );
        }}
      </Async>
    </>
  );
}
