import { useMemo, useState } from "react";
import { qs, type Query } from "./api";
import { useApi, useDebounced } from "./hooks";
import type { Page } from "./types";

/** Server-side paginated list with filters; resets to page 1 when filters change. */
export function useList<T>(path: string, initial: Query = {}, pageSize = 25) {
  const [filters, setFilters] = useState<Query>(initial);
  const [page, setPage] = useState(1);
  const debounced = useDebounced(filters, 250);
  const url = useMemo(() => `${path}${qs({ ...debounced, page, page_size: pageSize })}`, [path, debounced, page, pageSize]);
  const state = useApi<Page<T>>(url);
  const set = (k: string, v: Query[string]) => { setFilters((f) => ({ ...f, [k]: v })); setPage(1); };
  return { ...state, filters, set, page, setPage, pageSize };
}
