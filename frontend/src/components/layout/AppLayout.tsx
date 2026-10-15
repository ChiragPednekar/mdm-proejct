import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity, BarChart3, Boxes, BrainCircuit, ClipboardList, Gauge, LogOut, Package, Settings, ShieldCheck, Users, Wrench,
  FlaskConical,
} from "lucide-react";
import { useAuth } from "../../lib/auth";
import { cx } from "../ui/primitives";

const NAV = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/products", label: "Products", icon: Package },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/warranties", label: "Warranties", icon: ShieldCheck },
  { to: "/service-requests", label: "Service Requests", icon: ClipboardList },
  { to: "/repairs", label: "Repair History", icon: Wrench },
  { to: "/inventory", label: "Inventory", icon: Boxes },
  { to: "/predictions", label: "Failure Predictions", icon: Activity },
  { to: "/analytics", label: "Analytics & Reports", icon: BarChart3 },
  { to: "/models", label: "Model Performance", icon: BrainCircuit },
  { to: "/settings", label: "Settings", icon: Settings },
];

const ROLE_LABEL = { admin: "Administrator", service_manager: "Service manager", technician: "Technician" } as const;

export function AppLayout() {
  const { user, logout } = useAuth();
  const loc = useLocation();
  const current = NAV.find((n) => (n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to)));
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-line bg-surface max-md:w-14">
        <div className="flex h-12 items-center gap-2 border-b border-line px-4 max-md:px-3">
          <span className="grid size-7 place-items-center rounded-md bg-ink text-[#5eead4]"><FlaskConical className="size-4" /></span>
          <div className="leading-tight max-md:hidden">
            <p className="text-[13px] font-semibold">Warranty Intelligence</p>
            <p className="text-[10px] uppercase tracking-wider text-ink-4">Service centre</p>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} title={label}
              className={({ isActive }) => cx(
                "mb-0.5 flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium",
                isActive ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-canvas hover:text-ink",
              )}>
              <Icon className="size-4 shrink-0" />
              <span className="truncate max-md:hidden">{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center justify-between border-b border-line bg-surface/95 px-6 backdrop-blur max-md:px-4">
          <p className="text-xs text-ink-3">
            <span className="text-ink-4">Service Centre /</span> <span className="font-medium text-ink-2">{current?.label ?? "Details"}</span>
          </p>
          <div className="flex items-center gap-3">
            <div className="text-right leading-tight">
              <p className="text-[13px] font-medium">{user?.full_name}</p>
              <p className="text-[11px] text-ink-3">{user ? ROLE_LABEL[user.role] : ""}</p>
            </div>
            <button onClick={logout} title="Sign out" aria-label="Sign out" className="rounded-md p-1.5 text-ink-3 hover:bg-canvas hover:text-ink">
              <LogOut className="size-4" />
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-5 max-md:px-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
