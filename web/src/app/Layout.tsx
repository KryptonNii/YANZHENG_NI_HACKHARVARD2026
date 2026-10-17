import { NavLink, Outlet, useLocation } from "react-router-dom";
import { MOCK_API, useHealth } from "./health";
import { IdentitySwitcher } from "./IdentitySwitcher";
import { getLastDesignId } from "./lastDesign";
import { Badge, Dot } from "./ui";

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden>
      <rect width="32" height="32" rx="7" fill="#0f766e" />
      <path d="M8 21l6-6 4 4 7-8" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="25" cy="11" r="2.2" fill="#fff" />
    </svg>
  );
}

function StatusBadges() {
  const health = useHealth();
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="status-badges">
      <Badge tone="neutral" title="Every number is an estimate with a P10–P90 range and a provenance trail">
        Prototype — estimates with ranges
      </Badge>
      {MOCK_API && (
        <Badge tone="dark" title="VITE_MOCK_API=1: the browser answers API calls with fictional mock data. Not real estimates.">
          <Dot className="bg-caution-400" /> Mock API — fictional data
        </Badge>
      )}
      {health.kind === "ok" && health.offline && (
        <Badge tone="caution" title="DEMO_OFFLINE=1: external calls are served from cached fixtures">
          <Dot className="bg-caution-500" /> Offline mode — cached data
        </Badge>
      )}
      {health.kind === "unreachable" && (
        <Badge tone="worse" title="GET /api/health failed">
          <Dot className="bg-worse-500" /> API unreachable
        </Badge>
      )}
    </div>
  );
}

const navCls = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-2.5 py-1.5 text-sm font-semibold transition-colors ${
    isActive ? "bg-accent-50 text-accent-800" : "text-ink-600 hover:bg-ink-100 hover:text-ink-900"
  }`;

export function Layout() {
  useLocation(); // re-render on navigation so the "last design" links stay current
  const last = getLastDesignId();
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-ink-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-6 py-2.5">
          <NavLink to="/" className="flex items-center gap-2.5" aria-label="TrialPilot home">
            <Logo />
            <span className="text-lg font-bold tracking-tight text-ink-900">TrialPilot</span>
          </NavLink>
          <nav aria-label="Main" className="flex flex-1 flex-wrap items-center gap-0.5">
            <span className="mr-1 hidden text-[11px] font-bold uppercase tracking-wider text-ink-400 xl:inline">Plan</span>
            <NavLink to="/" end className={navCls}>
              Import
            </NavLink>
            {last && (
              <NavLink to={`/scenario/${encodeURIComponent(last)}`} className={navCls}>
                Simulator
              </NavLink>
            )}
            <NavLink to="/compare" className={navCls}>
              Compare
            </NavLink>
            <span className="ml-3 mr-1 hidden text-[11px] font-bold uppercase tracking-wider text-ink-400 xl:inline">Run</span>
            <NavLink to={`/command/${encodeURIComponent(last ?? "demo")}`} className={navCls}>
              Command center
            </NavLink>
            <span className="ml-3 mr-1 hidden text-[11px] font-bold uppercase tracking-wider text-ink-400 xl:inline">Prove</span>
            <NavLink to="/approvals" className={navCls}>
              Approvals
            </NavLink>
            <NavLink to="/audit" className={navCls}>
              Audit
            </NavLink>
            <NavLink to="/validation" className={navCls}>
              Validation
            </NavLink>
            <NavLink to="/science" className={navCls}>
              Science
            </NavLink>
            <NavLink to="/about" className={navCls}>
              About
            </NavLink>
          </nav>
          <IdentitySwitcher />
        </div>
        <div className="border-t border-ink-100 bg-ink-50/80">
          <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-6 py-1.5">
            <StatusBadges />
            <span className="hidden text-xs text-ink-500 lg:inline">Open source · MIT · every number shows its sources</span>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-6">
        <Outlet />
      </main>
      <footer className="border-t border-ink-200 bg-white">
        <div className="mx-auto max-w-[1600px] px-6 py-3 text-xs text-ink-500">
          TrialPilot is a prototype. Figures are estimates with P10–P90 ranges; each links to its formula, parameters and sources.
          Simulated data is labelled as simulated.
        </div>
      </footer>
    </div>
  );
}
