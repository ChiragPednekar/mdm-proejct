import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button, cx, EmptyState, ErrorState, Spinner } from "./primitives";
import type { ApiError } from "../../lib/api";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  className?: string;
  align?: "left" | "right";
}

export function DataTable<T>({
  columns, rows, rowKey, onRowClick, loading, error, onRetry, emptyTitle, emptyHint, dense,
}: {
  columns: Column<T>[]; rows: T[] | undefined; rowKey: (r: T) => string | number; onRowClick?: (r: T) => void;
  loading?: boolean; error?: ApiError | null; onRetry?: () => void; emptyTitle?: string; emptyHint?: ReactNode; dense?: boolean;
}) {
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (!rows) return <Spinner />;
  if (rows.length === 0) return <EmptyState title={emptyTitle ?? "No matching records"} hint={emptyHint} />;
  return (
    <div className={cx("relative overflow-x-auto", loading && "opacity-60")}>
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-line bg-canvas/60">
            {columns.map((c) => (
              <th key={c.key} className={cx("px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3 whitespace-nowrap",
                c.align === "right" && "text-right", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={rowKey(r)}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              className={cx("border-b border-line last:border-0", onRowClick && "cursor-pointer hover:bg-accent-soft/40")}
            >
              {columns.map((c) => (
                <td key={c.key} className={cx("px-3 align-middle", !c.className?.includes("whitespace-") && "whitespace-nowrap", dense ? "py-1.5" : "py-2", c.align === "right" && "text-right tabular", c.className)}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-ink-3">
      <span className="tabular">{from}–{to} of {total.toLocaleString("en-IN")}</span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)} icon={<ChevronLeft className="size-3.5" />} />
        <span className="tabular px-1">Page {page} / {pages}</span>
        <Button size="sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)} icon={<ChevronRight className="size-3.5" />} />
      </div>
    </div>
  );
}
