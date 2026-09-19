import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  NavLink,
  Navigate,
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
  GitCompareArrows,
  LayoutDashboard,
  Network,
  Moon,
  Radio,
  Search,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Users,
  X,
} from "lucide-react";
import type { Filters } from "./types";
import { useI18n, LanguageSwitcher } from "./i18n";
import { OverviewPage } from "./pages/Overview";
import { ServicesPage, ServiceDetailPage } from "./pages/Services";
import { ApiDetailPage } from "./pages/ApiDetail";
import { AnomaliesPage, AnomalyDetailPage } from "./pages/Anomalies";
import { TracesPage, TraceDetailPage } from "./pages/Traces";
import { AgentStatsPage, AgentNodeDetailPage } from "./pages/AgentStats";
import { UnknownUsersPage } from "./pages/UnknownUsers";
import { InteractiveTopologyPage } from "./pages/InteractiveTopology";

// 6 User-Centric Pages & Components
import { UserDirectory } from "./pages/user/UserDirectory";
import { UserLayout } from "./pages/user/UserLayout";
import { UserOverviewTab } from "./pages/user/UserOverviewTab";
import { UserActivityTab } from "./pages/user/UserActivityTab";
import { UserTopologyTab } from "./pages/user/UserTopologyTab";
import { UserChangesTab } from "./pages/user/UserChangesTab";
import { UserPatternsTab } from "./pages/user/UserPatternsTab";
import { UserInvestigationsTab } from "./pages/user/UserInvestigationsTab";

const now = new Date();
const defaultEnd = new Date(now.getTime() + 60_000).toISOString();
const defaultStart = new Date(now.getTime() - 7 * 86400_000).toISOString();

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

type ThemeMode = "dark" | "light";

const ThemeContext = createContext<{
  theme: ThemeMode;
  toggleTheme: () => void;
}>({
  theme: "dark",
  toggleTheme: () => {},
});

export const useTheme = () => useContext(ThemeContext);

