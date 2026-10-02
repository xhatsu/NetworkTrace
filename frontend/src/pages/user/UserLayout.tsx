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
import { entityPath } from "../../entityRoutes";
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
  const episodeRank: Record<Episode["state"], number> = { expected: 0, changed: 1, watch: 2, needs_attention: 3, critical: 4 };
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
      path: entityPath({ kind: "user", principal, tab: "activity" }),
      icon: Activity,
    },
    {
      id: "changes",
      label: t("Changes"),
      question: t("What is different from normal behavior?"),
      path: entityPath({ kind: "user", principal, tab: "changes" }),
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
              className="inline-flex items-center gap-1 border border-line bg-surface bg-surface-2 px-2 py-0.5 text-[11px] font-semibold text-muted transition hover:border-accent hover:text-ink"
              title={t("Back to User Directory")}
            >
              <ArrowLeft size={12} />
              <span>{t("Users")}</span>
            </button>

            <div className="flex items-center gap-2">
              <div className="grid h-6 w-6 place-items-center rounded-[2px] border border-entity-user/40 bg-entity-user/10 text-entity-user">
                {isHumanPrincipal ? <User size={13} strokeWidth={2} /> : <KeyRound size={13} strokeWidth={2} />}
              </div>
              <h1 className="font-mono text-base font-bold text-ink tracking-tight">
                {principal}
              </h1>
            </div>

            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className="text-muted">•</span>
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
              <span className="text-muted">·</span>
              <span className="text-[10px] text-muted">
                <strong className="text-ink">{profile?.environment || "—"}</strong>
              </span>
            </div>

            {/* Badges: Active, Baseline, Behavior State */}
            <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
              <span
                className={`inline-flex items-center gap-1 border px-1.5 py-0.5 font-semibold ${
                  profile?.status === "Active"
                    ? "border-good/50 bg-good/10 text-good"
                    : "border-line bg-surface-2 text-muted"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${profile?.status === "Active" ? "bg-good" : "bg-muted"}`} />
                {profile?.status || "Active"}
              </span>

              <span className="inline-flex items-center gap-1 border border-entity-user/40 bg-entity-user/10 px-1.5 py-0.5 font-semibold text-entity-user">
                <Sparkles size={10} className="text-entity-user" />
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
              className="toolbar-control flex items-center gap-1.5 h-6 px-2 py-0 text-[11px] font-semibold text-ink hover:text-ink"
            >
              <Users size={12} className="text-accent" />
              <span>{t("Switch")}</span>
              <ChevronDown size={11} className="text-muted" />
            </button>

            {switcherOpen && (
              <div className="absolute right-0 top-full z-50 mt-1.5 w-80 rounded-[2px] border border-line bg-surface p-2.5 shadow-xl">
                <div className="relative mb-2">
                  <Search className="absolute left-2.5 top-2.5 text-faint" size={13} />
                  <input
                    type="text"
                    autoFocus
                    placeholder={t("Filter users...")}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full border border-line bg-surface pl-8 pr-3 py-1.5 text-xs text-white placeholder:text-muted focus:border-accent focus:outline-none"
                  />
                </div>
                <div className="max-h-60 overflow-y-auto space-y-1 scrollbar">
                  {filteredUsers.slice(0, 30).map((u) => (
                    <button
                      key={u.principal_name}
                      onClick={() => {
                        setSwitcherOpen(false);
                        setSearchQuery("");
                        nav(entityPath({ kind: "user", principal: u.principal_name, tab: currentTab === "changes" ? "changes" : "activity" }));
                      }}
                      className={`flex w-full items-center justify-between px-2 py-1 text-xs transition ${
                        u.principal_name === principal
                          ? "bg-accent-soft border border-accent/40 text-white font-bold"
                          : "text-muted hover:bg-hover hover:text-ink"
                      }`}
                    >
                      <div className="flex items-center gap-2 truncate">
                        <div className="grid h-5 w-5 place-items-center rounded-sm bg-surface-2 text-entity-api text-[10px]">
                          {u.principal_name.slice(0, 2).toUpperCase()}
                        </div>
                        <span className="truncate font-mono">{u.principal_name}</span>
                      </div>
                      <span
                        className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          (u.behavior_score || 0) >= 60
                            ? "bg-bad/20 text-bad border border-bad/40"
                            : (u.behavior_score || 0) >= 25
                            ? "bg-warn/20 text-warn border border-warn/40"
                            : "bg-good/20 text-good border border-good/40"
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
        <div className="mt-2 flex flex-wrap items-center justify-between gap-y-2 border-t border-line pt-2 text-[11px]">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
            <span>
              <span className="text-muted text-[10px] uppercase font-sans mr-1">{t("Requests")}</span>
              <strong className="text-ink font-semibold tabular-nums">{(profile?.total_requests || 0).toLocaleString()}</strong>
            </span>
            <span className="text-muted">|</span>
            <span>
              <span className="text-muted text-[10px] uppercase font-sans mr-1">{t("Services")}</span>
              <strong className="text-accent font-semibold tabular-nums">{profile?.unique_targets ?? profile?.current?.targets?.length ?? 0}</strong>
            </span>
            <span className="text-muted">|</span>
            <span>
              <span className="text-muted text-[10px] uppercase font-sans mr-1">APIs</span>
              <strong className="text-good font-semibold tabular-nums">{profile?.unique_operations ?? profile?.current?.operations?.length ?? 0}</strong>
            </span>
            <span className="text-muted">|</span>
            <span>
              <span className="text-muted text-[10px] uppercase font-sans mr-1">{t("Callers")}</span>
              <strong className="text-entity-user font-semibold tabular-nums">{profile?.unique_callers ?? profile?.current?.callers?.length ?? 0}</strong>
            </span>
            <span className="text-muted">|</span>
            <span>
              <span className="text-muted text-[10px] uppercase font-sans mr-1">IPs</span>
              <strong className="text-warn font-semibold tabular-nums">{profile?.unique_sources ?? profile?.current?.sources?.length ?? 0}</strong>
            </span>
            <span className="text-muted">|</span>
            <span>
              <span className="text-muted text-[10px] uppercase font-sans mr-1">{t("Window")}</span>
              <span className="text-ink text-[10px]">{profile?.typical_active_window || t("All Hours")}</span>
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
                      ? "border-accent bg-accent-soft bg-surface-2 text-ink font-semibold"
                      : "border-line bg-surface text-muted hover:border-line-strong hover:bg-hover hover:text-ink"
                  }`}
                >
                  <Icon size={12} className={isActive ? "text-accent" : "text-muted text-muted"} />
                  <span>{tab.label}</span>
                  {tab.badge !== undefined && tab.badge > 0 && (
                    <span className="rounded-[2px] bg-accent-soft border border-accent/40 px-1 py-0 text-[10px] font-mono text-accent">
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
          action={<span className="font-mono text-[11px] text-accent">{n(tpsSeries[tpsSeries.length - 1]?.tps || 0, 2)} TPS</span>}
        >
          <TpsLineChart data={tpsSeries} />
        </Panel>
      )}

      {/* Main Tab Content View */}
      <div className="min-h-[500px]">
        {profileLoading || (profileError && metricBucketsLoading) ? (
          <div className="grid h-64 place-items-center rounded-[3px] border border-line bg-surface">
            <div className="flex flex-col items-center gap-3">
              <div className="h-7 w-7 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <span className="text-xs font-medium text-muted">{t("Loading user intelligence signals...")}</span>
            </div>
          </div>
        ) : profileError && !profile ? (
          <div className="rounded-[3px] border border-bad/50 bg-bad/10 p-6 text-center text-bad">
            <ShieldAlert size={26} className="mx-auto mb-2 text-bad" />
            <h3 className="text-sm font-semibold text-ink">Failed to load user intelligence for {principal}</h3>
            <p className="mt-1 text-xs text-muted">{(profileError as Error).message}</p>
          </div>
        ) : (
          <Outlet context={{ principal, profile }} />
        )}
      </div>
    </div>
  );
}
