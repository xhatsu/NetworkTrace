import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Area,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  BarChart,
  Bar,
} from "recharts";
import {
  Activity,
  AlertOctagon,
  ArrowRight,
  Clock,
  ExternalLink,
  Layers,
  Radio,
  RefreshCw,
  Search,
  Share2,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  User,
  Users,
} from "lucide-react";
import { api, queryString } from "../api";
import {
  ErrorState,
  Loading,
  MetricCard,
  Page,
  Panel,
  age,
  chartTooltip,
  n,
  pct,
} from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import type { SeriesPoint, Summary } from "../types";

type UserSummary = {
  observed_principals: number;
  active_principals: number;
  new_principals_today: number;
  principals_with_changes: number;
  dormant_reactivated: number;
  new_service_relationships: number;
  new_caller_relationships: number;
};

type UserItem = {
  id: number;
  principal_name: string;
  principal_type: string;
  first_seen: number;
  last_seen: number;
  total_requests: number;
  unique_callers: number;
  unique_sources: number;
  unique_targets: number;
  unique_operations: number;
  status: string;
  behavior_score: number;
  behavior_level: "High" | "Medium" | "Low";
  learning_status: string;
  recent_changes?: number;
};

type UserChangeEvent = {
  id: number;
  principal_name: string;
  change_type: string;
  caller_service?: string;
  target_service?: string;
  operation?: string;
  source_ip?: string;
  severity: string;
  score: number;
  detected_at: number;
  status: string;
  explanation?: string;
  reason?: Record<string, any>;
};

type UserIncident = {
  incident_id: string;
  principal_name: string;
  score: number;
  priority: string;
  started_at: number;
  last_seen_at: number;
  status: string;
  triggers?: string[];
  relationship_chain?: string[];
};

