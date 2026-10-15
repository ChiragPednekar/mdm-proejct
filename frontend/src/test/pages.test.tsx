import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ADMIN, mockApi, page, renderPage } from "./utils";
import Login from "../pages/Login";
import Customers from "../pages/Customers";
import ServiceRequestDetail from "../pages/ServiceRequestDetail";
import Dashboard from "../pages/Dashboard";
import App from "../App";

const customers = [
  { customer_id: 1, full_name: "Nadia Rao", email: "nadia@example.com", phone: "+91 9000000001", address: null, city: "Pune", created_at: "2025-01-01T00:00:00Z", product_count: 2, service_request_count: 3 },
  { customer_id: 2, full_name: "Omar Shah", email: null, phone: "+91 9000000002", address: null, city: "Mumbai", created_at: "2025-02-01T00:00:00Z", product_count: 1, service_request_count: 0 },
];

describe("Login", () => {
  it("validates required fields", async () => {
    mockApi([]);
    renderPage(<Login />, { loggedIn: false });
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Username is required")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
  });

  it("shows the server error for bad credentials", async () => {
    mockApi([["POST", /^\/auth\/login$/, () => ({ status: 401, body: { error: { code: "unauthorized", message: "Invalid username or password." } } })]]);
    renderPage(<Login />, { loggedIn: false });
    await userEvent.type(screen.getByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password.");
  });

  it("logs in and shows the app shell", async () => {
    mockApi([
      ["POST", /^\/auth\/login$/, () => ({ body: { access_token: "tok", user: ADMIN } })],
      ["GET", /^\/dashboard\/summary$/, () => ({ body: { metrics: [], top_components: [], top_models: [], low_stock: [] } })],
      ["GET", /^\/dashboard\/trends$/, () => ({ body: { monthly_activity: [], warranty_expenditure: [], failures_by_category: [], top_defects: [], failures_by_component: [], risk_distribution: [] } })],
    ]);
    const { render } = await import("@testing-library/react");
    render(<App />);
    await userEvent.type(screen.getByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "secret");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Executive dashboard")).toBeInTheDocument();
    expect(localStorage.getItem("swi.token")).toBe("tok");
  });
});

describe("Dashboard", () => {
  it("renders metrics returned by the API (no hard-coded values)", async () => {
    mockApi([
      ["GET", /^\/dashboard\/summary$/, () => ({ body: {
        metrics: [{ key: "open_service_requests", label: "Open service requests", value: 42, definition: "Open, Assigned or In Progress." },
                  { key: "repeat_failure_rate", label: "Repeat-failure rate", value: 0.25, numerator: 5, denominator: 20, definition: "d" }],
        top_components: [], top_models: [], low_stock: [] } })],
      ["GET", /^\/dashboard\/trends$/, () => ({ status: 500, body: { error: { code: "internal_error", message: "Trends failed" } } })],
    ]);
    renderPage(<Dashboard />);
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    expect(screen.getByText("5 of 20 failures (365 d)")).toBeInTheDocument();
    expect(screen.getByTitle(/Definition: Open, Assigned/)).toBeInTheDocument();
    expect(await screen.findByText("Trends failed")).toBeInTheDocument(); // error state, rest of page still works
  });
});

describe("Customers", () => {
  it("loads rows and filters through the API", async () => {
    const { calls } = mockApi([
      ["GET", /^\/customers\/cities$/, () => ({ body: ["Mumbai", "Pune"] })],
      ["GET", /^\/customers$/, (url) => {
        const q = url.searchParams.get("q") ?? "";
        const rows = customers.filter((c) => c.full_name.toLowerCase().includes(q.toLowerCase()));
        return { body: page(rows) };
      }],
    ]);
    renderPage(<Customers />);
    expect(await screen.findByText("Nadia Rao")).toBeInTheDocument();
    expect(screen.getByText("Omar Shah")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name, email or phone"), "omar");
    await waitFor(() => expect(screen.queryByText("Nadia Rao")).not.toBeInTheDocument());
    expect(screen.getByText("Omar Shah")).toBeInTheDocument();
    expect(calls.some((c) => c.url.searchParams.get("q") === "omar")).toBe(true);
  });

  it("shows an empty state", async () => {
    mockApi([["GET", /^\/customers\/cities$/, () => ({ body: [] })], ["GET", /^\/customers$/, () => ({ body: page([]) })]]);
    renderPage(<Customers />);
    expect(await screen.findByText("No matching records")).toBeInTheDocument();
  });

  it("validates the customer form before submitting", async () => {
    const { calls } = mockApi([["GET", /^\/customers\/cities$/, () => ({ body: [] })], ["GET", /^\/customers$/, () => ({ body: page([]) })]]);
    renderPage(<Customers />);
    await userEvent.click(await screen.findByRole("button", { name: /register customer/i }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Full name/), "A");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Name must have at least 2 characters")).toBeInTheDocument();
    expect(within(dialog).getByText("Provide a phone number or an email address")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });
});

const detail = (over: Record<string, unknown> = {}) => ({
  service_request_id: 7, request_status: "In Progress", complaint_description: "No power", priority: "High", failure_severity: "Major",
  reported_at: "2026-10-01T05:00:00Z", resolution_date: null, resolution_summary: null,
  fault_category: { fault_category_id: 1, name: "Electrical Failure", description: null, is_customer_induced: false, is_wear_and_tear: false, counts_as_failure: true },
  technician: { technician_id: 3, full_name: "Tina Tech", specialization: "Laptops" },
  product: { product_id: 9, serial_number: "TST-1", model_name: "T-1", manufacturer: "Testco", product_category: "Laptop", product_status: "Under Repair", customer_name: "Nadia Rao", customer_phone: null },
  warranty: { warranty_id: 4, warranty_type: "Manufacturer", start_date: "2026-01-01", end_date: "2026-12-31", covers_parts: true, covers_labor: true, effective_status: "Active" },
  warranty_covered: true, coverage_notes: "Covered by Manufacturer warranty #4 (parts and labor).", repairs: [],
  costs: { labor: 0, parts: 0, total: 0, warranty: 0, customer: 0 },
  allowed_transitions: ["Cancelled"], can_record_repair: true, can_complete: true, ...over,
});

function repairMocks(onRepair: (body: Record<string, unknown>) => { status?: number; body?: unknown }) {
  return mockApi([
    ["GET", /^\/service-requests\/7$/, () => ({ body: detail() })],
    ["GET", /^\/technicians$/, () => ({ body: [{ technician_id: 3, full_name: "Tina Tech", email: "t@x", specialization: "Laptops", employment_status: "Active" }] })],
    ["GET", /^\/catalog\/components$/, () => ({ body: [{ component_id: 5, component_name: "Battery Pack", component_category: "Power", manufacturer: null }] })],
    ["GET", /^\/inventory\/parts$/, () => ({ body: page([{ part_id: 11, component_id: 5, part_number: "PN-BAT-1", part_name: "Battery", unit_cost: "2500.00", selling_price: null, stock_quantity: 2, reorder_level: 1, supplier_name: null, updated_at: "", component_name: "Battery Pack", low_stock: false }]) })],
    ["POST", /^\/service-requests\/7\/repairs$/, (_u, init) => onRepair(JSON.parse(String(init.body)))],
  ]);
}

describe("Service request repair workflow", () => {
  it("validates the repair form, including stock limits", async () => {
    const { calls } = repairMocks(() => ({ status: 201 }));
    renderPage(<ServiceRequestDetail />, { route: "/service-requests/7", path: "/service-requests/:id" });
    await userEvent.click(await screen.findByRole("button", { name: /record repair/i }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /add part/i }));
    await waitFor(() => expect(within(dialog).getByLabelText("Part 1").querySelectorAll("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(within(dialog).getByLabelText("Part 1"), "11");
    await userEvent.clear(within(dialog).getByLabelText("Quantity 1"));
    await userEvent.type(within(dialog).getByLabelText("Quantity 1"), "3");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save repair" }));
    expect(within(dialog).getByText("Diagnosis is required")).toBeInTheDocument();
    expect(within(dialog).getByText("Only 2 in stock")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("submits a repair with parts, cost preview and an idempotency key; shows API errors", async () => {
    let attempts = 0;
    const { calls } = repairMocks(() => {
      attempts += 1;
      return attempts === 1
        ? { status: 409, body: { error: { code: "insufficient_stock", message: "Insufficient stock for one or more parts; nothing was deducted." } } }
        : { status: 201, body: { repair_id: 1 } };
    });
    renderPage(<ServiceRequestDetail />, { route: "/service-requests/7", path: "/service-requests/:id" });
    await userEvent.click(await screen.findByRole("button", { name: /record repair/i }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Diagnosis"), "Dead cell");
    await userEvent.type(within(dialog).getByLabelText("Repair action"), "Replaced battery");
    await userEvent.clear(within(dialog).getByLabelText("Labor cost"));
    await userEvent.type(within(dialog).getByLabelText("Labor cost"), "500");
    await userEvent.click(within(dialog).getByRole("button", { name: /add part/i }));
    await waitFor(() => expect(within(dialog).getByLabelText("Part 1").querySelectorAll("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(within(dialog).getByLabelText("Part 1"), "11");
    expect(within(dialog).getByText(/Total/).textContent).toContain("3,000");

    await userEvent.click(within(dialog).getByRole("button", { name: "Save repair" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Insufficient stock");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save repair" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(2);
    const body = posts[1].body as Record<string, unknown>;
    expect(body).toMatchObject({ technician_id: 3, diagnosis: "Dead cell", labor_cost: "500.00", outcome: "Fixed", parts: [{ part_id: 11, quantity: 1 }] });
    expect(typeof body.idempotency_key).toBe("string");
    // The retry reuses the same key, so the server can never deduct stock twice.
    expect((posts[0].body as Record<string, unknown>).idempotency_key).toBe(body.idempotency_key);
  });
});
