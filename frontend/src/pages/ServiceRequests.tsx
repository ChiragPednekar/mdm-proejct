import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { useApi } from "../lib/hooks";
import { useList } from "../lib/useList";
import { useAuth } from "../lib/auth";
import { dateTime } from "../lib/format";
import type { ServiceRequestRow, Technician } from "../lib/types";
import { Badge, Button, Card, PageHeader, StatusBadge, cx } from "../components/ui/primitives";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { FilterBar, FilterSelect, Input, SearchInput } from "../components/ui/Form";
import { ServiceRequestForm } from "../components/ServiceRequestForm";

const STATUS_GROUPS: Record<string, string[] | undefined> = {
  Pipeline: ["Open", "Assigned", "In Progress"], All: undefined, Open: ["Open"], Assigned: ["Assigned"],
  "In Progress": ["In Progress"], Resolved: ["Resolved"], Closed: ["Closed"], Cancelled: ["Cancelled"],
};

export default function ServiceRequests() {
  const nav = useNavigate();
  const { user } = useAuth();
  const [group, setGroup] = useState("Pipeline");
  const list = useList<ServiceRequestRow>("/service-requests", { status: STATUS_GROUPS.Pipeline, sort: "-reported_at" });
  const techs = useApi<Technician[]>("/technicians");
  const [open, setOpen] = useState(false);
  const f = list.filters;
  const pick = (g: string) => { setGroup(g); list.set("status", STATUS_GROUPS[g]); };
  return (
    <>
      <PageHeader title="Service requests" description="Complaint intake, warranty check, assignment, repair and resolution."
        actions={<Button variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setOpen(true)}>New service request</Button>} />
      <div className="mb-3 flex flex-wrap gap-1">
        {Object.keys(STATUS_GROUPS).map((g) => (
          <button key={g} onClick={() => pick(g)} className={cx("h-7 rounded-md px-2.5 text-xs font-medium",
            group === g ? "bg-ink text-white" : "bg-surface text-ink-2 ring-1 ring-line hover:bg-canvas")}>{g}</button>
        ))}
        {user?.role === "technician" && user.technician_id && (
          <button onClick={() => list.set("technician_id", f.technician_id ? undefined : user.technician_id!)}
            className={cx("ml-2 h-7 rounded-md px-2.5 text-xs font-medium", f.technician_id ? "bg-accent text-white" : "bg-surface ring-1 ring-line")}>My assignments</button>
        )}
      </div>
      <Card bodyClass="p-0">
        <FilterBar>
          <SearchInput className="w-64" placeholder="Serial, customer or complaint" value={String(f.q ?? "")} onChange={(v) => list.set("q", v)} />
          <FilterSelect label="Priority" value={String(f.priority ?? "")} onChange={(v) => list.set("priority", v)} options={["Critical", "High", "Medium", "Low"]} />
          <FilterSelect label="Severity" value={String(f.severity ?? "")} onChange={(v) => list.set("severity", v)} options={["Critical", "Major", "Moderate", "Minor"]} />
          <FilterSelect label="Category" value={String(f.category ?? "")} onChange={(v) => list.set("category", v)} options={["Laptop", "Refrigerator", "Washing Machine", "Air Conditioner", "Television"]} />
          <FilterSelect label="Technician" value={String(f.technician_id ?? "")} onChange={(v) => list.set("technician_id", v)}
            options={(techs.data ?? []).map((t) => ({ value: String(t.technician_id), label: t.full_name }))} />
          <FilterSelect label="Warranty" value={String(f.warranty_covered ?? "")} onChange={(v) => list.set("warranty_covered", v)}
            options={[{ value: "true", label: "Covered" }, { value: "false", label: "Not covered" }]} />
          <Input aria-label="Reported from" type="date" className="w-36" value={String(f.reported_from ?? "")} onChange={(e) => list.set("reported_from", e.target.value)} />
          <Input aria-label="Reported to" type="date" className="w-36" value={String(f.reported_to ?? "")} onChange={(e) => list.set("reported_to", e.target.value)} />
          <FilterSelect label="Sort" allLabel="Newest" value={f.sort === "-reported_at" ? "" : String(f.sort)} onChange={(v) => list.set("sort", v || "-reported_at")}
            options={[{ value: "reported_at", label: "Oldest" }, { value: "-priority", label: "Priority" }, { value: "status", label: "Status" }]} />
        </FilterBar>
        <DataTable rows={list.data?.items} loading={list.loading} error={list.error} onRetry={list.reload} rowKey={(r) => r.service_request_id}
          onRowClick={(r) => nav(`/service-requests/${r.service_request_id}`)} emptyTitle="No service requests match these filters"
          columns={[
            { key: "id", header: "SR", render: (r) => <span className="font-medium">#{r.service_request_id}</span> },
            { key: "d", header: "Reported", render: (r) => <span className="text-xs">{dateTime(r.reported_at)}</span> },
            { key: "s", header: "Serial", render: (r) => <span className="font-mono text-xs">{r.serial_number}</span> },
            { key: "c", header: "Customer", render: (r) => r.customer_name },
            { key: "f", header: "Fault", render: (r) => <span title={r.complaint_description}>{r.fault_category}</span> },
            { key: "p", header: "Priority", render: (r) => <StatusBadge value={r.priority} /> },
            { key: "t", header: "Technician", render: (r) => r.technician_name ?? <span className="text-ink-4">Unassigned</span> },
            { key: "w", header: "Warranty", render: (r) => r.warranty_covered ? <Badge tone="ok">Covered</Badge> : <Badge>No</Badge> },
            { key: "st", header: "Status", render: (r) => <StatusBadge value={r.request_status} /> },
          ]} />
        {list.data && <Pagination page={list.page} pageSize={list.pageSize} total={list.data.total} onPage={list.setPage} />}
      </Card>
      <ServiceRequestForm open={open} onClose={() => setOpen(false)} onCreated={(id) => { setOpen(false); nav(`/service-requests/${id}`); }} />
    </>
  );
}
