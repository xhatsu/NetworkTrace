import { createContext, useContext, useMemo, useState } from "react";
import {
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import {
  Activity,
  AlertOctagon,
  Boxes,
  ChevronDown,
  Clock,
  Compass,
  Database,
  GitBranch,
  GitCompareArrows,
  Globe2,
  LayoutDashboard,
  Radio,
  Search,
  SlidersHorizontal,
  Users,
  UserRoundSearch,
  Network,
  ChartNoAxesCombined,
  X,
} from "lucide-react";
import type { Filters } from "./types";
import { OverviewPage } from "./pages/Overview";
import { ServicesPage, ServiceDetailPage } from "./pages/Services";
import { PrincipalsPage, PrincipalDetailPage } from "./pages/Principals";
import { TopologyPage } from "./pages/Topology";
import { AnomaliesPage, AnomalyDetailPage } from "./pages/Anomalies";
import { TracesPage, TraceDetailPage } from "./pages/Traces";
import { UsersPage, UserDetailPage, UserChangesPage, UserGraphPage, UserAnalyticsPage } from "./pages/UserIntelligence";

const now = new Date();
const defaultEnd = new Date(now.getTime() + 60_000).toISOString();
const defaultStart = new Date(now.getTime() - 3 * 3600_000).toISOString();

const FilterContext = createContext<{
  filters: Filters;
  setFilter: (k: keyof Filters, v: string) => void;
}>({
  filters: {
    start: defaultStart,
    end: defaultEnd,
    timezone: "UTC",
    comparison: "previous",
  },
  setFilter: () => {},
});

export const useFilters = () => useContext(FilterContext);

function SideNav() {
  const groups = [
    { label: "", links: [[LayoutDashboard, "Overview", "/"]] },
    { label: "Observability", links: [[GitBranch, "Topology", "/topology"], [AlertOctagon, "Anomalies", "/anomalies"], [Boxes, "Services", "/services"], [Activity, "Traces", "/traces"]] },
    { label: "User Intelligence", links: [[UserRoundSearch, "Users", "/users"], [GitCompareArrows, "User Changes", "/user-changes"], [Network, "User Graph", "/user-graph"], [ChartNoAxesCombined, "User Analytics", "/user-analytics"]] },
  ] as const;

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[184px] flex-col border-r border-[rgba(255,255,255,0.06)] bg-[#090b0e] py-4 md:flex">
      {/* Brand mark */}
      <div className="mb-6 flex items-center gap-2 px-4">
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 text-white shadow-[0_0_20px_-3px_rgba(99,102,241,0.5)]">
          <Activity size={20} strokeWidth={2.5} />
        </div>
        <div><div className="text-xs font-semibold">TraceScope</div><div className="text-[9px] uppercase tracking-wider text-[#6e7681]">Intelligence</div></div>
      </div>

      {/* Nav items */}
      <nav className="flex w-full flex-1 flex-col gap-4 px-2">
        {groups.map((group) => <div key={group.label||"overview"}>
          {group.label && <div className="mb-1 px-2 text-[9px] font-semibold uppercase tracking-[.12em] text-[#59616b]">{group.label}</div>}
          <div className="space-y-1">{group.links.map(([Icon, label, to]) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            aria-label={label}
            className={({ isActive }) =>
              `group relative flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-[11px] font-medium transition duration-150 ${
                isActive
                  ? "bg-white/[0.08] text-white shadow-sm"
                  : "text-[#8b949e] hover:bg-white/[0.04] hover:text-[#c9d1d9]"
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-0 h-5 w-0.5 rounded-r-full bg-indigo-500 shadow-[0_0_8px_#6366f1]" />
                )}
                <Icon size={18} className={isActive ? "text-indigo-400" : "text-[#8b949e] group-hover:text-[#c9d1d9]"} />
                <span>{label}</span>
              </>
            )}
          </NavLink>
        ))}</div></div>)}
      </nav>

      {/* Database/Storage status */}
      <div className="flex items-center gap-2 px-4 text-[10px] text-[#6e7681]">
        <div
          title="SQLite Store · WAL mode"
          className="grid h-8 w-8 place-items-center rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] text-[#8b949e]"
        >
          <Database size={14} />
        </div>
        SQLite · WAL
      </div>
    </aside>
  );
}

function FilterBar() {
  const { filters, setFilter } = useFilters();
  const [showFilters, setShowFilters] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const nav = useNavigate();

  const handleGlobalSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;
    if (q.length >= 16 && !q.includes(" ")) {
      nav(`/traces/${encodeURIComponent(q)}`);
    } else {
      nav(`/services?q=${encodeURIComponent(q)}`);
    }
  };

  const rangeHours = Math.round(
    (new Date(filters.end).getTime() - new Date(filters.start).getTime()) / 3600_000,
  );

  function setRange(hours: number) {
    setFilter("end", new Date(Date.now() + 60_000).toISOString());
    setFilter("start", new Date(Date.now() - hours * 3600_000).toISOString());
  }

  const activeFilterKeys = (["environment", "group", "module", "service", "operation", "account"] as const).filter(
    (k) => !!filters[k],
  );

  return (
    <div className="border-b border-[rgba(255,255,255,0.06)] bg-[#090b0e]/95 px-4 py-2.5 backdrop-blur-md md:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Left: Branding, Status & Global Search */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight text-[#f0f3f6]">TraceScope</span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
              Live Estate
            </span>
          </div>

          {/* Quick Global Search */}
          <form onSubmit={handleGlobalSearch} className="relative hidden lg:block">
            <Search className="absolute left-2.5 top-2 text-[#8b949e]" size={12} />
            <input
              type="text"
              placeholder="Search services, trace ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-7 w-60 rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] pl-8 pr-3 text-xs text-[#f0f3f6] placeholder:text-[#6e7681] focus:border-indigo-500/60 focus:bg-white/[0.05] focus:outline-none"
            />
          </form>
        </div>

        {/* Center: Range preset segmented control */}
        <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.03] p-0.5">
          {[
            { label: "1h", hours: 1 },
            { label: "3h", hours: 3 },
            { label: "6h", hours: 6 },
            { label: "24h", hours: 24 },
          ].map(({ label, hours }) => (
            <button
              key={label}
              onClick={() => setRange(hours)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                rangeHours === hours
                  ? "bg-white/[0.12] text-white shadow-sm"
                  : "text-[#8b949e] hover:text-[#f0f3f6]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Right: Dimension filters & controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Quick filter toggle button */}
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`btn ${showFilters || activeFilterKeys.length > 0 ? "border-indigo-500/50 bg-indigo-500/10 text-indigo-300" : ""}`}
          >
            <SlidersHorizontal size={13} />
            <span>Filters</span>
            {activeFilterKeys.length > 0 && (
              <span className="grid h-4 w-4 place-items-center rounded-full bg-indigo-500 text-[9px] font-bold text-white">
                {activeFilterKeys.length}
              </span>
            )}
          </button>

          {/* Timezone */}
          <select
            aria-label="Timezone"
            value={filters.timezone}
            onChange={(e) => setFilter("timezone", e.target.value)}
            className="btn bg-[rgba(255,255,255,0.02)] cursor-pointer"
          >
            <option value="UTC" className="bg-[#12151a]">UTC</option>
            <option value="Asia/Ho_Chi_Minh" className="bg-[#12151a]">Asia/Ho Chi Minh</option>
            <option value="local" className="bg-[#12151a]">Browser Local</option>
          </select>

          {/* Baseline comparison */}
          <select
            aria-label="Comparison period"
            value={filters.comparison}
            onChange={(e) => setFilter("comparison", e.target.value)}
            className="btn bg-[rgba(255,255,255,0.02)] cursor-pointer"
          >
            <option value="previous" className="bg-[#12151a]">vs Prior Window</option>
            <option value="week" className="bg-[#12151a]">vs Prior Week</option>
            <option value="none" className="bg-[#12151a]">No Comparison</option>
          </select>

          {/* Auto refresh badge */}
          <div className="chip font-mono text-[10px] text-emerald-400 border-emerald-500/30">
            <Radio size={11} className="animate-pulse" />
            <span>60s rollup</span>
          </div>
        </div>
      </div>

      {/* Expanded filter panel */}
      {showFilters && (
        <div className="mt-3 grid grid-cols-2 gap-2 border-t border-[rgba(255,255,255,0.06)] pt-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["service", "Service"],
            ["operation", "Operation"],
            ["account", "Account"],
            ["environment", "Environment"],
            ["group", "Group"],
            ["module", "Module"],
          ].map(([key, label]) => (
            <div key={key} className="flex flex-col gap-1">
              <label className="text-[10px] font-medium uppercase tracking-wider text-[#8b949e]">
                {label}
              </label>
              <div className="relative">
                <input
                  aria-label={`${label} filter`}
                  placeholder={`All ${label.toLowerCase()}s`}
                  value={filters[key as keyof Filters] || ""}
                  onChange={(e) => setFilter(key as keyof Filters, e.target.value)}
                  className="w-full rounded-md border border-[rgba(255,255,255,0.08)] bg-white/[0.02] px-2.5 py-1 text-xs text-[#f0f3f6] placeholder:text-[#6e7681] focus:border-indigo-500/60 focus:bg-white/[0.05] focus:outline-none"
                />
                {filters[key as keyof Filters] && (
                  <button
                    onClick={() => setFilter(key as keyof Filters, "")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[#8b949e] hover:text-white"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Active filter badges */}
      {activeFilterKeys.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6e7681]">
            Active Filters:
          </span>
          {activeFilterKeys.map((k) => (
            <span
              key={k}
              className="inline-flex items-center gap-1 rounded-md border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-300"
            >
              <span className="text-[#8b949e]">{k}:</span>
              <span className="font-mono font-medium">{filters[k]}</span>
              <button
                onClick={() => setFilter(k, "")}
                className="ml-0.5 hover:text-white"
                title={`Remove ${k} filter`}
              >
                <X size={11} />
              </button>
            </span>
          ))}
          <button
            onClick={() => activeFilterKeys.forEach((k) => setFilter(k, ""))}
            className="text-[11px] text-[#8b949e] hover:text-white underline ml-1"
          >
            Clear all
          </button>
        </div>
      )}
    </div>
  );
}

function Layout() {
  const location = useLocation();
  return (
    <div className="min-h-screen bg-[#08090a] text-[#f0f3f6]">
      <SideNav />
      <main className="md:pl-[184px]">
        <header className="sticky top-0 z-20">
          <FilterBar />
        </header>
        <div key={location.pathname} className="min-h-[calc(100vh-60px)] pb-12">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/topology" element={<TopologyPage />} />
            <Route path="/anomalies" element={<AnomaliesPage />} />
            <Route path="/anomalies/:id" element={<AnomalyDetailPage />} />
            <Route path="/services" element={<ServicesPage />} />
            <Route path="/services/:name" element={<ServiceDetailPage />} />
            <Route path="/principals" element={<PrincipalsPage />} />
            <Route path="/principals/:name" element={<PrincipalDetailPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/users/:principal" element={<UserDetailPage />} />
            <Route path="/user-changes" element={<UserChangesPage />} />
            <Route path="/user-graph" element={<UserGraphPage />} />
            <Route path="/user-analytics" element={<UserAnalyticsPage />} />
            <Route path="/accounts" element={<PrincipalsPage />} />
            <Route path="/accounts/:username" element={<PrincipalDetailPage />} />
            <Route path="/traces" element={<TracesPage />} />
            <Route path="/traces/:id" element={<TraceDetailPage />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo<Filters>(
    () => ({
      start: params.get("start") || defaultStart,
      end: params.get("end") || defaultEnd,
      timezone: params.get("timezone") || "UTC",
      environment: params.get("environment") || undefined,
      group: params.get("group") || undefined,
      module: params.get("module") || undefined,
      service: params.get("service") || undefined,
      operation: params.get("operation") || undefined,
      account: params.get("account") || undefined,
      comparison: params.get("comparison") || "previous",
    }),
    [params],
  );

  function setFilter(k: keyof Filters, v: string) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (v) next.set(k, v);
        else next.delete(k);
        return next;
      },
      { replace: true },
    );
  }

  return (
    <FilterContext.Provider value={{ filters, setFilter }}>
      <Layout />
    </FilterContext.Provider>
  );
}
