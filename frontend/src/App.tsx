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
import { AgentStatsPage, AgentNodeDetailPage } from "./pages/AgentStats";

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
    {
      label: "User Intelligence",
      accent: "cyan" as const,
      headerClass: "text-cyan-400",
      dotClass: "bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.8)]",
      activeClass: "bg-cyan-500/15 border border-cyan-500/35 text-white font-semibold shadow-sm",
      pillClass: "bg-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.9)]",
      iconActiveClass: "text-cyan-300",
      focusRing: "focus-visible:ring-cyan-400",
      hoverClass: "hover:bg-cyan-500/10 hover:text-cyan-100",
      links: [
        [UserRoundSearch, "Users", "/users"],
        [GitCompareArrows, "User Changes", "/user-changes"],
        [Network, "User Graph", "/user-graph"],
        [ChartNoAxesCombined, "User Analytics", "/user-analytics"],
      ],
    },
    {
      label: "Observability",
      accent: "violet" as const,
      headerClass: "text-violet-400",
      dotClass: "bg-violet-400 shadow-[0_0_8px_rgba(139,92,246,0.8)]",
      activeClass: "bg-violet-500/15 border border-violet-500/35 text-white font-semibold shadow-sm",
      pillClass: "bg-violet-400 shadow-[0_0_10px_rgba(167,139,250,0.9)]",
      iconActiveClass: "text-violet-300",
      focusRing: "focus-visible:ring-violet-400",
      hoverClass: "hover:bg-violet-500/10 hover:text-violet-100",
      links: [
        [LayoutDashboard, "Overview", "/"],
        [GitBranch, "Topology", "/topology"],
        [AlertOctagon, "Anomalies", "/anomalies"],
        [Boxes, "Services", "/services"],
        [Activity, "Traces", "/traces"],
      ],
    },
    {
      label: "Infrastructure",
      accent: "amber" as const,
      headerClass: "text-amber-400",
      dotClass: "bg-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.8)]",
      activeClass: "bg-amber-500/15 border border-amber-500/35 text-white font-semibold shadow-sm",
      pillClass: "bg-amber-400 shadow-[0_0_10px_rgba(251,191,36,0.9)]",
      iconActiveClass: "text-amber-300",
      focusRing: "focus-visible:ring-amber-400",
      hoverClass: "hover:bg-amber-500/10 hover:text-amber-100",
      links: [
        [Radio, "Agent Fleet", "/agent-stats"],
      ],
    },
  ] as const;

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[184px] flex-col border-r border-[rgba(255,255,255,0.12)] bg-[#161424] py-4 md:flex">
      {/* Brand mark */}
      <div className="mb-6 flex items-center gap-2 px-4">
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-cyan-500 via-indigo-600 to-violet-600 text-white shadow-[0_0_20px_-3px_rgba(6,182,212,0.5)]">
          <Activity size={20} strokeWidth={2.5} />
        </div>
        <div>
          <div className="text-xs font-semibold text-[#f5f3fa] tracking-tight">TraceScope</div>
          <div className="text-[9px] uppercase tracking-wider text-cyan-400/90 font-medium">Intelligence</div>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex w-full flex-1 flex-col gap-4 px-2">
        {groups.map((group) => (
          <div key={group.label || "overview"}>
            {group.label && (
              <div className={`mb-1.5 flex items-center gap-1.5 px-2 text-[9px] font-semibold uppercase tracking-[.12em] ${group.headerClass}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${group.dotClass}`} />
                <span>{group.label}</span>
              </div>
            )}
            <div className="space-y-1">
              {group.links.map(([Icon, label, to]) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === "/"}
                  aria-label={label}
                  className={({ isActive }) =>
                    `group relative flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-[11px] font-medium transition duration-150 focus-visible:outline-none focus-visible:ring-2 ${group.focusRing} focus-visible:ring-offset-1 focus-visible:ring-offset-[#161424] ${
                      isActive
                        ? group.activeClass
                        : `text-[#c4bdd9] ${group.hoverClass}`
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <span className={`absolute left-0 h-5 w-1 rounded-r-full ${group.pillClass}`} />
                      )}
                      <Icon
                        size={18}
                        className={
                          isActive
                            ? group.iconActiveClass
                            : "text-[#a59ebf] group-hover:text-white transition-colors"
                        }
                      />
                      <span>{label}</span>
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Database/Storage status */}
      <div className="flex items-center gap-2 px-4 text-[10px] text-[#9e96b8]">
        <div
          title="SQLite Store · WAL mode"
          className="relative grid h-8 w-8 place-items-center rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
        >
          <Database size={14} />
          <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.9)]" />
        </div>
        <div className="flex flex-col">
          <span className="text-[#f5f3fa] font-medium leading-none">SQLite WAL</span>
          <span className="text-[9px] text-emerald-400 mt-0.5">Online</span>
        </div>
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
    <div className="border-b border-[rgba(255,255,255,0.12)] bg-[#161424]/95 px-4 py-2.5 backdrop-blur-md md:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Left: Branding, Status & Global Search */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight text-[#f5f3fa]">TraceScope</span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
              Live Estate
            </span>
          </div>

          {/* Quick Global Search */}
          <form onSubmit={handleGlobalSearch} className="relative hidden lg:block">
            <Search className="absolute left-2.5 top-2 text-[#9e96b8]" size={12} />
            <input
              type="text"
              placeholder="Search services, trace ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-7 w-60 rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] pl-8 pr-3 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/50 focus:bg-white/[0.08] focus:outline-none"
            />
          </form>
        </div>

        {/* Center: Range preset segmented control */}
        <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] p-0.5">
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
                  ? "bg-gradient-to-r from-cyan-600 via-indigo-600 to-violet-600 text-white shadow-sm font-semibold"
                  : "text-[#c4bdd9] hover:text-white"
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
            className={`btn ${showFilters || activeFilterKeys.length > 0 ? "border-cyan-500/50 bg-cyan-500/20 text-cyan-200" : ""}`}
          >
            <SlidersHorizontal size={13} />
            <span>Filters</span>
            {activeFilterKeys.length > 0 && (
              <span className="grid h-4 w-4 place-items-center rounded-full bg-cyan-500 text-[9px] font-bold text-white shadow-[0_0_6px_rgba(6,182,212,0.8)]">
                {activeFilterKeys.length}
              </span>
            )}
          </button>

          {/* Timezone */}
          <select
            aria-label="Timezone"
            value={filters.timezone}
            onChange={(e) => setFilter("timezone", e.target.value)}
            className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa] cursor-pointer"
          >
            <option value="UTC" className="bg-[#1a172a]">UTC</option>
            <option value="Asia/Ho_Chi_Minh" className="bg-[#1a172a]">Asia/Ho Chi Minh</option>
            <option value="local" className="bg-[#1a172a]">Browser Local</option>
          </select>

          {/* Baseline comparison */}
          <select
            aria-label="Comparison period"
            value={filters.comparison}
            onChange={(e) => setFilter("comparison", e.target.value)}
            className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa] cursor-pointer"
          >
            <option value="previous" className="bg-[#1a172a]">vs Prior Window</option>
            <option value="week" className="bg-[#1a172a]">vs Prior Week</option>
            <option value="none" className="bg-[#1a172a]">No Comparison</option>
          </select>

          {/* Auto refresh badge */}
          <div className="chip font-mono text-[10px] text-emerald-300 border-emerald-500/40 bg-emerald-500/10">
            <Radio size={11} className="animate-pulse text-emerald-400" />
            <span>60s rollup</span>
          </div>
        </div>
      </div>

      {/* Expanded filter panel */}
      {showFilters && (
        <div className="mt-3 grid grid-cols-2 gap-2 border-t border-[rgba(255,255,255,0.12)] pt-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["service", "Service", "focus:border-indigo-400"],
            ["operation", "Operation", "focus:border-violet-400"],
            ["account", "Account", "focus:border-cyan-400"],
            ["environment", "Environment", "focus:border-emerald-400"],
            ["group", "Group", "focus:border-amber-400"],
            ["module", "Module", "focus:border-sky-400"],
          ].map(([key, label, focusClass]) => (
            <div key={key} className="flex flex-col gap-1">
              <label className="text-[10px] font-medium uppercase tracking-wider text-[#9e96b8]">
                {label}
              </label>
              <div className="relative">
                <input
                  aria-label={`${label} filter`}
                  placeholder={`All ${label.toLowerCase()}s`}
                  value={filters[key as keyof Filters] || ""}
                  onChange={(e) => setFilter(key as keyof Filters, e.target.value)}
                  className={`w-full rounded-md border border-[rgba(255,255,255,0.14)] bg-white/[0.04] px-2.5 py-1 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] ${focusClass} focus:bg-white/[0.08] focus:outline-none`}
                />
                {filters[key as keyof Filters] && (
                  <button
                    onClick={() => setFilter(key as keyof Filters, "")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[#9e96b8] hover:text-white"
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
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[#9e96b8]">
            Active Filters:
          </span>
          {activeFilterKeys.map((k) => {
            const badgeColorMap: Record<string, string> = {
              account: "border-cyan-500/40 bg-cyan-500/15 text-cyan-200",
              service: "border-indigo-500/40 bg-indigo-500/15 text-indigo-200",
              operation: "border-violet-500/40 bg-violet-500/15 text-violet-200",
              environment: "border-emerald-500/40 bg-emerald-500/15 text-emerald-200",
              group: "border-amber-500/40 bg-amber-500/15 text-amber-200",
              module: "border-sky-500/40 bg-sky-500/15 text-sky-200",
            };
            const badgeColor = badgeColorMap[k] || "border-violet-500/40 bg-violet-500/15 text-violet-200";
            return (
              <span
                key={k}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${badgeColor}`}
              >
                <span className="opacity-75">{k}:</span>
                <span className="font-mono font-medium">{filters[k]}</span>
                <button
                  onClick={() => setFilter(k, "")}
                  className="ml-0.5 hover:text-white"
                  title={`Remove ${k} filter`}
                >
                  <X size={11} />
                </button>
              </span>
            );
          })}
          <button
            onClick={() => activeFilterKeys.forEach((k) => setFilter(k, ""))}
            className="text-[11px] text-[#c4bdd9] hover:text-white underline ml-1"
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
    <div className="min-h-screen bg-[#12101b] text-[#f5f3fa]">
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
            <Route path="/agent-stats" element={<AgentStatsPage />} />
            <Route path="/agent-stats/:node" element={<AgentNodeDetailPage />} />
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