export function OverviewPage() {
  const { filters, setFilter } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const qs = queryString(filters);
  const [userSearch, setUserSearch] = useState("");
  const [riskFilter, setRiskFilter] = useState<"all" | "high" | "med" | "active">("all");

  // 1. User Summary KPIs
  const userSummaryQuery = useQuery({
    queryKey: ["users-summary", qs],
    queryFn: () => api<UserSummary>(`/api/v1/users/summary?${qs}`),
    refetchInterval: 60000,
  });

  // 2. User Directory List
  const usersQuery = useQuery({
    queryKey: ["users-list", qs],
    queryFn: () => api<{ items: UserItem[]; count: number }>(`/api/v1/users?limit=100&sort=most_active&${qs}`),
    refetchInterval: 60000,
  });

  // 3. User Intelligence Analytics
  const userAnalyticsQuery = useQuery({
    queryKey: ["user-analytics", qs],
    queryFn: () => api<any>(`/api/v1/user-analytics?${qs}`),
    refetchInterval: 60000,
  });

  // 4. Recent Behavioral Change Events Feed
  const userChangesQuery = useQuery({
    queryKey: ["user-changes-feed", qs],
    queryFn: () => api<{ items: UserChangeEvent[]; count: number }>(`/api/v1/user-changes?limit=8&${qs}`),
    refetchInterval: 60000,
  });

  // 5. Active User Incidents Queue
  const incidentsQuery = useQuery({
    queryKey: ["user-incidents-feed", qs],
    queryFn: () => api<{ items: UserIncident[]; count?: number }>(`/api/v1/incidents?limit=6&${qs}`),
    refetchInterval: 60000,
  });

  // 6. Time-Series Traffic & Error Velocity
  const seriesQuery = useQuery({
    queryKey: ["series", qs],
    queryFn: () => api<{ items: SeriesPoint[] }>(`/api/v1/dashboard/series?${qs}`),
    refetchInterval: 60000,
  });

  // 7. Overall System Volume Context
  const summaryQuery = useQuery({
    queryKey: ["summary", qs],
    queryFn: () => api<Summary>(`/api/v1/dashboard/summary?${qs}`),
    refetchInterval: 60000,
  });

  const isLoading = userSummaryQuery.isLoading || usersQuery.isLoading;
  const isError = userSummaryQuery.error || usersQuery.error;

  if (isLoading) {
    return (
      <Page
        eyebrow={t("User Intelligence")}
        title={t("User Behavioral Observability Dashboard")}
        description={t("Executive identity monitoring: real-time account behavior, baseline deviations, novel touchpoints, and active triage.")}
      >
        <Loading />
      </Page>
    );
  }

  if (isError) {
    return (
      <Page
        eyebrow={t("User Intelligence")}
        title={t("User Behavioral Observability Dashboard")}
        description=""
      >
        <ErrorState
          message={(userSummaryQuery.error || usersQuery.error)?.message || "Unable to load identity metrics."}
        />
      </Page>
    );
  }

  const uSum = userSummaryQuery.data || {
    observed_principals: 0,
    active_principals: 0,
    new_principals_today: 0,
    principals_with_changes: 0,
    dormant_reactivated: 0,
    new_service_relationships: 0,
    new_caller_relationships: 0,
  };

  const allUsers = usersQuery.data?.items || [];
  const points = seriesQuery.data?.items || [];
  const changes = userChangesQuery.data?.items || [];
  const incidents = incidentsQuery.data?.items || [];
  const analytics = userAnalyticsQuery.data || {};
  const s = summaryQuery.data;

  // Cohort Computations
  const highRiskUsers = allUsers.filter((u) => (u.behavior_score || 0) >= 60);
  const medRiskUsers = allUsers.filter((u) => (u.behavior_score || 0) >= 25 && (u.behavior_score || 0) < 60);
  const lowRiskUsers = allUsers.filter((u) => (u.behavior_score || 0) < 25);
  const activeUsers = allUsers.filter((u) => u.status === "Active");

  // Filtered Users Table
  const filteredUsers = allUsers.filter((u) => {
    if (userSearch) {
      const q = userSearch.toLowerCase();
      const matchName = u.principal_name.toLowerCase().includes(q);
      const matchType = (u.principal_type || "").toLowerCase().includes(q);
      if (!matchName && !matchType) return false;
    }
    if (riskFilter === "high") return (u.behavior_score || 0) >= 60;
    if (riskFilter === "med") return (u.behavior_score || 0) >= 25 && (u.behavior_score || 0) < 60;
    if (riskFilter === "active") return u.status === "Active";
    return true;
  });

  const cohortData = [
    { name: t("High Risk (≥60)"), count: highRiskUsers.length, fill: "#ff1744" },
    { name: t("Medium Risk (25-59)"), count: medRiskUsers.length, fill: "#ffab00" },
    { name: t("Low Risk (<25)"), count: lowRiskUsers.length, fill: "#00e676" },
    { name: t("Actively Transacting"), count: activeUsers.length, fill: "#00f0ff" },
  ];

  return (
    <Page
      eyebrow={t("Identity & Credential Intelligence")}
      title={t("User Behavioral Observability Dashboard")}
      description={t("Executive identity monitoring: real-time account behavior, baseline deviations, novel touchpoints, and active triage.")}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-mono font-bold text-emerald-300">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            <span>{t("Behavioral Engine Active")}</span>
          </div>
          <button
            onClick={() => nav("/users")}
            className="btn-cyan text-xs"
          >
            <Users size={14} />
            <span>{t("User Directory")} ({uSum.observed_principals})</span>
            <ArrowRight size={12} />
          </button>
        </div>
      }
    >
      {/* 8 Primary User Signal Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <MetricCard
          label={t("Tracked Users")}
          value={n(uSum.observed_principals, 0)}
          detail={t("Total distinct identities")}
          accent="cyan"
        />
        <MetricCard
          label={t("Active Accounts")}
          value={n(uSum.active_principals, 0)}
          detail={t("Transacting in 5m window")}
          accent="emerald"
        />
        <MetricCard
          label={t("High-Risk Users")}
          value={String(highRiskUsers.length)}
          detail={t("Score ≥ 60/100")}
          tone={highRiskUsers.length > 0 ? "bad" : "normal"}
          accent="rose"
        />
        <MetricCard
          label={t("Medium-Risk")}
          value={String(medRiskUsers.length)}
          detail={t("Score 25–59/100")}
          accent="amber"
        />
        <MetricCard
          label={t("Baseline Drift")}
          value={n(uSum.principals_with_changes, 0)}
          detail={t("Users violating baselines")}
          tone={uSum.principals_with_changes > 0 ? "bad" : "good"}
          accent="violet"
        />
        <MetricCard
          label={t("New Target Edges")}
          value={n(uSum.new_service_relationships, 0)}
          detail={t("Novel target services accessed")}
          accent="indigo"
        />
        <MetricCard
          label={t("New Caller Paths")}
          value={n(uSum.new_caller_relationships, 0)}
          detail={t("Unprecedented caller paths")}
          accent="sky"
        />
        <MetricCard
          label={t("Active Incidents")}
          value={String(incidents.length)}
          detail={t("Multi-signal user investigations")}
          tone={incidents.length > 0 ? "bad" : "good"}
          accent="rose"
        />
      </div>

      {/* User Quick Search & Filter Toolbar */}
      <div className="mt-4 rounded-xl border border-[#262838] bg-[#141622] p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-1 items-center gap-2 min-w-[260px] max-w-md">
            <div className="relative w-full">
              <Search className="absolute left-3 top-2.5 text-[#94a3b8]" size={14} />
              <input
                type="text"
                placeholder={t("Search user account or credential...")}
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                className="w-full rounded-lg border border-[#262838] bg-[#0c0d14] pl-9 pr-3 py-1.5 text-xs text-white placeholder:text-[#94a3b8] focus:border-cyan-400 focus:outline-none"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-[#94a3b8] text-[11px] uppercase font-bold tracking-wider">{t("Cohort Filter:")}</span>
            {[
              { key: "all", label: `${t("All Users")} (${allUsers.length})` },
              { key: "high", label: `${t("High Risk")} (${highRiskUsers.length})` },
              { key: "med", label: `${t("Medium Risk")} (${medRiskUsers.length})` },
              { key: "active", label: `${t("Active Only")} (${activeUsers.length})` },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setRiskFilter(tab.key as any)}
                className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition ${
                  riskFilter === tab.key
                    ? "bg-cyan-500/20 border border-cyan-500/50 text-cyan-300 font-bold"
                    : "border border-[#262838] bg-[#1a1d2c] text-[#cbd5e1] hover:border-[#3d425b] hover:text-white"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Central Visualizations: User Ingress Velocity vs Error Dynamics & Risk Cohort Split */}
      <div className="mt-4 grid gap-4 lg:grid-cols-12">
        {/* Left 7 Cols: Identity Traffic Velocity & Error Dynamics */}
        <Panel
          title={t("Identity Traffic Velocity & Error Rates")}
          subtitle={t("60s bucketed transaction throughput vs HTTP failure proportions")}
          className="lg:col-span-7"
          action={
            <div className="flex items-center gap-2 text-xs font-mono text-[#94a3b8]">
              <span>TPS: <strong className="text-cyan-300 font-bold">{n(s?.observed_rps || 0, 1)}</strong></span>
              <span>•</span>
              <span>5xx: <strong className="text-rose-400 font-bold">{pct(s?.http_5xx_rate || 0)}</strong></span>
            </div>
          }
        >
          <div className="h-[290px] p-3">
            <ResponsiveContainer>
              <ComposedChart data={points}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis
                  dataKey="timestamp_ms"
                  tickFormatter={(v) => formatTime(v, filters.timezone)}
                  minTickGap={50}
                  stroke="#766e92"
                />
                <YAxis
                  yAxisId="left"
                  stroke="#766e92"
                  width={45}
                  unit=" tps"
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="#f43f5e"
                  width={45}
                  tickFormatter={(v) => `${Math.round(v * 100)}%`}
                />
                <Tooltip
                  {...chartTooltip}
                  formatter={(val: any, name: any) => {
                    if (name === "5xx Failure Rate" || String(name).includes("5xx")) {
                      return [`${(Number(val || 0) * 100).toFixed(2)}%`, name];
                    }
                    return [`${Number(val || 0).toFixed(2)} tps`, name];
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Area
                  yAxisId="left"
                  type="monotone"
                  dataKey="rps"
                  name={t("Observed Throughput (TPS)")}
                  stroke="#00f0ff"
                  fill="#00f0ff"
                  fillOpacity={0.12}
                  strokeWidth={2}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="baseline_rps"
                  name={t("Historical Baseline TPS")}
                  stroke="#a78bfa"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                  dot={false}
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="http_5xx_rate"
                  name={t("5xx Failure Rate")}
                  stroke="#f43f5e"
                  strokeWidth={2}
                  dot={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        {/* Right 5 Cols: Identity Cohort Risk Breakdown */}
        <Panel
          title={t("Identity Risk & Status Distribution")}
          subtitle={t("Account distribution across behavioral risk levels and activity states")}
          className="lg:col-span-5"
        >
          <div className="h-[290px] p-3">
            <ResponsiveContainer>
              <BarChart data={cohortData} layout="vertical" margin={{ left: 20, right: 20, top: 10, bottom: 10 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                <XAxis type="number" stroke="#766e92" />
                <YAxis
                  type="category"
                  dataKey="name"
                  stroke="#766e92"
                  width={140}
                  tick={{ fill: "#cbd5e1", fontSize: 11, fontWeight: 500 }}
                />
                <Tooltip {...chartTooltip} />
                <Bar dataKey="count" name={t("Principal Identity")} radius={[0, 4, 4, 0]}>
                  {cohortData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      {/* Actionable User Tables: Riskiest Users vs Shared Credentials */}
      <div className="mt-4 grid gap-4 lg:grid-cols-12">
        {/* Left 7 Cols: Top Riskiest / Most Active User Accounts */}
        <Panel
          title={t("Prioritized User & Service Accounts")}
          subtitle={t("Identities sorted by behavioral risk score, active baseline deviations, and request volume")}
          className="lg:col-span-7"
          action={
            <button
              onClick={() => nav("/users")}
              className="text-xs font-semibold text-cyan-300 hover:text-white flex items-center gap-1"
            >
              <span>{t("View full directory")} ({allUsers.length})</span>
              <ArrowRight size={12} />
            </button>
          }
        >
          <div className="overflow-x-auto scrollbar max-h-[380px]">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#262838] bg-[#10121a]">
                  <th className="table-head px-4 py-2.5">{t("Principal Identity")}</th>
                  <th className="table-head px-3 py-2.5">{t("Type")}</th>
                  <th className="table-head px-3 py-2.5">{t("Risk Score")}</th>
                  <th className="table-head px-3 py-2.5 text-right">{t("Volume")}</th>
                  <th className="table-head px-3 py-2.5 text-right">{t("Scope")}</th>
                  <th className="table-head px-4 py-2.5 text-right">{t("Actions")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.slice(0, 10).map((u) => {
                  const score = u.behavior_score || 0;
                  const isHigh = score >= 60;
                  const isMed = score >= 25 && score < 60;
                  return (
                    <tr
                      key={u.principal_name}
                      className="border-b border-[#1f2230] hover:bg-[#181b28] transition-colors cursor-pointer"
                      onClick={() => nav(`/users/${encodeURIComponent(u.principal_name)}/overview`)}
                    >
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="grid h-6 w-6 place-items-center rounded-md bg-[#222536] text-cyan-300 text-[10px] font-bold">
                            {u.principal_name.slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <div className="font-mono font-bold text-white truncate max-w-[180px]" title={u.principal_name}>
                              {u.principal_name}
                            </div>
                            <div className="flex items-center gap-1.5 text-[10px] text-[#94a3b8]">
                              <span className={`h-1.5 w-1.5 rounded-full ${u.status === "Active" ? "bg-emerald-400" : "bg-slate-500"}`} />
                              <span>{t(u.status)}</span>
                            </div>
                          </div>
                        </div>
                      </td>

                      <td className="px-3 py-2.5 text-[#cbd5e1] font-mono text-[11px]">
                        {t(u.principal_type || "service_account")}
                      </td>

                      <td className="px-3 py-2.5">
                        <span
                          className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-bold border ${
                            isHigh
                              ? "border-rose-500/50 bg-rose-500/15 text-rose-300"
                              : isMed
                              ? "border-amber-500/50 bg-amber-500/15 text-amber-300"
                              : "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
                          }`}
                        >
                          {isHigh ? <ShieldAlert size={11} /> : <Shield size={11} />}
                          <span>{score}/100</span>
                        </span>
                      </td>

                      <td className="px-3 py-2.5 text-right font-mono font-bold text-white">
                        {(u.total_requests || 0).toLocaleString()}
                      </td>

                      <td className="px-3 py-2.5 text-right font-mono text-[11px] text-[#cbd5e1]">
                        <span className="text-cyan-300">{u.unique_targets || 0} tgts</span>
                        <span className="text-[#94a3b8]"> · </span>
                        <span>{u.unique_sources || 0} IPs</span>
                      </td>

                      <td className="px-4 py-2.5 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            nav(`/users/${encodeURIComponent(u.principal_name)}/overview`);
                          }}
                          className="btn text-[11px] py-1 px-2.5 hover:border-cyan-400 text-cyan-300"
                        >
                          <span>{t("Inspect")}</span>
                          <ExternalLink size={10} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* Right 5 Cols: Shared Credentials & High Fan-Out Ingress */}
        <Panel
          title={t("Shared Credentials & Fan-Out Ingress")}
          subtitle={t("Identities invoking microservices through multiple distinct callers or distributed IPs")}
          className="lg:col-span-5"
          action={
            <button
              onClick={() => nav("/user-graph")}
              className="text-xs font-semibold text-violet-300 hover:text-white flex items-center gap-1"
            >
              <span>{t("Explore Graph")}</span>
              <ArrowRight size={12} />
            </button>
          }
        >
          <div className="overflow-x-auto scrollbar max-h-[380px]">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#262838] bg-[#10121a]">
                  <th className="table-head px-4 py-2.5">{t("Credential")}</th>
                  <th className="table-head px-3 py-2.5 text-right">{t("Callers")}</th>
                  <th className="table-head px-3 py-2.5 text-right">{t("Volume")}</th>
                  <th className="table-head px-4 py-2.5 text-right">{t("Status")}</th>
                </tr>
              </thead>
              <tbody>
                {(analytics.shared_credentials || []).slice(0, 10).map((sc: any) => (
                  <tr
                    key={sc.principal_name}
                    className="border-b border-[#1f2230] hover:bg-[#181b28] transition-colors cursor-pointer"
                    onClick={() => nav(`/users/${encodeURIComponent(sc.principal_name)}/topology`)}
                  >
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <Share2 size={13} className="text-violet-400 shrink-0" />
                        <span className="font-mono font-bold text-white truncate max-w-[150px]" title={sc.principal_name}>
                          {sc.principal_name}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono font-bold text-amber-300">
                      {sc.callers} {t("Callers")}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#cbd5e1]">
                      {(sc.requests || 0).toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className="rounded border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                        {t("Multi-Caller")}
                      </span>
                    </td>
                  </tr>
                ))}
                {(!analytics.shared_credentials || analytics.shared_credentials.length === 0) && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-xs text-[#94a3b8]">
                      {t("No shared credential anomalies detected in current window.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* Latest Behavioral Change Events Stream */}
      <Panel
        title={t("Live Behavioral Change Events Stream")}
        subtitle={t("Real-time baseline deviations: novel services, unprecedented callers, foreign IPs, and method anomalies")}
        className="mt-4"
        action={
          <button
            onClick={() => nav("/user-changes")}
            className="text-xs font-semibold text-cyan-300 hover:text-white flex items-center gap-1"
          >
            <span>{t("View all change events")}</span>
            <ArrowRight size={12} />
          </button>
        }
      >
        <div className="overflow-x-auto scrollbar">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#262838] bg-[#10121a]">
                <th className="table-head px-4 py-2.5">{t("Account / Principal")}</th>
                <th className="table-head px-3 py-2.5">{t("Deviation Type")}</th>
                <th className="table-head px-3 py-2.5">{t("Observed Touchpoint")}</th>
                <th className="table-head px-3 py-2.5">{t("Score")}</th>
                <th className="table-head px-3 py-2.5">{t("Detected")}</th>
                <th className="table-head px-4 py-2.5 text-right">{t("Actions")}</th>
              </tr>
            </thead>
            <tbody>
              {changes.slice(0, 8).map((ch) => {
                const targetText = ch.target_service || ch.caller_service || ch.operation || ch.source_ip || "System endpoint";
                const isCrit = ch.severity === "critical" || ch.score >= 50;
                return (
                  <tr
                    key={ch.id}
                    className="border-b border-[#1f2230] hover:bg-[#181b28] transition-colors cursor-pointer"
                    onClick={() => nav(`/users/${encodeURIComponent(ch.principal_name)}/changes`)}
                  >
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <User size={13} className="text-cyan-400" />
                        <span className="font-mono font-bold text-white truncate max-w-[180px]" title={ch.principal_name}>
                          {ch.principal_name}
                        </span>
                      </div>
                    </td>

                    <td className="px-3 py-2.5">
                      <span
                        className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-bold border ${
                          ch.change_type === "NEW_TARGET"
                            ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-300"
                            : ch.change_type === "NEW_CALLER"
                            ? "border-violet-500/40 bg-violet-500/10 text-violet-300"
                            : ch.change_type === "NEW_SOURCE_IP"
                            ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                            : "border-rose-500/40 bg-rose-500/10 text-rose-300"
                        }`}
                      >
                        {t(ch.change_type, ch.change_type.replaceAll("_", " "))}
                      </span>
                    </td>

                    <td className="px-3 py-2.5 font-mono text-[11px] text-[#cbd5e1] truncate max-w-[240px]" title={targetText}>
                      {targetText}
                    </td>

                    <td className="px-3 py-2.5 font-mono font-bold">
                      <span className={isCrit ? "text-rose-400" : "text-amber-400"}>
                        +{ch.score}
                      </span>
                    </td>

                    <td className="px-3 py-2.5 font-mono text-[11px] text-[#94a3b8]">
                      {age(ch.detected_at)}
                    </td>

                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          nav(`/users/${encodeURIComponent(ch.principal_name)}/changes`);
                        }}
                        className="btn text-[11px] py-1 px-2.5 hover:border-cyan-400 text-cyan-300"
                      >
                        <span>{t("Analyze")}</span>
                        <ArrowRight size={10} />
                      </button>
                    </td>
                  </tr>
                );
              })}
              {changes.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-xs text-[#94a3b8]">
                    {t("No recent baseline changes detected in the selected time range.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Active User Behavioral Security Incidents */}
      <Panel
        title={t("Correlated Multi-Signal User Incidents")}
        subtitle={t("High-confidence behavioral security incidents grouped by principal lifetime window")}
        className="mt-4"
        action={
          <button
            onClick={() => nav("/incidents")}
            className="text-xs font-semibold text-rose-300 hover:text-white flex items-center gap-1"
          >
            <span>{t("View Incident Queue")} ({incidents.length})</span>
            <ArrowRight size={12} />
          </button>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 p-1">
          {incidents.slice(0, 6).map((inc) => (
            <div
              key={inc.incident_id}
              onClick={() => nav(`/users/${encodeURIComponent(inc.principal_name)}/investigations`)}
              className="cursor-pointer rounded-xl border border-[#262838] bg-[#12141f] p-4 transition-colors hover:border-[#383b52] hover:bg-[#161826] space-y-3"
            >
              <div className="flex items-center justify-between gap-2 border-b border-[#262838] pb-2.5">
                <div className="flex items-center gap-2 truncate font-mono text-xs font-bold text-white">
                  <User size={13} className="text-cyan-400 shrink-0" />
                  <span className="truncate">{inc.principal_name}</span>
                </div>
                <span
                  className={`rounded px-2 py-0.5 text-[10px] font-bold border ${
                    inc.score >= 50 || inc.priority === "high"
                      ? "border-rose-500/50 bg-rose-500/15 text-rose-300"
                      : "border-amber-500/50 bg-amber-500/15 text-amber-300"
                  }`}
                >
                  Score: {inc.score}
                </span>
              </div>

              <div className="space-y-1.5 text-xs">
                <div className="flex items-center justify-between text-[#94a3b8] text-[11px]">
                  <span>{t("Duration")}</span>
                  <span className="font-mono text-white">
                    {new Date(inc.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} – {new Date(inc.last_seen_at || inc.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>

                <div className="flex items-center justify-between text-[#94a3b8] text-[11px]">
                  <span>{t("Active Status")}</span>
                  <span className="font-mono text-emerald-300 font-bold uppercase">{t(inc.status || "open")}</span>
                </div>

                {inc.triggers && inc.triggers.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-[#262838] space-y-1">
                    <span className="text-[10px] uppercase font-bold text-[#94a3b8] tracking-wider">{t("Trigger Signals:")}</span>
                    <div className="flex flex-wrap gap-1">
                      {inc.triggers.slice(0, 3).map((trig, tIdx) => (
                        <span key={tIdx} className="rounded bg-[#1a1d2c] border border-[#2d3145] px-1.5 py-0.5 text-[9px] font-mono text-[#cbd5e1]">
                          {trig}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="pt-2 flex justify-end">
                <span className="text-xs font-bold text-cyan-300 hover:text-white flex items-center gap-1">
                  <span>{t("Open Investigation")}</span>
                  <ArrowRight size={11} />
                </span>
              </div>
            </div>
          ))}

          {incidents.length === 0 && (
            <div className="col-span-full py-8 text-center text-xs text-[#94a3b8]">
              {t("No active correlated user incidents in the selected time window.")}
            </div>
          )}
        </div>
      </Panel>
    </Page>
  );
}

function formatTime(value: number, timezone: string) {
  try {
    return new Intl.DateTimeFormat([], {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: timezone === "local" ? undefined : timezone,
    }).format(new Date(Number(value)));
  } catch {
    return new Date(Number(value)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
}