function initialTheme(): ThemeMode {
  try {
    return window.localStorage.getItem("tracescope-theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function SideNav() {
  const { t } = useI18n();
  const location = useLocation();
  const groups = [
    {
      label: "Overview",
      accent: "cyan" as const,
      headerClass: "text-cyan-400 font-bold",
      dotClass: "bg-cyan-400",
      activeClass: "bg-cyan-500/20 border border-cyan-400/60 text-white font-bold",
      pillClass: "bg-cyan-400",
      iconActiveClass: "text-cyan-300",
      focusRing: "focus-visible:ring-cyan-400",
      hoverClass: "hover:bg-cyan-500/10 hover:text-white",
      links: [
        [LayoutDashboard, "Dashboard", "/dashboard"],
      ],
    },
    {
      label: "Monitor",
      accent: "violet" as const,
      headerClass: "text-violet-400 font-bold",
      dotClass: "bg-violet-400",
      activeClass: "bg-violet-500/20 border border-violet-400/60 text-white font-bold",
      pillClass: "bg-violet-400",
      iconActiveClass: "text-violet-300",
      focusRing: "focus-visible:ring-violet-400",
      hoverClass: "hover:bg-violet-500/10 hover:text-white",
      links: [
        [Boxes, "Services", "/services"],
        [Users, "Users", "/users"],
        [Network, "Topology", "/topology"],
        [AlertOctagon, "Changes", "/anomalies"],
      ],
    },
    {
      label: "Investigate",
      accent: "sky" as const,
      headerClass: "text-sky-400 font-bold",
      dotClass: "bg-sky-400",
      activeClass: "bg-sky-500/20 border border-sky-400/60 text-white font-bold",
      pillClass: "bg-sky-400",
      iconActiveClass: "text-sky-300",
      focusRing: "focus-visible:ring-sky-400",
      hoverClass: "hover:bg-sky-500/10 hover:text-white",
      links: [
        [Activity, "Traces", "/traces"],
      ],
    },
    {
      label: "System",
      accent: "amber" as const,
      headerClass: "text-amber-400 font-bold",
      dotClass: "bg-amber-400",
      activeClass: "bg-amber-500/20 border border-amber-400/60 text-white font-bold",
      pillClass: "bg-amber-400",
      iconActiveClass: "text-amber-300",
      focusRing: "focus-visible:ring-amber-400",
      hoverClass: "hover:bg-amber-500/10 hover:text-white",
      links: [
        [Radio, "Agent Fleet", "/agent-stats"],
      ],
    },
  ] as const;

  return (
    <aside className="fixed inset-y-0 left-0 z-50 hidden w-[190px] flex-col border-r border-[#262838] bg-[#0c0e17] py-4 md:flex shadow-md">
      {/* Brand mark */}
      <div className="mb-6 flex items-center gap-2.5 px-4">
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-600 border border-indigo-400/40 text-white font-bold">
          <Activity size={20} strokeWidth={2.8} />
        </div>
        <div>
          <div className="text-sm font-bold text-white tracking-tight">TraceScope</div>
          <div className="text-[9px] uppercase tracking-wider text-cyan-300 font-bold">{t("Intelligence")}</div>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex w-full flex-1 flex-col gap-4 px-2">
        {groups.map((group) => (
          <div key={group.label}>
            <div className={`mb-1.5 flex items-center gap-1.5 px-2.5 text-[9px] uppercase tracking-[.14em] ${group.headerClass}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${group.dotClass}`} />
              <span>{t(group.label)}</span>
            </div>
            <div className="space-y-1">
              {group.links.map(([Icon, label, to]) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={(event) => {
                    if (location.pathname !== "/topology" || to === "/topology" || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                    event.preventDefault();
                    window.location.assign(to);
                  }}
                  className={({ isActive }) =>
                    `group relative flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-xs font-semibold transition duration-150 focus-visible:outline-none focus-visible:ring-2 ${group.focusRing} ${
                      isActive
                        ? group.activeClass
                        : `text-[#cbd5e1] ${group.hoverClass}`
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <span className={`absolute left-0 h-5 w-1 rounded-r-full ${group.pillClass}`} />
                      )}
                      <Icon
                        size={17}
                        className={
                          isActive
                            ? group.iconActiveClass
                            : "text-[#94a3b8] group-hover:text-white transition-colors"
                        }
                      />
                      <span>{t(label)}</span>
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Database/Storage status */}
      <div className="flex items-center gap-2 px-4 text-[10px] text-[#cbd5e1] border-t border-[#262838] pt-3">
        <div
          title="ClickHouse Store · Real-Time Analytics"
          className="relative grid h-8 w-8 place-items-center rounded-lg border border-emerald-500/50 bg-emerald-500/20 text-emerald-300"
        >
          <Database size={14} />
          <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-400" />
        </div>
        <div className="flex flex-col">
          <span className="text-white font-bold leading-none">ClickHouse</span>
          <span className="text-[9px] text-emerald-300 font-bold mt-0.5">● {t("Connected")}</span>
        </div>
      </div>
    </aside>
  );
}

function FilterBar() {
  const { filters, setFilter } = useFilters();
  const { theme, toggleTheme } = useTheme();
  const { t } = useI18n();
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
      nav(`/users/${encodeURIComponent(q)}/overview`);
    }
  };

  const activeFilterKeys = (["environment", "group", "module", "service", "operation", "account"] as const).filter(
    (k) => !!filters[k],
  );

  return (
    <div className="border-b border-[#262838] bg-[#0c0e17] px-4 py-2.5 md:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Left: Branding, Status & Global Search */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold tracking-tight text-white">TraceScope</span>
          </div>

          {/* Quick Global Search */}
          <form onSubmit={handleGlobalSearch} className="relative hidden lg:block">
            <Search className="absolute left-2.5 top-2 text-[#94a3b8]" size={13} />
            <input
              type="text"
              placeholder={t("Search service, API, user, or trace ID...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-7 w-64 rounded-lg border border-[#262838] bg-[#141622] pl-8 pr-3 text-xs text-white placeholder:text-[#94a3b8] focus:border-cyan-400 focus:outline-none"
            />
          </form>
        </div>

        {/* Fixed operational window: current five-minute bucket with seven-day history. */}
        <div className="flex items-center gap-2 rounded-lg border border-cyan-500/35 bg-cyan-500/10 px-3 py-1.5 text-xs font-semibold text-cyan-300">
          <Clock size={13} />
          <span>{t("Current: 5m · History: 7d", "Hiện tại: 5 phút · Lịch sử: 7 ngày")}</span>
        </div>

        {/* Right: Dimension filters & controls */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`btn ${showFilters || activeFilterKeys.length > 0 ? "border-cyan-400 bg-cyan-500/25 text-white" : ""}`}
          >
            <SlidersHorizontal size={13} />
            <span>{t("Filters")}</span>
            {activeFilterKeys.length > 0 && (
              <span className="grid h-4 w-4 place-items-center rounded-full bg-cyan-400 text-[9px] font-bold text-black">
                {activeFilterKeys.length}
              </span>
            )}
          </button>

          <LanguageSwitcher />

          <button
            type="button"
            aria-label={theme === "dark" ? t("Switch to light mode", "Chuyển sang chế độ sáng") : t("Switch to dark mode", "Chuyển sang chế độ tối")}
            aria-pressed={theme === "light"}
            title={theme === "dark" ? t("Switch to light mode", "Chuyển sang chế độ sáng") : t("Switch to dark mode", "Chuyển sang chế độ tối")}
            onClick={toggleTheme}
            className="flex items-center gap-1.5 rounded-lg border border-[#262838] bg-[#141622] px-2.5 py-1 text-xs font-bold text-white transition hover:border-amber-400/70 hover:bg-[#1a1d2e] focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            {theme === "dark" ? <Sun size={13} className="text-amber-300" /> : <Moon size={13} className="text-indigo-500" />}
            <span className="hidden xl:inline">{theme === "dark" ? t("Light", "Sáng") : t("Dark", "Tối")}</span>
          </button>

          <select
            aria-label="Timezone"
            value={filters.timezone}
            onChange={(e) => setFilter("timezone", e.target.value)}
            className="btn bg-[#141622] border-[#262838] text-white cursor-pointer"
          >
            <option value="UTC" className="bg-[#141622]">UTC</option>
            <option value="Asia/Ho_Chi_Minh" className="bg-[#141622]">Asia/Ho Chi Minh</option>
            <option value="local" className="bg-[#141622]">Browser Local</option>
          </select>

          <div className="chip font-mono text-[10px] font-bold text-emerald-300 border-emerald-500/40 bg-emerald-500/15">
            <Radio size={11} className="text-emerald-400" />
            <span>{t("Live", "Trực tiếp")}</span>
          </div>
        </div>
      </div>

      {/* Expanded filter panel */}
      {showFilters && (
        <div className="mt-3 grid grid-cols-2 gap-2 border-t border-white/15 pt-3 sm:grid-cols-3 lg:grid-cols-6 animate-in fade-in duration-150">
          {[
            ["service", "Service", "focus:border-indigo-400"],
            ["operation", "Operation", "focus:border-violet-400"],
            ["account", "Account", "focus:border-cyan-400"],
            ["environment", "Environment", "focus:border-emerald-400"],
            ["group", "Group", "focus:border-amber-400"],
            ["module", "Module", "focus:border-sky-400"],
          ].map(([key, label, focusClass]) => (
            <div key={key} className="flex flex-col gap-1">
              <label className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">
                {label}
              </label>
              <div className="relative">
                <input
                  aria-label={`${label} filter`}
                  placeholder={`All ${label.toLowerCase()}s`}
                  value={filters[key as keyof Filters] || ""}
                  onChange={(e) => setFilter(key as keyof Filters, e.target.value)}
                  className={`w-full rounded-md border border-white/20 bg-black/40 px-2.5 py-1 text-xs text-white placeholder:text-[#94a3b8] ${focusClass} focus:outline-none`}
                />
                {filters[key as keyof Filters] && (
                  <button
                    onClick={() => setFilter(key as keyof Filters, "")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[#94a3b8] hover:text-white"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Layout() {
  const location = useLocation();
  return (
    <div className="min-h-screen bg-[#0b0914] text-[#f8fafc]">
      <SideNav />
      <main className="md:pl-[190px]">
        <header className="sticky top-0 z-20">
          <FilterBar />
        </header>
        <div key={location.pathname} className={location.pathname === "/topology" ? "h-[calc(100dvh-94px)]" : "min-h-[calc(100vh-60px)] pb-12"}>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/dashboard" element={<OverviewPage />} />

            {/* User Directory & 6 User-Centric Sub-Pages */}
            <Route path="/users" element={<UserDirectory />} />
            <Route path="/users/:principal" element={<UserLayout />}>
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview" element={<UserOverviewTab />} />
              <Route path="activity" element={<UserActivityTab />} />
              <Route path="topology" element={<UserTopologyTab />} />
              <Route path="changes" element={<UserChangesTab />} />
              <Route path="patterns" element={<UserPatternsTab />} />
              <Route path="investigations" element={<UserInvestigationsTab />} />
            </Route>

            {/* Unattributed Traffic Monitor; kept as a secondary Users-area route */}
            <Route path="/unknown-users" element={<UnknownUsersPage />} />
            <Route path="/users/-anonymous-" element={<Navigate to="/unknown-users" replace />} />
            <Route path="/users/unknown" element={<Navigate to="/unknown-users" replace />} />

            {/* System Observability & Fleet */}
            <Route path="/anomalies" element={<AnomaliesPage />} />
            <Route path="/anomalies/:id" element={<AnomalyDetailPage />} />
            <Route path="/topology" element={<InteractiveTopologyPage />} />
            <Route path="/services" element={<ServicesPage />} />
            <Route path="/services/:name" element={<ServiceDetailPage />} />
            <Route path="/services/:name/apis/:api" element={<ApiDetailPage />} />
            <Route path="/traces" element={<TracesPage />} />
            <Route path="/traces/:id" element={<TraceDetailPage />} />
            <Route path="/agent-stats" element={<AgentStatsPage />} />
            <Route path="/agent-stats/:node" element={<AgentNodeDetailPage />} />

            {/* Backwards compatibility aliases */}
            <Route path="/accounts" element={<Navigate to="/users" replace />} />
            <Route path="/accounts/:username" element={<Navigate to="/users" replace />} />
            <Route path="/principals" element={<Navigate to="/users" replace />} />
            <Route path="/principals/:name" element={<Navigate to="/users" replace />} />
            <Route path="/user-changes" element={<Navigate to="/users" replace />} />
            <Route path="/user-analytics" element={<Navigate to="/users" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const [params, setParams] = useSearchParams();
  const [theme, setTheme] = useState<ThemeMode>(initialTheme);
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

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.setAttribute("content", theme === "light" ? "#f5f7fb" : "#08090a");
    try {
      window.localStorage.setItem("tracescope-theme", theme);
    } catch {
      // Some embedded/browser privacy modes disable localStorage; the current session still works.
    }
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme: () => setTheme((current) => current === "dark" ? "light" : "dark") }}>
      <FilterContext.Provider value={{ filters, setFilter }}>
        <Layout />
      </FilterContext.Provider>
    </ThemeContext.Provider>
  );
}
