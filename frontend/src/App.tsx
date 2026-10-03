import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
  BellRing,
  Boxes,
  Waypoints,
  ChevronDown,
  Clock,
  Compass,
  Database,
  GitCompareArrows,
  LayoutDashboard,
  Network,
  Moon,
  Radio,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sun,
  Users,
  X,
} from "lucide-react";
import type { Filters } from "./types";
import { api, queryString } from "./api";
import { useI18n, LanguageSwitcher } from "./i18n";
import { OverviewPage } from "./pages/Overview";
import { ServicesPage, ServiceDetailPage } from "./pages/Services";
import { ApiDetailPage, ApisPage } from "./pages/ApiDetail";
import { RelationshipMapPage } from "./workspace/MapPage";
import { ApiWorkspacePage, ApisIndexPage, ServiceScopePage, ServicesIndexPage, UserWorkspacePage, UsersIndexPage } from "./workspace/pages";
import { BehaviorPage, BehaviorDetailPage } from "./pages/Behavior";
import { ChangesPage, ChangeDetailPage } from "./pages/Changes";
import { TracesPage, TraceDetailPage } from "./pages/Traces";
import { AgentStatsPage, AgentNodeDetailPage } from "./pages/AgentStats";
import { UnknownUsersPage } from "./pages/UnknownUsers";
import { InteractiveTopologyPage } from "./pages/InteractiveTopology";
import { AlertsPage } from "./pages/Alerts";
import { entityPath } from "./entityRoutes";

// 6 User-Centric Pages & Components
import { UserDirectory } from "./pages/user/UserDirectory";
import { UserLayout } from "./pages/user/UserLayout";
import { UserActivityWorkspace } from "./pages/user/UserActivityWorkspace";
import { LegacyUserInvestigationRedirect, UserChangeDetailPage, UserChangesTab } from "./pages/user/UserChangesTab";

const now = new Date();
const defaultEnd = new Date(now.getTime() + 60_000).toISOString();
const defaultStart = new Date(now.getTime() - 7 * 86400_000).toISOString();

function LegacyAnomalyRedirect() {
  const location = useLocation();
  const legacyId = location.pathname.split("/").filter(Boolean).pop() || "";
  return <Navigate to={`${entityPath({ kind: "change", id: legacyId })}${location.search}`} replace />;
}

const FilterContext = createContext<{
  filters: Filters;
  setFilter: (k: keyof Filters, v: string) => void;
}>({
  filters: {
    start: defaultStart,
    end: defaultEnd,
    timezone: "local",
    comparison: "previous",
  },
  setFilter: () => {},
});

export const useFilters = () => useContext(FilterContext);

import { ThemeProvider, useTheme, type ThemeMode } from "./theme";
export { useTheme, type ThemeMode };

