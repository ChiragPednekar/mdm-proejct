import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../lib/auth";
import { ToastProvider } from "../components/ui/Toast";
import { tokenStore } from "../lib/api";

export type Handler = (url: URL, init: RequestInit) => { status?: number; body?: unknown } | undefined;

export const ADMIN = { user_id: 1, username: "admin", email: "a@example.com", full_name: "Asha Admin", role: "admin", technician_id: null };

/** Replace fetch with a router over [method, path-regex, handler]. Records calls. */
export function mockApi(routes: [string, RegExp, Handler][]) {
  const calls: { method: string; url: URL; body: unknown }[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init = {}) => {
    const url = new URL(String(input));
    const method = (init.method ?? "GET").toUpperCase();
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    const path = url.pathname.replace("/api/v1", "");
    if (method === "GET" && path === "/auth/me") return json(200, ADMIN);
    for (const [m, re, h] of routes) {
      if (m === method && re.test(path)) {
        const r = h(url, init) ?? {};
        return json(r.status ?? 200, r.body ?? {});
      }
    }
    return json(404, { error: { code: "not_found", message: `No mock for ${method} ${path}` } });
  });
  return { calls, spy };
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function page<T>(items: T[], total = items.length) {
  return { items, total, page: 1, page_size: 25 };
}

export function renderPage(ui: ReactElement, { route = "/", path = "/", loggedIn = true } = {}) {
  if (loggedIn) tokenStore.set("test-token");
  return render(
    <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <ToastProvider>
          <Routes><Route path={path} element={ui} /><Route path="*" element={<div>navigated</div>} /></Routes>
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}
