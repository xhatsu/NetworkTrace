import { useState } from "react";
import {
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertOctagon,
  ArrowLeft,
  Calendar,
  CheckCircle2,
  ChevronDown,
  Clock,
  Compass,
  GitCompareArrows,
  Layers,
  Network,
  Radio,
  Search,
  Shield,
  ShieldAlert,
  Sparkles,
  User,
  Users,
} from "lucide-react";
import { api, queryString } from "../../api";
import { useFilters } from "../../App";
import { Panel, TpsLineChart, n } from "../../components";
import { useI18n } from "../../i18n";

export function UserLayout() {
  const { principal = "" } = useParams<{ principal: string }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Determine current active subtab
  const currentTab = location.pathname.split("/")[3] || "overview";

  // Fetch full user profile
  const {
    data: profile,
    isLoading: profileLoading,
    error: profileError,
  } = useQuery({
    queryKey: ["user-detail", principal, filters],
    queryFn: () =>
      api<any>(`/api/v1/users/${encodeURIComponent(principal)}?${queryString(filters)}`),
    enabled: !!principal,
  });

  // Fetch all users for quick switcher
  const { data: allUsers } = useQuery({
    queryKey: ["users-list-quick"],
    queryFn: () => api<any>(`/api/v1/users?limit=200`),
    staleTime: 60_000,
  });

  // Keep the scoped TPS trend visible above every user workspace tab. The
  // overview tab shares this query key, so this does not create a second
  // request when the tab is mounted.
  const { data: performance } = useQuery({
    queryKey: ["user-performance", principal, filters],
    queryFn: () =>
      api<any>(`/api/v1/users/${encodeURIComponent(principal)}/performance?${queryString(filters)}`),
    enabled: !!principal,
  });
  const tpsSeries = (performance?.series || [])
    .map((row: any) => ({
      timestamp_ms: Number(row.timestamp_ms ?? Number(row.bucket_start ?? 0) * 1000),
      tps: Number(row.tps ?? row.rps ?? 0),
    }))
    .filter((row: { timestamp_ms: number; tps: number }) => Number.isFinite(row.timestamp_ms) && row.timestamp_ms > 0);

  // Update principal type
  const updateTypeMutation = useMutation({
    mutationFn: (newType: string) =>
      api(`/api/v1/users/${encodeURIComponent(principal)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ principal_type: newType }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-detail", principal] });
      queryClient.invalidateQueries({ queryKey: ["users-list-quick"] });
    },
  });

  const userList: any[] = allUsers?.items || [];
  const filteredUsers = userList.filter((u) =>
    (u.principal_name || "").toLowerCase().includes(searchQuery.toLowerCase())
  );

  const tabs = [
    {
      id: "overview",
      label: t("Overview"),
      question: t("Is this user behaving normally right now?"),
      path: `/users/${encodeURIComponent(principal)}/overview`,
      icon: Radio,
    },
    {
      id: "activity",
      label: t("Activity"),
      question: t("How has traffic & performance changed?"),
      path: `/users/${encodeURIComponent(principal)}/activity`,
      icon: Activity,
    },
    {
      id: "topology",
      label: t("Access"),
      question: t("What systems is this user touching?"),
      path: `/users/${encodeURIComponent(principal)}/topology`,
      icon: Network,
    },
    {
      id: "changes",
      label: t("Changes"),
      question: t("What is different from normal behavior?"),
      path: `/users/${encodeURIComponent(principal)}/changes`,
      icon: GitCompareArrows,
      badge: profile?.changes?.length || profile?.recent_changes || 0,
    },
    {
      id: "patterns",
      label: t("Patterns"),
      question: t("When and how does this user normally operate?"),
      path: `/users/${encodeURIComponent(principal)}/patterns`,
      icon: Layers,
    },
    {
      id: "investigations",
      label: t("Investigations"),
      question: t("What needs investigation?"),
      path: `/users/${encodeURIComponent(principal)}/investigations`,
      icon: AlertOctagon,
      alert: (profile?.behavior_score || 0) >= 60,
    },
  ];

  const score = profile?.behavior_score ?? 0;
  const isHighRisk = score >= 60;
  const isMedRisk = score >= 25 && score < 60;

  return (
    <div className="mx-auto max-w-[1720px] px-4 py-5 md:px-8">
      {/* Top breadcrumb & quick back */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-[#94a3b8]">
          <button
            onClick={() => nav("/users")}
            className="flex items-center gap-1.5 rounded-lg border border-[rgba(255,255,255,0.18)] bg-[rgba(255,255,255,0.06)] px-2.5 py-1 text-xs font-semibold text-white transition hover:border-cyan-400/60 hover:bg-cyan-500/20 hover:text-cyan-200"
          >
            <ArrowLeft size={13} />
            <span>{t("User Directory")}</span>
          </button>
          <span className="text-white/40">/</span>
          <span className="font-mono font-semibold text-white">{principal}</span>
          <span className="text-white/40">/</span>
          <span className="capitalize text-cyan-400 font-semibold">{currentTab}</span>
        </div>

        {/* Quick User Switcher dropdown */}
        <div className="relative">
          <button
            onClick={() => setSwitcherOpen(!switcherOpen)}
            className="flex items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.22)] bg-[#191530] px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:border-cyan-400 hover:bg-[#211c40]"
          >
            <Users size={14} className="text-cyan-400" />
            <span className="text-[#94a3b8]">Switch Account:</span>
            <span className="font-mono text-white font-bold">{principal}</span>
            <ChevronDown size={14} className="text-[#cbd5e1]" />
          </button>

          {switcherOpen && (
            <div className="absolute right-0 top-full z-50 mt-1.5 w-80 rounded-xl border border-[#2e3247] bg-[#161825] p-2.5 shadow-xl">
              <div className="relative mb-2">
                <Search className="absolute left-2.5 top-2.5 text-[#94a3b8]" size={13} />
                <input
                  type="text"
                  autoFocus
                  placeholder="Filter users..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full rounded-lg border border-[#2e3247] bg-[#0e1019] pl-8 pr-3 py-1.5 text-xs text-white placeholder:text-[#94a3b8] focus:border-cyan-400 focus:outline-none"
                />
              </div>
              <div className="max-h-60 overflow-y-auto space-y-1 scrollbar">
                {filteredUsers.slice(0, 30).map((u) => (
                  <button
                    key={u.principal_name}
                    onClick={() => {
                      setSwitcherOpen(false);
                      setSearchQuery("");
                      nav(`/users/${encodeURIComponent(u.principal_name)}/${currentTab}`);
                    }}
                    className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs transition ${
                      u.principal_name === principal
                        ? "bg-cyan-500/20 border border-cyan-500/40 text-white font-bold"
                        : "text-[#cbd5e1] hover:bg-[#202436] hover:text-white"
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <div className="grid h-5 w-5 place-items-center rounded-md bg-white/10 text-cyan-300 text-[10px]">
                        {u.principal_name.slice(0, 2).toUpperCase()}
                      </div>
                      <span className="truncate font-mono">{u.principal_name}</span>
                    </div>
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        (u.behavior_score || 0) >= 60
                          ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                          : (u.behavior_score || 0) >= 25
                          ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                          : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                      }`}
                    >
                      {u.behavior_score || 0}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* User Identity Banner */}
      <div className="mb-5 rounded-xl border border-[#262838] bg-[#141622] p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="relative grid h-11 w-11 place-items-center rounded-xl bg-indigo-600 border border-indigo-400/40 text-white">
              <User size={22} strokeWidth={2.2} />
              <span
                className={`absolute -bottom-1 -right-1 h-4 w-4 rounded-full border-2 border-[#141622] ${
                  profile?.status === "Active"
                    ? "bg-emerald-400"
                    : "bg-slate-500"
                }`}
              />
            </div>

            <div>
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-cyan-400">
                  User identity
                </span>
                <span className="text-white/30">•</span>
                <span className="text-xs font-semibold text-[#cbd5e1]">
                  Environment: <strong className="text-white">{profile?.environment || "production"}</strong>
                </span>
              </div>
              <h1 className="mt-0.5 text-xl md:text-2xl font-bold tracking-tight text-white font-mono">
                <span className="text-cyan-300">{principal}</span>
              </h1>
            </div>
          </div>

          {/* Badges & Health status */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Status pill */}
            <div
              className={`inline-flex items-center gap-2 rounded-xl border px-3 py-1.5 text-xs font-bold ${
                profile?.status === "Active"
                  ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
                  : "border-slate-600/50 bg-slate-800/40 text-slate-300"
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  profile?.status === "Active" ? "bg-emerald-400" : "bg-slate-400"
                }`}
              />
              <span>{profile?.status || "Active"}</span>
            </div>

            {/* Principal Type dropdown selector */}
            <select
              aria-label="Principal type"
              value={profile?.principal_type || "service_account"}
              onChange={(e) => updateTypeMutation.mutate(e.target.value)}
              className="rounded-xl border border-[#2e3247] bg-[#141622] px-3 py-1.5 text-xs font-bold text-white shadow-sm transition hover:border-cyan-400 focus:outline-none cursor-pointer"
            >
              <option value="service_account" className="bg-[#141622]">Service Account</option>
              <option value="human" className="bg-[#141622]">Human User</option>
              <option value="system_account" className="bg-[#141622]">System Account</option>
              <option value="shared_credential" className="bg-[#141622]">Shared Credential</option>
              <option value="integration_account" className="bg-[#141622]">Integration Account</option>
              <option value="unknown" className="bg-[#141622]">Unknown</option>
            </select>

            {/* Baseline learning status */}
            <div className="inline-flex items-center gap-1.5 rounded-xl border border-violet-500/40 bg-violet-500/15 px-3 py-1.5 text-xs font-bold text-violet-200">
              <Sparkles size={13} className="text-violet-300" />
              <span>{profile?.learning_status === "learning" ? "Learning Baseline" : "Established Baseline"}</span>
            </div>

            {/* Behavioral Score Badge */}
            <div
              className={`inline-flex items-center gap-2 rounded-xl border px-3 py-1.5 text-xs font-bold shadow-sm ${
                isHighRisk
                  ? "border-rose-500/60 bg-rose-500/15 text-rose-200"
                  : isMedRisk
                  ? "border-amber-500/60 bg-amber-500/15 text-amber-200"
                  : "border-emerald-500/60 bg-emerald-500/15 text-emerald-200"
              }`}
            >
              {isHighRisk ? <ShieldAlert size={14} /> : <Shield size={14} />}
              <span>Anomaly Score: {score}/100</span>
              <span className="opacity-80">({isHighRisk ? "HIGH" : isMedRisk ? "MEDIUM" : "LOW"})</span>
            </div>
          </div>
        </div>

        {/* Mini stats ribbon */}
        <div className="mt-4 grid grid-cols-2 gap-2 border-t border-[rgba(255,255,255,0.12)] pt-3 text-xs sm:grid-cols-4 md:grid-cols-4">
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Total Requests</span>
            <div className="font-mono text-sm font-bold text-white">
              {(profile?.total_requests || 0).toLocaleString()}
            </div>
          </div>
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Active Targets</span>
            <div className="font-mono text-sm font-bold text-cyan-300">
              {profile?.unique_targets ?? profile?.current?.targets?.length ?? 0} services
            </div>
          </div>
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Active Callers</span>
            <div className="font-mono text-sm font-bold text-violet-300">
              {profile?.unique_callers ?? profile?.current?.callers?.length ?? 0} callers
            </div>
          </div>
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Active Operations</span>
            <div className="font-mono text-sm font-bold text-emerald-300">
              {profile?.unique_operations ?? profile?.current?.operations?.length ?? 0} endpoints
            </div>
          </div>
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Source IPs</span>
            <div className="font-mono text-sm font-bold text-amber-300">
              {profile?.unique_sources ?? profile?.current?.sources?.length ?? 0} IPs
            </div>
          </div>
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Active Window</span>
            <div className="font-mono text-xs font-bold text-[#e2e8f0]">
              {profile?.typical_active_window || "All Hours"}
            </div>
          </div>
        </div>
      </div>

      <Panel
        title={t("TPS")}
        subtitle={t("Observed user throughput over the selected window")}
        className="mb-3"
        action={<span className="font-mono text-[11px] text-[#5794f2]">{n(tpsSeries[tpsSeries.length - 1]?.tps || 0, 2)} TPS</span>}
      >
        <TpsLineChart data={tpsSeries} />
      </Panel>

      {/* Compact user investigation navigation */}
      <div className="mb-5 flex flex-wrap gap-1.5 border-b border-[rgba(255,255,255,0.16)] pb-2">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = currentTab === tab.id;
          return (
            <NavLink
              key={tab.id}
              to={tab.path}
              className={`group flex min-w-[118px] flex-1 items-center justify-center gap-2 rounded-lg border px-3 py-2 transition-colors duration-150 ${
                isActive
                  ? "border-cyan-500 bg-[#191c2b] text-white"
                  : "border-[#262838] bg-[#141622] text-[#cbd5e1] hover:border-[#383b52] hover:bg-[#181a28] hover:text-white"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div
                    className={`grid h-6 w-6 shrink-0 place-items-center rounded-md ${
                      isActive
                        ? "bg-cyan-500 text-black font-bold"
                        : "bg-white/10 text-cyan-300 group-hover:bg-white/20"
                    }`}
                  >
                    <Icon size={16} strokeWidth={2.4} />
                  </div>
                  <span className="text-[11px] font-bold tracking-tight">{tab.label}</span>
                </div>

                {tab.badge !== undefined && tab.badge > 0 && (
                  <span className="rounded-full bg-cyan-500/30 border border-cyan-400/50 px-2 py-0.5 text-[10px] font-bold text-cyan-200">
                    {tab.badge}
                  </span>
                )}
                {tab.alert && (
                  <span className="flex h-2 w-2 rounded-full bg-rose-400 animate-ping" />
                )}
              </div>
            </NavLink>
          );
        })}
      </div>

      {/* Main Tab Content View */}
      <div className="min-h-[500px]">
        {profileLoading ? (
          <div className="grid h-64 place-items-center rounded-2xl border border-[rgba(255,255,255,0.14)] bg-[#161228]">
            <div className="flex flex-col items-center gap-3">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
              <span className="text-xs font-semibold text-cyan-200">Loading user intelligence signals...</span>
            </div>
          </div>
        ) : profileError ? (
          <div className="rounded-2xl border border-rose-500/50 bg-rose-500/10 p-6 text-center text-rose-200">
            <ShieldAlert size={28} className="mx-auto mb-2 text-rose-400" />
            <h3 className="text-sm font-bold">Failed to load user intelligence for {principal}</h3>
            <p className="mt-1 text-xs text-[#cbd5e1]">{(profileError as Error).message}</p>
          </div>
        ) : (
          <Outlet context={{ principal, profile }} />
        )}
      </div>
    </div>
  );
}
