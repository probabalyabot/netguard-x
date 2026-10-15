import clsx from "clsx";
import { BarChart3, Columns2, FlaskConical, LayoutDashboard, ListChecks, Network, RefreshCw } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useApp } from "../state/AppState";
import { Chip, Notice, VerdictBadge } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/explorer", label: "Network explorer", icon: Network },
  { to: "/analyze", label: "Change analysis", icon: FlaskConical },
  { to: "/compare", label: "Before and after", icon: Columns2 },
  { to: "/findings", label: "Findings", icon: ListChecks },
  { to: "/evaluation", label: "Research evaluation", icon: BarChart3 },
];

function Sidebar() {
  const { report } = useApp();
  return (
    <nav aria-label="Main" className="flex w-14 shrink-0 flex-col border-r border-line bg-panel lg:w-56">
      <div className="flex h-12 items-center gap-2.5 border-b border-line px-3.5">
        <svg viewBox="0 0 32 32" className="size-6 shrink-0" aria-hidden>
          <path d="M8 22 16 8l8 14z" fill="none" stroke="rgb(var(--net))" strokeWidth="2" strokeLinejoin="round" />
          <circle cx="16" cy="8" r="2.6" fill="rgb(var(--net))" /><circle cx="8" cy="22" r="2.6" fill="rgb(var(--net))" /><circle cx="24" cy="22" r="2.6" fill="rgb(var(--net))" />
        </svg>
        <span className="hidden text-[15px] font-semibold tracking-tight lg:block">NetGuard-X</span>
      </div>
      <ul className="flex-1 space-y-0.5 p-2">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink to={to} end={end} title={label}
              className={({ isActive }) => clsx("flex items-center gap-2.5 rounded px-2.5 py-2 text-sm transition-colors",
                isActive ? "bg-raised text-fg shadow-[inset_2px_0_0_rgb(var(--net))]" : "text-muted hover:bg-raised/60 hover:text-fg")}>
              <Icon size={17} strokeWidth={1.75} aria-hidden className="shrink-0" />
              <span className="hidden lg:block">{label}</span>
              {to === "/findings" && report && report.findings.length > 0 && (
                <span className="ml-auto hidden rounded bg-bad/15 px-1.5 text-xs text-bad lg:block">{report.findings.length}</span>
              )}
              <span className="sr-only">{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      <p className="hidden border-t border-line p-3 text-xs text-faint lg:block">Static routing and ACLs. Every result comes from the simulator; nothing touches a device.</p>
    </nav>
  );
}

function TopBar() {
  const { health, recheckHealth, networkLabel, report, stale } = useApp();
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-panel px-4">
      <div className="flex min-w-0 items-center gap-2">
        <span className="text-xs text-muted">Network</span>
        <span className="truncate text-sm font-medium">{networkLabel || "none loaded"}</span>
      </div>
      <Chip tone="net" className="hidden sm:inline-flex" >Simulator</Chip>
      <span className="hidden text-xs text-muted md:inline">Changes run against an in-memory model. Nothing is deployed.</span>
      <div className="ml-auto flex items-center gap-3">
        {report && (
          <span className="hidden items-center gap-2 sm:flex" title={report.verdict.headline}>
            <VerdictBadge decision={report.verdict.decision} />
            {stale && <span className="text-xs text-warn">out of date</span>}
          </span>
        )}
        {health.state === "online" && <span className="flex items-center gap-1.5 text-xs text-muted"><span className="size-1.5 rounded-full bg-safe" />API v{health.version}</span>}
        {health.state === "checking" && <span className="text-xs text-muted">Connecting…</span>}
        {health.state === "offline" && (
          <button className="btn !py-1 !text-xs" onClick={recheckHealth}><span className="size-1.5 rounded-full bg-bad" />API offline<RefreshCw size={12} aria-hidden /></button>
        )}
      </div>
    </header>
  );
}

export function Layout() {
  const { health, examplesError } = useApp();
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1500px] p-4 sm:p-6">
            {health.state === "offline" && (
              <div className="mb-4">
                <Notice tone="bad" title="The NetGuard-X API is not reachable">
                  {health.message} In development the frontend proxies <code>/api</code> to <code>http://127.0.0.1:8000</code>; see frontend/README.md.
                </Notice>
              </div>
            )}
            {examplesError && health.state !== "offline" && <div className="mb-4"><Notice tone="warn" title="Could not load the example networks">{examplesError}</Notice></div>}
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
