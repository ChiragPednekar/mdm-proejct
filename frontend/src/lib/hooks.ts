import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** GET `path` (null = skip). Re-fetches whenever the path changes. */
export function useApi<T>(path: string | null): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);

  useEffect(() => {
    if (path === null) { setLoading(false); return; }
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    api<T>(path)
      .then((d) => { if (id === seq.current) setData(d); })
      .catch((e: unknown) => {
        if (id === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, "error", String(e)));
      })
      .finally(() => { if (id === seq.current) setLoading(false); });
  }, [path, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
