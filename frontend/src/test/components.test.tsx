import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { ApiError } from "../lib/api";

const cols = [{ key: "n", header: "Name", render: (r: { id: number; name: string }) => r.name }];

describe("DataTable", () => {
  it("shows a loading indicator before data arrives", () => {
    render(<DataTable columns={cols} rows={undefined} rowKey={(r) => r.id} />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });
  it("shows an empty state", () => {
    render(<DataTable columns={cols} rows={[]} rowKey={(r) => r.id} emptyTitle="Nothing found" />);
    expect(screen.getByText("Nothing found")).toBeInTheDocument();
  });
  it("shows an error with retry", async () => {
    const retry = vi.fn();
    render(<DataTable columns={cols} rows={undefined} rowKey={(r) => r.id} error={new ApiError(500, "x", "Server exploded")} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Server exploded");
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(retry).toHaveBeenCalled();
  });
  it("renders rows and handles clicks", async () => {
    const click = vi.fn();
    render(<DataTable columns={cols} rows={[{ id: 1, name: "Alpha" }, { id: 2, name: "Beta" }]} rowKey={(r) => r.id} onRowClick={click} />);
    await userEvent.click(screen.getByText("Beta"));
    expect(click).toHaveBeenCalledWith({ id: 2, name: "Beta" });
  });
});

describe("Pagination", () => {
  it("disables navigation at the bounds", async () => {
    const onPage = vi.fn();
    render(<Pagination page={1} pageSize={25} total={60} onPage={onPage} />);
    expect(screen.getByText("1–25 of 60")).toBeInTheDocument();
    expect(screen.getByLabelText("Previous page")).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Next page"));
    expect(onPage).toHaveBeenCalledWith(2);
  });
});