function SideNav() {
  const { t } = useI18n();
  const location = useLocation();
  // API detail lives under /services/:name/apis/:api but belongs to the APIs section.
  const onApiDetail = /^\/services\/[^/]+\/apis\//.test(location.pathname);
  const navActive = (to: string, routeActive: boolean) =>
    to === "/apis" ? routeActive || onApiDetail : to === "/services" ? routeActive && !onApiDetail : routeActive;
  const groups = [
    {
      label: "Dashboard",
      links: [
        [LayoutDashboard, "Dashboard", "/dashboard"],
      ],
    },
    {
      label: "Workspace",
      links: [
        [Network, "Relationship map", "/workspace/map"],
        [Users, "Users", "/workspace/users"],
        [Waypoints, "APIs", "/workspace/apis"],
        [Boxes, "Service scopes", "/workspace/services"],
      ],
    },
    {
      label: "Explore",
      links: [
        [Boxes, "Services", "/services"],
        [Waypoints, "APIs", "/apis"],
        [Users, "Users", "/users"],
        [Network, "Topology", "/topology"],
        [GitCompareArrows, "Learned behavior", "/behavior"],
      ],
    },
    {
      label: "Changes",
      links: [
        [AlertOctagon, "Changes", "/changes"],
        [BellRing, "Alerts", "/alerts"],
      ],
    },
    {
      label: "Investigate",
      links: [
        [Activity, "Traces", "/traces"],
      ],
    },
    {
      label: "System",
      links: [
        [Radio, "Agent Fleet", "/agent-stats"],
      ],
    },
  ] as const;

  return (
    <aside className="app-rail fixed inset-y-0 left-0 z-50 hidden w-[230px] flex-col py-4 md:flex bg-structure border-r border-structure-line">
      {/* Brand mark */}
      <div className="mb-5 flex items-center gap-2.5 px-3">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-ctl bg-accent text-white font-bold shadow-card">
          <Activity size={18} strokeWidth={2.5} />
        </div>
        <div className="rail-label">
          <div className="text-sm font-bold text-ink tracking-tight">TraceScope</div>
          <div className="text-[10.5px] uppercase tracking-wider text-structure-ink/70 font-bold">{t("Intelligence")}</div>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex w-full flex-1 flex-col gap-3 px-2">
        {groups.map((group) => (
          <div key={group.label}>
            <div className="mb-1.5 flex items-center gap-1.5 px-2 text-[11px] uppercase tracking-[.14em] font-semibold text-muted">
              <span className="rail-section-label">{t(group.label)}</span>
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
                  className={({ isActive: routeActive }) => {
                    const isActive = navActive(to, routeActive);
                    return `group relative flex h-8 w-full items-center gap-2.5 rounded-ctl px-2.5 text-[12.5px] font-medium transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                      isActive
                        ? "bg-accent-soft text-ink font-semibold"
                        : "text-structure-ink/80 hover:bg-structure-2 hover:text-ink"
                    }`;
                  }}
                >
                  {({ isActive: routeActive }) => {
                    const isActive = navActive(to, routeActive);
                    return (
                      <>
                        {isActive && (
                          <span className="absolute left-0 h-4.5 w-1 rounded-r-full bg-accent" />
                        )}
                        <Icon
                          size={16}
                          className={
                            isActive
                              ? "text-accent"
                              : "text-muted group-hover:text-ink transition-colors"
                          }
                        />
                        <span className="rail-label">{t(label)}</span>
                      </>
                    );
                  }}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Database/Storage status */}
      <div className="flex items-center gap-2 px-3 text-[11px] text-muted border-t border-structure-line pt-3">
        <div
          title={t("ClickHouse Store · Real-Time Analytics")}
          className="relative grid h-7 w-7 shrink-0 place-items-center rounded-ctl border border-good-bd bg-good-bg text-good"
        >
          <Database size={14} />
          <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-good" />
        </div>
        <div className="rail-label flex flex-col">
          <span className="text-ink font-bold leading-none">ClickHouse</span>
          <span className="text-[10px] text-good font-bold mt-0.5">● {t("Connected")}</span>
        </div>
      </div>
    </aside>
  );
}

type FilterService = { name: string; environment?: string; service_group?: string; service_module?: string };
type EntityFilterKey = "service" | "operation" | "account" | "environment" | "group" | "module";
const entityFilterFields: Array<{ key: EntityFilterKey; label: string }> = [
  { key: "service", label: "Service" }, { key: "operation", label: "Operation" },
  { key: "account", label: "Account" }, { key: "environment", label: "Environment" },
  { key: "group", label: "Group" }, { key: "module", label: "Module" },
];

function FilterBar() {
  const { filters, setFilter } = useFilters();
  const { theme, toggleTheme } = useTheme();
  const { t } = useI18n();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [showFilters, setShowFilters] = useState(false);
  const optionWindow = queryString({ start: filters.start, end: filters.end, timezone: filters.timezone, comparison: "none" });
  const serviceOptionsQuery = useQuery({
    queryKey: ["toolbar-service-options", optionWindow],
    queryFn: () => api<{ items: FilterService[] }>(`/api/v1/services?${optionWindow}&limit=500`),
    enabled: showFilters, staleTime: 60000,
  });
  const accountOptionsQuery = useQuery({
    queryKey: ["toolbar-account-options", optionWindow],
    queryFn: () => api<{ items: Array<{ principal_name: string }>; total?: number }>(`/api/v1/users?${optionWindow}&limit=500`),
    enabled: showFilters, staleTime: 60000,
  });
  const operationOptionsQuery = useQuery({
    queryKey: ["toolbar-operation-options", optionWindow, filters.service],
    queryFn: () => api<{ operations: Array<{ name: string }> }>(`/api/v1/services/${encodeURIComponent(filters.service || "")}?${optionWindow}`),
    enabled: showFilters && !!filters.service, staleTime: 60000,
  });
  const optionServices = serviceOptionsQuery.data?.items || [];
  const observedOptions: Record<EntityFilterKey, Array<string | undefined>> = {
    service: optionServices.map((item) => item.name),
    environment: optionServices.map((item) => item.environment),
    group: optionServices.map((item) => item.service_group),
    module: optionServices.map((item) => item.service_module),
    account: (accountOptionsQuery.data?.items || []).map((item) => item.principal_name),
    operation: (operationOptionsQuery.data?.operations || []).map((item) => item.name),
  };
  const [searchQuery, setSearchQuery] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const entitySearchQuery = useQuery({
    queryKey: ["global-entity-search", searchQuery.trim()],
    queryFn: () => api<{ services: Array<{ name: string }>; apis: Array<{ service: string; name: string }> }>(`/api/v1/search?q=${encodeURIComponent(searchQuery.trim())}&limit=20`),
    enabled: searchQuery.trim().length >= 2,
    staleTime: 30000,
  });
  const nav = useNavigate();

  const currentEntity = useMemo(() => {
    const path = location.pathname;
    if (path.startsWith("/workspace")) {
      const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
      if (parts[1] === "map") return t("Relationship map", "Bản đồ quan hệ");
      if (parts[1] === "users") return parts[2] ? `${t("User")}: ${parts[2]}` : t("Users");
      if (parts[1] === "apis") return parts[3] ? `${t("API")}: ${parts[3]} (${parts[2]})` : t("APIs");
      if (parts[1] === "services") return parts[2] ? `${t("Service scope", "Phạm vi Service")}: ${parts[2]}` : t("Service scopes", "Phạm vi Service");
    }
    if (path.startsWith("/users/")) {
      const parts = path.split("/").filter(Boolean);
      const principal = decodeURIComponent(parts[1] || "");
      if (principal) return `${t("User")}: ${principal}`;
      return t("Users");
    }
    if (path.startsWith("/services/")) {
      const parts = path.split("/").filter(Boolean);
      const svcName = decodeURIComponent(parts[1] || "");
      if (parts[2] === "apis" && parts[3]) {
        return `${t("API")}: ${decodeURIComponent(parts[3])} (${svcName})`;
      }
      if (svcName) return `${t("Service")}: ${svcName}`;
      return t("Services");
    }
    if (path.startsWith("/traces/")) {
      const parts = path.split("/").filter(Boolean);
      const traceId = decodeURIComponent(parts[1] || "");
      if (traceId) return `${t("Trace")}: ${traceId.slice(0, 8)}…`;
      return t("Traces");
    }
    if (path.startsWith("/changes/")) {
      const parts = path.split("/").filter(Boolean);
      const changeId = decodeURIComponent(parts[1] || "");
      if (changeId) return `${t("Change")}: ${changeId}`;
      return t("Changes");
    }
    if (path.startsWith("/agent-stats/")) {
      const parts = path.split("/").filter(Boolean);
      const node = decodeURIComponent(parts[1] || "");
      if (node) return `${t("Agent")}: ${node}`;
      return t("Agent Fleet");
    }
    if (path === "/agent-stats") return t("Agent Fleet");
    if (path === "/topology") return t("Topology");
    if (path === "/services") return t("Services");
    if (path === "/users") return t("Users");
    if (path.startsWith("/behavior")) return t("Learned behavior", "Hành vi đã học");
    if (path === "/changes") return t("Changes");
    if (path === "/traces") return t("Traces");
    if (path === "/dashboard" || path === "/overview" || path === "/") return t("Dashboard");
    return t("Overview");
  }, [location.pathname, t]);

  const handleGlobalSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;

    if (/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(q)) {
      nav(`/users?q=${encodeURIComponent(q)}`);
      return;
    }

    if (q.includes("/")) {
      const [svc, ...opParts] = q.split("/").map((p) => p.trim());
      if (svc && opParts.length > 0) {
        nav(entityPath({ kind: "api", service: svc, operation: opParts.join("/") }));
        return;
      }
    }

    const searchData = entitySearchQuery.data;
    const exactService = searchData?.services.find((item) => item.name.toLowerCase() === q.toLowerCase());
    if (exactService) {
      nav(entityPath({ kind: "service", name: exactService.name }));
      return;
    }
    const exactApi = searchData?.apis.find((item) => item.name.toLowerCase() === q.toLowerCase() || `${item.service}/${item.name}`.toLowerCase() === q.toLowerCase());
    if (exactApi) {
      nav(entityPath({ kind: "api", service: exactApi.service, operation: exactApi.name }));
      return;
    }
    if (searchData?.services[0] && !/^user:/i.test(q) && !/^change:/i.test(q)) {
      nav(entityPath({ kind: "service", name: searchData.services[0].name }));
      return;
    }
    if (searchData?.apis[0]) {
      nav(entityPath({ kind: "api", service: searchData.apis[0].service, operation: searchData.apis[0].name }));
      return;
    }

    if (/^service:/i.test(q)) {
      nav(entityPath({ kind: "service", name: q.replace(/^service:/i, "").trim() }));
      return;
    }
    if (/^user:/i.test(q)) {
      nav(entityPath({ kind: "user", principal: q.replace(/^user:/i, "").trim() }));
      return;
    }
    if (/^change:/i.test(q)) {
      nav(entityPath({ kind: "change", id: q.replace(/^change:/i, "").trim() }));
      return;
    }
    if (/^trace:/i.test(q)) {
      nav(`/traces/${encodeURIComponent(q.replace(/^trace:/i, "").trim())}`);
      return;
    }

    if (/^[a-fA-F0-9]{16,64}$/.test(q)) {
      nav(`/traces/${encodeURIComponent(q)}`);
      return;
    }

    nav(entityPath({ kind: "user", principal: q }));
  };

  const handleRefresh = () => {
    setIsRefreshing(true);
    queryClient.invalidateQueries();
    setTimeout(() => setIsRefreshing(false), 500);
  };

  const activeFilterKeys = (["environment", "group", "module", "service", "operation", "account"] as const).filter(
    (k) => !!filters[k],
  );

  return (
    <div className="toolbar px-3 py-1.5 md:px-4">
      {/* One line from lg up in every language: the left side shrinks (breadcrumb truncates, search narrows)
          and the controls never wrap. Below lg the controls always take their own second line. */}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 lg:flex-nowrap">
        {/* Left: Branding, Current entity & Global Search */}
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-xs font-bold tracking-tight text-muted">
              TraceScope / <span className="text-ink font-semibold">{currentEntity}</span>
            </span>
          </div>

          {/* Quick Global Search */}
          <form onSubmit={handleGlobalSearch} className="relative hidden min-w-[9rem] max-w-64 flex-1 xl:block">
            <Search className="absolute left-2.5 top-2 text-faint" size={13} />
            <input
              type="text"
              placeholder={t("Search service, API, user, IP, or trace ID...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-7 w-full rounded-ctl border border-line-strong bg-bg pl-8 pr-3 text-[11.5px] text-ink placeholder:text-faint focus:border-line-strong focus:outline-none"
            />
          </form>
        </div>

        {/* Middle/Right: Operational window, Refresh, Filters, Language, Theme */}
        <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto lg:shrink-0 lg:flex-nowrap">
          {/* Fixed operational window: current five-minute bucket with seven-day history. */}
          <div className="flex items-center gap-1.5 rounded-ctl border border-line bg-surface-2 px-2.5 py-1 text-[11px] font-semibold text-muted">
            <Clock size={13} />
            <span className="hidden 2xl:inline">{t("Current: 5m · History: 7d", "Hiện tại: 5 phút · Lịch sử: 7 ngày")}</span>
            <span className="2xl:hidden" title={t("Current: 5m · History: 7d", "Hiện tại: 5 phút · Lịch sử: 7 ngày")}>5m · 7d</span>
          </div>

          <button
            type="button"
            aria-label={t("Refresh", "Làm mới")}
            title={t("Refresh telemetry data", "Làm mới dữ liệu")}
            onClick={handleRefresh}
            className="flex items-center gap-1.5 rounded-ctl border border-line-strong bg-bg px-2.5 py-1 text-[11px] font-semibold text-ink transition hover:bg-hover"
          >
            <RefreshCw size={12} className={`text-muted ${isRefreshing ? "animate-spin text-accent" : ""}`} />
            <span className="hidden 2xl:inline">{t("Refresh", "Làm mới")}</span>
          </button>

          <button
            type="button"
            aria-expanded={showFilters}
            aria-controls="toolbar-filters"
            onClick={() => setShowFilters(!showFilters)}
            className={`flex items-center gap-1.5 rounded-ctl border border-line-strong bg-bg px-2.5 py-1 text-[11px] font-semibold transition hover:bg-hover ${showFilters || activeFilterKeys.length > 0 ? "border-accent bg-accent-soft text-ink font-semibold" : "text-ink"}`}
          >
            <SlidersHorizontal size={13} />
            <span>{t("Filters")}</span>
            {activeFilterKeys.length > 0 && (
              <span className="grid h-4 w-4 place-items-center rounded-full bg-accent text-[10px] font-bold text-white">
                {activeFilterKeys.length}
              </span>
            )}
          </button>

          <LanguageSwitcher />

          <div className="seg flex items-center rounded-ctl border border-line-strong bg-bg p-0.5" role="group" aria-label="Theme">
            {(["light", "dark"] as const).map((mode) => {
              const active = theme === mode;
              const Icon = mode === "light" ? Sun : Moon;
              const label = mode === "light" ? t("Light", "Sáng") : t("Dark", "Tối");
              return (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={active}
                  onClick={() => !active && toggleTheme()}
                  className={`flex items-center gap-1 rounded-ctl px-2 py-0.5 text-[11px] font-semibold transition-colors ${
                    active
                      ? "bg-surface-2 text-ink shadow-sm"
                      : "text-muted hover:text-ink"
                  }`}
                >
                  <Icon size={12} />
                  <span className="hidden 2xl:inline">{label}</span>
                </button>
              );
            })}
          </div>

          <select
            aria-label={t("Timezone")}
            value={filters.timezone}
            onChange={(e) => setFilter("timezone", e.target.value)}
            className="w-[9.5rem] truncate rounded-ctl border border-line-strong bg-bg px-2 py-1 text-[11px] font-semibold text-ink cursor-pointer"
          >
            <option value="local">{t("Browser Local", "Browser local")}</option>
            <option value="UTC">UTC</option>
            <option value="Asia/Ho_Chi_Minh">Asia/Ho Chi Minh</option>
          </select>

          <div className="chip w-[5.75rem] justify-center whitespace-nowrap font-mono text-[10.5px] font-bold text-good border border-good-bd bg-good-bg rounded-ctl">
            <Radio size={11} className="text-good" />
            <span>{t("Live", "Trực tiếp")}</span>
          </div>
        </div>
      </div>

      {/* Expanded filter panel */}
      {showFilters && (
        <div id="toolbar-filters" className="mt-2 grid grid-cols-2 gap-2 border-t border-line pt-2 sm:grid-cols-3 lg:grid-cols-6">
          {entityFilterFields.map(({ key, label }) => {
            const source = key === "account" ? accountOptionsQuery : key === "operation" ? operationOptionsQuery : serviceOptionsQuery;
            const needsService = key === "operation" && !filters.service;
            const values = [...new Set([...observedOptions[key], filters[key]].filter((value): value is string => !!value))].sort((a, b) => a.localeCompare(b));
            const hint = needsService ? t("Select a service first", "Chọn Service trước")
              : source.isLoading ? t("Loading options…", "Đang tải lựa chọn…")
              : source.isError ? t("Options unavailable", "Không tải được lựa chọn")
              : values.length === 0 ? t("No observed values", "Chưa có giá trị quan sát")
              : (key === "account" || key === "service") && values.length >= 500 ? t("Showing up to 500 values", "Hiển thị tối đa 500 giá trị") : "";
            return <div key={key} className="flex min-w-0 flex-col gap-1">
              <label htmlFor={`toolbar-filter-${key}`} className="text-[10px] font-bold uppercase tracking-wider text-muted">{t(label)}</label>
              <div className="flex items-center gap-1">
                <select
                  id={`toolbar-filter-${key}`}
                  aria-label={`${label} filter`}
                  aria-describedby={hint ? `toolbar-filter-${key}-hint` : undefined}
                  value={filters[key] || ""}
                  disabled={needsService && !filters[key]}
                  onChange={(event) => setFilter(key, event.target.value)}
                  className="min-w-0 flex-1 cursor-pointer rounded-ctl border border-line-strong bg-bg px-2 py-1 text-[11px] text-ink focus:border-line-strong focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">{t("All", "Tất cả")} · {t(label)}</option>
                  {values.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
                {filters[key] && <button type="button" aria-label={`${t("Clear", "Xóa")} ${t(label)}`} onClick={() => setFilter(key, "")} className="p-1 text-muted hover:text-ink focus-visible:outline focus-visible:outline-2"><X size={12} /></button>}
              </div>
              {hint && <span id={`toolbar-filter-${key}-hint`} className="text-[10px] text-muted">{hint}{source.isError && !needsService && <button type="button" onClick={() => source.refetch()} className="ml-1 text-ink underline">{t("Retry", "Thử lại")}</button>}</span>}
            </div>;
          })}
        </div>
      )}
    </div>
  );
}

function Layout() {
  const location = useLocation();
  return (
    <div className="min-h-screen bg-page text-ink">
      <SideNav />
      <main className="md:pl-[230px]">
        <header className="sticky top-0 z-20">
          <FilterBar />
        </header>
        <div key={location.pathname} className={location.pathname === "/topology" ? "h-[calc(100dvh-94px)]" : "min-h-[calc(100vh-60px)] pb-12"}>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/dashboard" element={<OverviewPage />} />

            {/* User Directory & 2 operator-facing workspace views */}
            <Route path="/users" element={<UserDirectory />} />
            <Route path="/users/:principal" element={<UserLayout />}>
              <Route index element={<Navigate to="activity" replace />} />
              <Route path="overview" element={<Navigate to="../activity" replace />} />
              <Route path="activity" element={<UserActivityWorkspace />} />
              <Route path="changes" element={<UserChangesTab />} />
              <Route path="changes/:episodeId" element={<UserChangeDetailPage />} />
              {/* Compatibility aliases for the former six-tab workspace. */}
              <Route path="topology" element={<Navigate to="../activity" replace />} />
              <Route path="patterns" element={<Navigate to="../activity" replace />} />
              <Route path="investigations" element={<LegacyUserInvestigationRedirect />} />
            </Route>

            {/* Unattributed Traffic Monitor; kept as a secondary Users-area route */}
            <Route path="/unknown-users" element={<UnknownUsersPage />} />
            <Route path="/users/-anonymous-" element={<Navigate to="/unknown-users" replace />} />
            <Route path="/users/unknown" element={<Navigate to="/unknown-users" replace />} />

            {/* System Observability & Fleet */}
            <Route path="/behavior" element={<BehaviorPage />} />
            <Route path="/behavior/profiles/:id" element={<BehaviorDetailPage kind="profiles" />} />
            <Route path="/behavior/deviations/:id" element={<BehaviorDetailPage kind="deviations" />} />
            <Route path="/changes" element={<ChangesPage />} />
            <Route path="/changes/:id" element={<ChangeDetailPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/anomalies" element={<Navigate to="/changes" replace />} />
            <Route path="/anomalies/:id" element={<LegacyAnomalyRedirect />} />
            <Route path="/topology" element={<InteractiveTopologyPage />} />
            <Route path="/services" element={<ServicesPage />} />
            <Route path="/services/:name" element={<ServiceDetailPage />} />
            <Route path="/services/:name/apis/:api" element={<ApiDetailPage />} />
            <Route path="/apis" element={<ApisPage />} />
            <Route path="/workspace" element={<Navigate to="/workspace/users" replace />} />
            <Route path="/workspace/map" element={<RelationshipMapPage />} />
            <Route path="/workspace/users" element={<UsersIndexPage />} />
            <Route path="/workspace/users/:principal" element={<UserWorkspacePage />} />
            <Route path="/workspace/apis" element={<ApisIndexPage />} />
            <Route path="/workspace/apis/:service/:api" element={<ApiWorkspacePage />} />
            <Route path="/workspace/services" element={<ServicesIndexPage />} />
            <Route path="/workspace/services/:service" element={<ServiceScopePage />} />
            <Route path="/traces" element={<TracesPage />} />
            <Route path="/traces/:id" element={<TraceDetailPage />} />
            <Route path="/agent-stats" element={<AgentStatsPage />} />
            <Route path="/agent-stats/:node" element={<AgentNodeDetailPage />} />

            {/* Backwards compatibility aliases */}
            <Route path="/accounts" element={<Navigate to="/users" replace />} />
            <Route path="/accounts/:username" element={<Navigate to="/users" replace />} />
            <Route path="/principals" element={<Navigate to="/users" replace />} />
            <Route path="/principals/:name" element={<Navigate to="/users" replace />} />
            <Route path="/user-changes" element={<Navigate to="/changes" replace />} />
            <Route path="/user-analytics" element={<Navigate to="/users" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

function AppInner() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo<Filters>(
    () => ({
      start: params.get("start") || defaultStart,
      end: params.get("end") || defaultEnd,
      timezone: params.get("timezone") || "local",
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
        if (k === "service" && v !== (prev.get("service") || "")) next.delete("operation");
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

export default function App() {
  return (
    <ThemeProvider>
      <AppInner />
    </ThemeProvider>
  );
}
