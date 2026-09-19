import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, AlertOctagon, ArrowRight, Server, UserRound } from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, MetricCard, Page, Panel, chartTooltip, n } from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import type { SeriesPoint, Summary } from "../types";

type UserSummary = {
  observed_principals: number;
  active_principals: number;
  principals_with_changes: number;
};

type ServiceHealth = {
  name: string;
  environment?: string;
  anomaly_status?: string;
  rps?: number;
  error_rate?: number;
  p95_latency?: number;
};

type ChangeEvent = {
  id?: number;
  score?: number;
  severity?: string;
  principal_name?: string;
  change_type?: string;
  target_service?: string;
  caller_service?: string;
  operation?: string;
  new_value?: string;
  detected_at?: number | string;
};

const SCORE_COLORS = {
  low: "#22c55e",
  medium: "#f59e0b",
  high: "#f97316",
  critical: "#e11d48",
};

function formatTime(value: number, timezone: string) {
  try {
    const options: Intl.DateTimeFormatOptions = { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" };
    if (timezone !== "local") options.timeZone = timezone;
    return new Intl.DateTimeFormat([], options).format(new Date(Number(value)));
  } catch {
    return new Date(Number(value)).toLocaleString();
  }
}

function formatTooltipTime(value: unknown, timezone: string) {
  if (!value) return "";
  try {
    const options: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" };
    if (timezone !== "local") options.timeZone = timezone;
    return new Intl.DateTimeFormat([], options).format(new Date(Number(value)));
  } catch {
    return new Date(Number(value)).toLocaleString();
  }
}

function changeLabel(change: ChangeEvent) {
  return change.operation || change.change_type?.replaceAll("_", " ") || "Behavior change";
}

function changeScope(change: ChangeEvent) {
  return change.target_service || change.caller_service || change.new_value || "Identity behavior";
}

function changeTimestamp(change: ChangeEvent) {
  const raw = Number(change.detected_at || 0);
  return raw > 10_000_000_000 ? raw : raw * 1000;
}

function scoreBucket(score: number) {
  if (score >= 75) return "critical" as const;
  if (score >= 50) return "high" as const;
  if (score >= 25) return "medium" as const;
  return "low" as const;
}

function severityClass(severity?: string) {
  if (severity === "critical") return "border-rose-500/40 bg-rose-500/15 text-rose-300";
  if (severity === "high") return "border-amber-500/40 bg-amber-500/15 text-amber-300";
  if (severity === "medium") return "border-violet-500/40 bg-violet-500/15 text-violet-300";
  return "border-cyan-500/40 bg-cyan-500/15 text-cyan-300";
}

export function OverviewPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const qs = queryString(filters);

  const summaryQuery = useQuery({ queryKey: ["dashboard-summary", qs], queryFn: () => api<Summary>(`/api/v1/dashboard/summary?${qs}`), refetchInterval: 60000 });
  const seriesQuery = useQuery({ queryKey: ["dashboard-series", qs], queryFn: () => api<{ items: SeriesPoint[]; bucket_seconds?: number }>(`/api/v1/dashboard/series?${qs}`), refetchInterval: 60000 });
  const usersQuery = useQuery({ queryKey: ["dashboard-user-summary", qs], queryFn: () => api<UserSummary>(`/api/v1/users/summary?${qs}`), refetchInterval: 60000 });
  const servicesQuery = useQuery({ queryKey: ["dashboard-services-health", qs], queryFn: () => api<{ items: ServiceHealth[] }>(`/api/v1/services?limit=500&${qs}`), refetchInterval: 60000 });
  const changesQuery = useQuery({ queryKey: ["dashboard-abnormal-changes", qs], queryFn: () => api<{ items: ChangeEvent[]; count?: number }>(`/api/v1/user-changes?limit=500&${qs}`), refetchInterval: 60000 });

  const isLoading = summaryQuery.isLoading || seriesQuery.isLoading || usersQuery.isLoading;
  const firstError = summaryQuery.error || seriesQuery.error || usersQuery.error;
  if (isLoading) {
    return <Page eyebrow={t("Observability Dashboard")} title={t("Operational Overview")} description={t("Current five-minute telemetry over the last seven days.")}><Loading /></Page>;
  }
  if (firstError) {
    return <Page eyebrow={t("Observability Dashboard")} title={t("Operational Overview")} description=""><ErrorState message={firstError.message} /></Page>;
  }

  const summary = summaryQuery.data || ({} as Summary);
  const users = usersQuery.data || { observed_principals: 0, active_principals: 0, principals_with_changes: 0 };
  const points = seriesQuery.data?.items || [];
  const serviceItems = servicesQuery.data?.items || [];
  const changes = changesQuery.data?.items || [];
  const latestPoint = points[points.length - 1];
  const totalTps = Number(latestPoint?.tps ?? summary.observed_tps ?? summary.observed_rps ?? 0);
  const currentErrorPercent = Number(latestPoint?.http_5xx_rate ?? summary.http_5xx_rate ?? 0) * 100;
  const currentP95 = Number(latestPoint?.p95_ms ?? summary.p95_latency_ms ?? 0);
  const totalUsers = Number(users.observed_principals || summary.active_accounts || 0);
  const totalServices = Number(summary.active_services || serviceItems.length || 0);
  const abnormalServices = serviceItems.filter((service) => service.anomaly_status === "abnormal");
  const abnormalCount = Number(changesQuery.data?.count ?? changes.length);

  const chartPoints = points.map((point) => ({ ...point, error_percent: Number(point.http_5xx_rate || 0) * 100 }));
  const importantChanges = [...changes].sort((a, b) => (Number(b.score || 0) - Number(a.score || 0)) || (changeTimestamp(b) - changeTimestamp(a))).slice(0, 6);
  const serviceHotspots = [...serviceItems].sort((a, b) => {
    const abnormalDelta = Number(b.anomaly_status === "abnormal") - Number(a.anomaly_status === "abnormal");
    return abnormalDelta || (Number(b.error_rate || 0) - Number(a.error_rate || 0)) || (Number(b.p95_latency || 0) - Number(a.p95_latency || 0));
  }).slice(0, 6);
  const usersWithChanges = changes.reduce<Record<string, number>>((acc, change) => {
    const user = change.principal_name;
    if (user && user !== "unknown" && user !== "-anonymous-") acc[user] = (acc[user] || 0) + 1;
    return acc;
  }, {});
  const changedUsers = Object.entries(usersWithChanges).sort(([, a], [, b]) => b - a).slice(0, 6);

  const scoreBuckets = { low: 0, medium: 0, high: 0, critical: 0 };
  changes.forEach((change) => { scoreBuckets[scoreBucket(Math.max(0, Number(change.score || 0)))] += 1; });
  const scoreDistribution = [{ name: t("Abnormal changes"), ...scoreBuckets }];
  const scoreLegend = [["low", t("0–24 Low")], ["medium", t("25–49 Medium")], ["high", t("50–74 High")], ["critical", t("75–100 Critical")]] as const;

  return (
    <Page eyebrow={t("Observability Dashboard")} title={t("Operational Overview")} description={t("Status, changes, and the services or users behind them.")} actions={<button onClick={() => nav("/anomalies")} className="btn-cyan text-xs"><AlertOctagon size={14} />{t("Open anomalies")}</button>}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-cyan-500/25 bg-cyan-500/10 px-3.5 py-2.5 text-xs"><div className="flex items-center gap-2 font-semibold text-cyan-300"><Activity size={14} />{t("Live dashboard window")}</div><div className="font-mono text-[#94a3b8]">{t("5-minute buckets · 7-day history")}</div></div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard label={t("Total TPS")} value={n(totalTps, 2)} detail={t("Current five-minute throughput")} accent="cyan" />
        <MetricCard label={t("Total Users")} value={n(totalUsers, 0)} detail={t("Observed identities")} accent="indigo" />
        <MetricCard label={t("Total Services")} value={n(totalServices, 0)} detail={`${n(abnormalServices.length, 0)} ${t("in bad health")}`} tone={abnormalServices.length ? "bad" : "good"} accent="amber" />
        <MetricCard label={t("Abnormal Changes")} value={n(abnormalCount, 0)} detail={t("Behavior changes in current window")} tone={abnormalCount ? "bad" : "good"} accent="purple" />
      </div>

      <Panel title={t("Important Changes")} subtitle={t("Highest-value changes detected in the current window.")} className="mt-4" action={<button onClick={() => nav("/anomalies")} className="text-[11px] font-semibold text-cyan-300 hover:text-white">{t("View all")} <ArrowRight size={12} className="inline" /></button>}>
        {importantChanges.length ? <div className="grid gap-2 p-3 md:grid-cols-2 xl:grid-cols-3">{importantChanges.map((change, index) => { const severity = change.severity || scoreBucket(Number(change.score || 0)); return <button key={change.id ?? `${change.principal_name}-${change.change_type}-${index}`} onClick={() => nav(change.id ? `/anomalies/${change.id}?${queryString(filters)}` : "/user-changes")} className="rounded-lg border border-[#262838] bg-[#0c0d14] p-3 text-left transition hover:border-cyan-500/50 hover:bg-cyan-500/[0.05]"><div className="flex items-center justify-between gap-2"><span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${severityClass(severity)}`}>{t(severity, severity)}</span><span className="font-mono text-[10px] text-[#94a3b8]">{changeTimestamp(change) ? formatTime(changeTimestamp(change), filters.timezone) : "—"}</span></div><div className="mt-2 truncate text-xs font-semibold text-[#f5f3fa]">{changeLabel(change)}</div><div className="mt-1 truncate text-[11px] text-violet-300">{changeScope(change)}</div><div className="mt-2 flex items-center gap-2 text-[11px] text-[#94a3b8]">{change.principal_name && <><UserRound size={12} className="text-cyan-400" />{change.principal_name}</>}{change.target_service && <><Server size={12} className="text-violet-400" />{change.target_service}</>}</div></button>; })}</div> : <div className="p-6 text-center text-xs text-[#94a3b8]">{t("No important changes in the current window.")}</div>}
      </Panel>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title={t("Total TPS")} subtitle={t("Five-minute buckets · last seven days")} action={<span className="font-mono text-xs font-bold text-cyan-300">{n(totalTps, 2)} TPS</span>}><div className="h-[250px] p-3"><ResponsiveContainer><LineChart data={chartPoints} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}><CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} /><XAxis dataKey="timestamp_ms" tickFormatter={(value) => formatTime(value, filters.timezone)} minTickGap={44} stroke="#766e92" /><YAxis width={42} unit=" tps" stroke="#766e92" /><Tooltip {...chartTooltip} formatter={(value: any) => [`${Number(value || 0).toFixed(2)} TPS`, t("Total TPS")]} labelFormatter={(value: any) => formatTooltipTime(value, filters.timezone)} /><Line type="monotone" dataKey="tps" stroke="#06b6d4" strokeWidth={2} dot={false} name={t("Total TPS")} /></LineChart></ResponsiveContainer></div></Panel>
        <Panel title={t("Error %")} subtitle={t("HTTP 5xx error rate in five-minute buckets")} action={<span className="font-mono text-xs font-bold text-rose-300">{currentErrorPercent.toFixed(2)}%</span>}><div className="h-[250px] p-3"><ResponsiveContainer><LineChart data={chartPoints} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}><CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} /><XAxis dataKey="timestamp_ms" tickFormatter={(value) => formatTime(value, filters.timezone)} minTickGap={44} stroke="#766e92" /><YAxis width={42} unit="%" stroke="#766e92" /><Tooltip {...chartTooltip} formatter={(value: any) => [`${Number(value || 0).toFixed(2)}%`, t("Error %")]} labelFormatter={(value: any) => formatTooltipTime(value, filters.timezone)} /><Line type="monotone" dataKey="error_percent" stroke="#e11d48" strokeWidth={2} dot={false} name={t("Error %")} /></LineChart></ResponsiveContainer></div></Panel>
        <Panel title={t("P95 latency")} subtitle={t("Tail latency in five-minute buckets")} action={<span className="font-mono text-xs font-bold text-violet-300">{n(currentP95, 0)} ms</span>}><div className="h-[250px] p-3"><ResponsiveContainer><LineChart data={chartPoints} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}><CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} /><XAxis dataKey="timestamp_ms" tickFormatter={(value) => formatTime(value, filters.timezone)} minTickGap={44} stroke="#766e92" /><YAxis width={42} unit=" ms" stroke="#766e92" /><Tooltip {...chartTooltip} formatter={(value: any) => [`${Number(value || 0).toFixed(0)} ms`, t("P95 latency")]} labelFormatter={(value: any) => formatTooltipTime(value, filters.timezone)} /><Line type="monotone" dataKey="p95_ms" stroke="#8b5cf6" strokeWidth={2} dot={false} name={t("P95 latency")} /></LineChart></ResponsiveContainer></div></Panel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title={t("Services needing attention")} subtitle={t("Services ordered by health signal, error rate, and latency.")} action={<button onClick={() => nav("/services")} className="text-[11px] font-semibold text-cyan-300 hover:text-white">{t("View services")} <ArrowRight size={12} className="inline" /></button>}><div className="overflow-auto"><table className="w-full min-w-[560px]"><thead><tr className="border-b border-[#262838] text-left"><th className="table-head px-4 py-2.5">{t("Service")}</th><th className="table-head px-4 py-2.5">{t("TPS")}</th><th className="table-head px-4 py-2.5">{t("P95")}</th><th className="table-head px-4 py-2.5">{t("Error")}</th><th className="table-head px-4 py-2.5">{t("Health")}</th></tr></thead><tbody>{serviceHotspots.map((service) => <tr key={service.name} className="border-b border-[#262838] text-xs"><td className="px-4 py-2.5"><button onClick={() => nav(`/services/${encodeURIComponent(service.name)}`)} className="text-left font-semibold text-[#f5f3fa] hover:text-cyan-300">{service.name}</button><span className="block text-[10px] text-[#94a3b8]">{service.environment || "—"}</span></td><td className="px-4 py-2.5 font-mono text-cyan-300">{n(service.rps, 2)}</td><td className="px-4 py-2.5 font-mono text-violet-300">{n(service.p95_latency, 0)} ms</td><td className={`px-4 py-2.5 font-mono ${Number(service.error_rate || 0) > 0.01 ? "text-rose-300" : "text-emerald-300"}`}>{(Number(service.error_rate || 0) * 100).toFixed(2)}%</td><td className="px-4 py-2.5"><span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${service.anomaly_status === "abnormal" ? "border-rose-500/40 bg-rose-500/15 text-rose-300" : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"}`}>{service.anomaly_status === "abnormal" ? t("Needs attention") : t("Normal")}</span></td></tr>)}</tbody></table>{!serviceHotspots.length && <div className="p-6 text-center text-xs text-[#94a3b8]">{t("No service health data available.")}</div>}</div></Panel>
        <Panel title={t("Users with changes")} subtitle={t("Identities with the most observed changes in this window.")} action={<button onClick={() => nav("/users")} className="text-[11px] font-semibold text-cyan-300 hover:text-white">{t("View users")} <ArrowRight size={12} className="inline" /></button>}><div className="divide-y divide-[#262838]">{changedUsers.length ? changedUsers.map(([principal, count]) => <button key={principal} onClick={() => nav(`/users/${encodeURIComponent(principal)}`)} className="flex w-full items-center justify-between px-4 py-3 text-left transition hover:bg-cyan-500/[0.05]"><span className="flex items-center gap-2 text-xs font-semibold text-[#f5f3fa]"><UserRound size={14} className="text-cyan-400" />{principal}</span><span className="font-mono text-xs text-amber-300">{count} {t("changes")}</span></button>) : <div className="p-6 text-center text-xs text-[#94a3b8]">{t("No users with changes in the current window.")}</div>}</div></Panel>
      </div>

      <Panel title={t("Abnormal Changes by Score")} subtitle={t("Secondary distribution of observed abnormal-change scores.")} className="mt-4" action={<span className="font-mono text-xs text-rose-300">{n(abnormalCount, 0)} {t("changes")}</span>}><div className="h-[220px] p-3">{changes.length ? <ResponsiveContainer><BarChart data={scoreDistribution} layout="vertical" margin={{ top: 18, right: 18, bottom: 8, left: 12 }}><CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} /><XAxis type="number" allowDecimals={false} stroke="#766e92" /><YAxis type="category" dataKey="name" width={110} stroke="#766e92" tick={{ fill: "#cbd5e1", fontSize: 11 }} /><Tooltip {...chartTooltip} />{scoreLegend.map(([key, label]) => <Bar key={key} dataKey={key} stackId="score" name={label} fill={SCORE_COLORS[key]} radius={key === "critical" ? [0, 4, 4, 0] : undefined} />)}</BarChart></ResponsiveContainer> : <div className="grid h-full place-items-center text-xs text-[#94a3b8]">{t("No abnormal changes in the current seven-day window.")}</div>}</div><div className="flex flex-wrap gap-x-5 gap-y-2 border-t border-[#262838] px-4 py-3">{scoreLegend.map(([key, label]) => <div key={key} className="flex items-center gap-1.5 text-[11px] text-[#94a3b8]"><span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: SCORE_COLORS[key] }} />{label}: <strong className="font-mono text-[#f5f3fa]">{scoreDistribution[0][key]}</strong></div>)}</div></Panel>
    </Page>
  );
}
