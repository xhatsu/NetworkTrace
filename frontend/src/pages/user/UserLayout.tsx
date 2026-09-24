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
  ArrowLeft,
  ChevronDown,
  GitCompareArrows,
  KeyRound,
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
import { episodeStatusClass, episodeStatusLabel, type Episode, type EpisodeResponse } from "../../components/EpisodePrimitives";

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
  const currentTab = location.pathname.split("/")[3] || "activity";

  // The User Intelligence profile comes from derived principal summaries; activity charts read metric buckets separately.
  const {
    data: fetchedProfile,
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
    queryKey: ["users-list-quick", filters],
    queryFn: () => api<any>(`/api/v1/principals?${queryString(filters, { limit: "200" })}`),
    staleTime: 60_000,
  });

  // The scoped TPS trend reads the worker's retained five-minute rollups.
  const { data: metricBuckets, isLoading: metricBucketsLoading } = useQuery({
    queryKey: ["user-metric-buckets", principal, filters],
    queryFn: () =>
      api<Array<{ bucket_start: number; requests: number }>>(`/api/v1/principals/${encodeURIComponent(principal)}/metrics?${queryString(filters, { bucket: "300" })}`),
    enabled: !!principal,
  });
  const tpsSeries = (metricBuckets || [])
    .map((row) => ({
      timestamp_ms: Number(row.bucket_start) * 1000,
      tps: Number(row.requests || 0) / 300,
    }))
    .filter((row: { timestamp_ms: number; tps: number }) => Number.isFinite(row.timestamp_ms) && row.timestamp_ms > 0);
  // Retained five-minute buckets can outlive the worker's one-minute profile view.
  const profile = fetchedProfile || (metricBuckets?.length ? {
    principal_name: principal,
    principal_type: "unknown",
    status: "Historical",
    learning_status: "learning",
    total_requests: metricBuckets.reduce((sum, row) => sum + Number(row.requests || 0), 0),
    hourly_activity: [],
  } : undefined);

  const { data: episodeData } = useQuery({
    queryKey: ["user-episodes", principal, filters],
    queryFn: () => api<EpisodeResponse>(`/api/v1/changes?${queryString(filters, { principal, limit: "100" })}`),
    enabled: !!principal,
    refetchInterval: 60_000,
  });
  const episodeRank: Record<Episode["state"], number> = { expected: 0, changed: 1, needs_attention: 2, critical: 3 };
  const activeEpisodes = (episodeData?.items || []).filter((episode) => episode.status !== "resolved");
  const behaviorState: Episode["state"] = activeEpisodes.reduce<Episode["state"]>((current, episode) => episodeRank[episode.state] > episodeRank[current] ? episode.state : current, "expected");

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
      id: "activity",
      label: t("Activity"),
      question: t("How has traffic & performance changed?"),
      path: `/users/${encodeURIComponent(principal)}/activity`,
      icon: Activity,
    },
    {
      id: "changes",
      label: t("Changes"),
      question: t("What is different from normal behavior?"),
      path: `/users/${encodeURIComponent(principal)}/changes`,
      icon: GitCompareArrows,
      badge: episodeData?.total || profile?.changes?.length || profile?.recent_changes || 0,
    },
  ];

  const score = profile?.behavior_score ?? 0;
  const principalType = String(profile?.principal_type || "unknown");
  const isHumanPrincipal = principalType === "human";
  const principalRoleLabel = isHumanPrincipal
    ? t("User identity", "User identity")
    : principalType === "unknown"
      ? t("Observed principal", "Principal quan sát được")
      : t("Observed credential", "Credential quan sát được");

  return (
    <div className="mx-auto max-w-[1720px] px-3 py-3 md:px-6">
      {/* Compressed Grafana-style User Header */}
      <div className="panel mb-3 p-3">
        {/* Row 1: Back link, Identity, Badges, and Switcher */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2 sm:gap-2.5">
            <button
              onClick={() => nav("/users")}
              className="inline-flex items-center gap-1 border border-[#2a2d30] bg-[#181b1f] px-2 py-0.5 text-[11px] font-semibold text-[#a7a9ab] transition hover:border-[#5794f2]/50 hover:text-white"
              title={t("Back to User Directory")}
            >
              <ArrowLeft size={12} />
              <span>{t("Users")}</span>
            </button>

            <div className="flex items-center gap-2">
              <div className="grid h-6 w-6 place-items-center rounded-[2px] border border-[#b877d9]/40 bg-[#b877d9]/10 text-[#d9b4ea]">
                {isHumanPrincipal ? <User size={13} strokeWidth={2} /> : <KeyRound size={13} strokeWidth={2} />}
              </div>
              <h1 className="font-mono text-base font-bold text-white tracking-tight">
                {principal}
              </h1>
            </div>

            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className="text-[#7b7d80]">•</span>
              <select
                aria-label={t("Principal type")}
                value={profile?.principal_type || "service_account"}
                onChange={(e) => updateTypeMutation.mutate(e.target.value)}
                className="toolbar-control cursor-pointer h-6 px-1.5 py-0 text-[10px] font-medium"
              >
                <option value="service_account">{t("Service Account")}</option>
                <option value="human">{t("Human User")}</option>
                <option value="system_account">{t("System Account")}</option>
                <option value="shared_credential">{t("Shared Credential")}</option>
                <option value="integration_account">{t("Integration Account")}</option>
                <option value="unknown">{t("Unknown")}</option>
              </select>
              <span className="text-[#7b7d80]">·</span>
              <span className="text-[10px] text-[#a7a9ab]">
                <strong className="text-[#d8d9da]">{profile?.environment || "—"}</strong>
              </span>
            </div>

            {/* Badges: Active, Baseline, Behavior State */}
            <div className="flex flex-wrap items-center gap-1.5 text-[9.5px]">
              <span
                className={`inline-flex items-center gap-1 border px-1.5 py-0.5 font-semibold ${
                  profile?.status === "Active"
                    ? "border-[#73bf69]/50 bg-[#73bf69]/10 text-[#73bf69]"
                    : "border-[#7b7d80]/50 bg-[#181b1f] text-[#a7a9ab]"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${profile?.status === "Active" ? "bg-[#73bf69]" : "bg-[#7b7d80]"}`} />
                {profile?.status || "Active"}
              </span>

              <span className="inline-flex items-center gap-1 border border-[#b877d9]/40 bg-[#b877d9]/10 px-1.5 py-0.5 font-semibold text-[#b877d9]">
                <Sparkles size={10} className="text-[#b877d9]" />
                {profile?.learning_status === "learning" ? t("Learning Baseline") : profile?.learning_status ? t("Established Baseline") : t("Baseline unavailable")}
              </span>

              <span className={`inline-flex items-center gap-1 border px-1.5 py-0.5 font-semibold ${episodeStatusClass(behaviorState)}`}>
                {behaviorState === "critical" || behaviorState === "needs_attention" ? <ShieldAlert size={10} /> : <Shield size={10} />}
                {activeEpisodes.length ? episodeStatusLabel(behaviorState, t) : t("Normal")}
                <span className="font-mono opacity-70">({score})</span>
              </span>
            </div>
          </div>

          {/* Quick User Switcher dropdown */}
          <div className="relative">
            <button
              onClick={() => setSwitcherOpen(!switcherOpen)}
              className="toolbar-control flex items-center gap-1.5 h-6 px-2 py-0 text-[11px] font-semibold text-[#d8d9da] hover:text-white"
            >
              <Users size={12} className="text-[#5794f2]" />
              <span>{t("Switch")}</span>
              <ChevronDown size={11} className="text-[#7b7d80]" />
            </button>

            {switcherOpen && (
              <div className="absolute right-0 top-full z-50 mt-1.5 w-80 rounded-[2px] border border-[#2e3247] bg-[#161825] p-2.5 shadow-xl">
                <div className="relative mb-2">
                  <Search className="absolute left-2.5 top-2.5 text-[#94a3b8]" size={13} />
                  <input
                    type="text"
                    autoFocus
                    placeholder={t("Filter users...")}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full border border-[#2e3247] bg-[#0e1019] pl-8 pr-3 py-1.5 text-xs text-white placeholder:text-[#94a3b8] focus:border-[#5794f2] focus:outline-none"
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
                      className={`flex w-full items-center justify-between px-2 py-1 text-xs transition ${
                        u.principal_name === principal
                          ? "bg-[#5794f2]/20 border border-[#5794f2]/40 text-white font-bold"
                          : "text-[#cbd5e1] hover:bg-[#202436] hover:text-white"
                      }`}
                    >
                      <div className="flex items-center gap-2 truncate">
                        <div className="grid h-5 w-5 place-items-center rounded-sm bg-white/10 text-cyan-300 text-[10px]">
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

        {/* Row 2: Compact metrics ribbon and Activity / Changes tabs */}
        <div className="mt-2 flex flex-wrap items-center justify-between gap-y-2 border-t border-[#2a2d30] pt-2 text-[11px]">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-[#a7a9ab]">
            <span>
              <span className="text-[#7b7d80] text-[10px] uppercase font-sans mr-1">{t("Requests")}</span>
              <strong className="text-[#d8d9da] font-semibold tabular-nums">{(profile?.total_requests || 0).toLocaleString()}</strong>
            </span>
            <span className="text-[#303236]">|</span>
            <span>
              <span className="text-[#7b7d80] text-[10px] uppercase font-sans mr-1">{t("Services")}</span>
              <strong className="text-[#5794f2] font-semibold tabular-nums">{profile?.unique_targets ?? profile?.current?.targets?.length ?? 0}</strong>
            </span>
            <span className="text-[#303236]">|</span>
            <span>
              <span className="text-[#7b7d80] text-[10px] uppercase font-sans mr-1">APIs</span>
              <strong className="text-[#73bf69] font-semibold tabular-nums">{profile?.unique_operations ?? profile?.current?.operations?.length ?? 0}</strong>
            </span>
            <span className="text-[#303236]">|</span>
            <span>
              <span className="text-[#7b7d80] text-[10px] uppercase font-sans mr-1">{t("Callers")}</span>
              <strong className="text-[#b877d9] font-semibold tabular-nums">{profile?.unique_callers ?? profile?.current?.callers?.length ?? 0}</strong>
            </span>
            <span className="text-[#303236]">|</span>
            <span>
              <span className="text-[#7b7d80] text-[10px] uppercase font-sans mr-1">IPs</span>
              <strong className="text-[#ff9830] font-semibold tabular-nums">{profile?.unique_sources ?? profile?.current?.sources?.length ?? 0}</strong>
            </span>
            <span className="text-[#303236]">|</span>
            <span>
              <span className="text-[#7b7d80] text-[10px] uppercase font-sans mr-1">{t("Window")}</span>
              <span className="text-[#d8d9da] text-[10px]">{profile?.typical_active_window || t("All Hours")}</span>
            </span>
          </div>

          {/* Navigation tabs */}
          <div className="flex items-center gap-1.5">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = currentTab === tab.id;
              return (
                <NavLink
                  key={tab.id}
                  to={tab.path}
                  className={`inline-flex items-center gap-1.5 border px-2.5 py-1 text-[11px] font-medium transition ${
                    isActive
                      ? "border-[#5794f2] bg-[#181b1f] text-white font-semibold"
                      : "border-[#2a2d30] bg-[#111217] text-[#a7a9ab] hover:border-[#34373b] hover:bg-[#181b1f] hover:text-[#d8d9da]"
                  }`}
                >
                  <Icon size={12} className={isActive ? "text-[#5794f2]" : "text-[#7b7d80]"} />
                  <span>{tab.label}</span>
                  {tab.badge !== undefined && tab.badge > 0 && (
                    <span className="rounded-[2px] bg-[#5794f2]/20 border border-[#5794f2]/40 px-1 py-0 text-[9px] font-mono text-[#5794f2]">
                      {tab.badge}
                    </span>
                  )}
                </NavLink>
              );
            })}
          </div>
        </div>
      </div>

      {/* Scoped TPS panel for non-overview workspace tabs */}
      {currentTab === "changes" && (
        <Panel
          title={t("TPS")}
          subtitle={t("Observed user throughput over the selected window")}
          className="mb-4"
          action={<span className="font-mono text-[11px] text-[#5794f2]">{n(tpsSeries[tpsSeries.length - 1]?.tps || 0, 2)} TPS</span>}
        >
          <TpsLineChart data={tpsSeries} />
        </Panel>
      )}

      {/* Main Tab Content View */}
      <div className="min-h-[500px]">
        {profileLoading || (profileError && metricBucketsLoading) ? (
          <div className="grid h-64 place-items-center rounded-[3px] border border-[#2a2d30] bg-[#111217]">
            <div className="flex flex-col items-center gap-3">
              <div className="h-7 w-7 animate-spin rounded-full border-2 border-[#5794f2] border-t-transparent" />
              <span className="text-xs font-medium text-[#a7a9ab]">{t("Loading user intelligence signals...")}</span>
            </div>
          </div>
        ) : profileError && !profile ? (
          <div className="rounded-[3px] border border-red-500/50 bg-red-500/10 p-6 text-center text-red-200">
            <ShieldAlert size={26} className="mx-auto mb-2 text-[#f2495c]" />
            <h3 className="text-sm font-semibold text-[#d8d9da]">Failed to load user intelligence for {principal}</h3>
            <p className="mt-1 text-xs text-[#a7a9ab]">{(profileError as Error).message}</p>
          </div>
        ) : (
          <Outlet context={{ principal, profile }} />
        )}
      </div>
    </div>
  );
}
