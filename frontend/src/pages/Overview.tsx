import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertOctagon, ArrowRight, Server, UserRound } from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, MetricCard, Page, Panel, TpsLineChart, chartTooltip, n } from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import type { SeriesPoint, Summary } from "../types";
import { episodeStatusClass, episodeStatusLabel, type Episode, type EpisodeResponse } from "../components/EpisodePrimitives";

type UserSummary = {
  observed_principals: number;
  active_principals: number;
  principals_with_changes: number;
};

type UserHealth = {
  principal_name: string;
  total_requests?: number;
  unique_targets?: number;
  unique_operations?: number;
  behavior_score?: number;
  recent_changes?: number;
};

type ServiceHealth = {
  name: string;
  environment?: string;
  anomaly_status?: string;
  rps?: number;
  error_rate?: number;
  p95_latency?: number;
  principal_count?: number;
  operations_count?: number;
};

type DashboardBandwidth = {
  available?: boolean;
  metrics?: { bandwidth_bytes_per_second?: number };
  series?: Array<{ timestamp_ms: number; bandwidth_bytes_per_second?: number }>;
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

function changeHref(change: Episode, filters: ReturnType<typeof useFilters>["filters"]) {
  const qs = queryString(filters);
  return `/changes/${encodeURIComponent(change.id)}${qs ? `?${qs}` : ""}`;
}

export function OverviewPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const qs = queryString(filters);

  const summaryQuery = useQuery({ queryKey: ["dashboard-summary", qs], queryFn: () => api<Summary>(`/api/v1/dashboard/summary?${qs}`), refetchInterval: 60000 });
  const seriesQuery = useQuery({ queryKey: ["dashboard-series", qs], queryFn: () => api<{ items: SeriesPoint[]; bucket_seconds?: number }>(`/api/v1/dashboard/series?${qs}`), refetchInterval: 60000 });
  const bandwidthQuery = useQuery({ queryKey: ["dashboard-bandwidth", qs], queryFn: () => api<DashboardBandwidth>(`/api/v1/topology/bandwidth?window=30d&${qs}`), refetchInterval: 60000 });
  const usersQuery = useQuery({ queryKey: ["dashboard-user-summary", qs], queryFn: () => api<UserSummary>(`/api/v1/users/summary?${qs}`), refetchInterval: 60000 });
  const usersDirectoryQuery = useQuery({ queryKey: ["dashboard-user-health", qs], queryFn: () => api<{ items: UserHealth[] }>(`/api/v1/users?${queryString(filters, { limit: "6", sort: "most_changed" })}`), refetchInterval: 60000 });
  const servicesQuery = useQuery({ queryKey: ["dashboard-services-health", qs], queryFn: () => api<{ items: ServiceHealth[] }>(`/api/v1/services?limit=500&${qs}`), refetchInterval: 60000 });
  const changesQuery = useQuery({ queryKey: ["dashboard-change-episodes", qs], queryFn: () => api<EpisodeResponse>(`/api/v1/changes?limit=500&${qs}`), refetchInterval: 60000 });

  const isLoading = summaryQuery.isLoading || seriesQuery.isLoading || usersQuery.isLoading || bandwidthQuery.isLoading;
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
  const userHotspots = usersDirectoryQuery.data?.items || [];
  const changes = changesQuery.data?.items || [];
  const latestPoint = points[points.length - 1];
  const totalTps = Number(latestPoint?.tps ?? summary.observed_tps ?? summary.observed_rps ?? 0);
  const currentErrorPercent = Number(latestPoint?.http_5xx_rate ?? summary.http_5xx_rate ?? 0) * 100;
  const currentP95 = Number(latestPoint?.p95_ms ?? summary.p95_latency_ms ?? 0);
  const totalUsers = Number(users.observed_principals || summary.active_accounts || 0);
  const totalServices = Number(summary.active_services || serviceItems.length || 0);
  const abnormalServices = serviceItems.filter((service) => service.anomaly_status === "abnormal");
  const windowSeconds = Math.max(1, (new Date(filters.end).getTime() - new Date(filters.start).getTime()) / 1000);

  const chartPoints = points.map((point) => ({ ...point, error_percent: Number(point.http_5xx_rate || 0) * 100 }));
  const stateRank: Record<Episode["state"], number> = { expected: 0, changed: 1, needs_attention: 2, critical: 3 };
  const importantChanges = [...changes].sort((a, b) => (stateRank[b.state] - stateRank[a.state]) || (b.last_seen_at - a.last_seen_at)).slice(0, 6);
  const serviceHotspots = [...serviceItems].sort((a, b) => {
    const abnormalDelta = Number(b.anomaly_status === "abnormal") - Number(a.anomaly_status === "abnormal");
    return abnormalDelta || (Number(b.error_rate || 0) - Number(a.error_rate || 0)) || (Number(b.p95_latency || 0) - Number(a.p95_latency || 0));
  }).slice(0, 6);
  const usersWithChanges = changes.reduce<Record<string, number>>((acc, change) => {
    const user = change.subject.type === "user" ? change.subject.name : undefined;
    if (user && user !== "unknown" && user !== "-anonymous-") acc[user] = (acc[user] || 0) + 1;
    return acc;
  }, {});
  const changedUsers = Object.entries(usersWithChanges).sort(([, a], [, b]) => b - a).slice(0, 6);

  const stateCounts = {
    expected: changes.filter((change) => change.state === "expected").length,
    changed: changes.filter((change) => change.state === "changed").length,
    needs_attention: changes.filter((change) => change.state === "needs_attention").length,
    critical: changes.filter((change) => change.state === "critical").length,
  };

  // 1. TPS sparkline & secondary metrics
  const tpsSparkline = points.map((p) => Number(p.tps || p.rps || 0));
  const avgTps = points.length ? tpsSparkline.reduce((a, b) => a + b, 0) / points.length : totalTps;
  const peakTps = points.length ? Math.max(...tpsSparkline) : totalTps;

  // 2. Bandwidth series is supplied by the topology rollups because the legacy
  // dashboard rollups intentionally do not retain byte measurements.
  const bandwidthSeries = (bandwidthQuery.data?.series || []).map((point) => Number(point.bandwidth_bytes_per_second || 0));
  const currentBandwidth = bandwidthSeries.length
    ? bandwidthSeries[bandwidthSeries.length - 1]
    : Number(bandwidthQuery.data?.metrics?.bandwidth_bytes_per_second || 0);
  const avgBandwidth = bandwidthSeries.length
    ? bandwidthSeries.reduce((sum, value) => sum + value, 0) / bandwidthSeries.length
    : currentBandwidth;
  const peakBandwidth = bandwidthSeries.length ? Math.max(...bandwidthSeries) : currentBandwidth;

  function formatRate(value: number) {
    const rate = Math.max(0, Number.isFinite(value) ? value : 0);
    if (rate >= 1024 ** 2) return `${n(rate / 1024 ** 2, 1)} MiB/s`;
    if (rate >= 1024) return `${n(rate / 1024, 1)} KiB/s`;
    return `${n(rate, 0)} B/s`;
  }

  // 2. Error rate sparkline & peak
  const errorSparkline = points.map((p) => Number(p.http_5xx_rate || 0) * 100);
  const maxError = points.length ? Math.max(...errorSparkline) : currentErrorPercent;

  // 3. P95 latency sparkline, avg p50 & peak p99
  const p95Sparkline = points.map((p) => Number(p.p95_ms || 0));
  const avgP50 = points.length ? points.reduce((acc, p) => acc + Number(p.p50_ms || 0), 0) / points.length : 0;
  const peakP99 = points.length ? Math.max(...points.map((p) => Number(p.p99_ms || 0))) : 0;

  // 4. Active users sparkline
  const usersSparkline = points.map((p) => Number(p.active_users ?? (p.sample_count > 0 ? (users.active_principals || totalUsers) : 0)));

  // 5. Active services sparkline
  const servicesSparkline = points.map((p) => Number(p.active_services ?? (p.sample_count > 0 ? totalServices : 0)));

  return (
    <Page
      eyebrow={t("Observability Dashboard")}
      title={t("Operational Overview")}
      description={t("Status, changes, and the services or users behind them.")}
      actions={
        <button onClick={() => nav("/changes")} className="btn">
          <AlertOctagon size={14} className="text-[#ff9830]" />
          {t("View behavior changes")}
        </button>
      }
    >
      {/* 1. Compact health summary with sparklines: TPS, Error Rate, Bandwidth, P95, Active Users, Services */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard
          label={t("TPS")}
          value={n(totalTps, 2)}
          detail={t("Current throughput")}
          subDetail={`avg ${n(avgTps, 1)} · peak ${n(peakTps, 1)}`}
          sparkline={tpsSparkline}
          accent="sky"
        />
        <MetricCard
          label={t("Error rate")}
          value={`${currentErrorPercent.toFixed(2)}%`}
          detail={t("HTTP 5xx")}
          subDetail={`peak ${maxError.toFixed(1)}%`}
          sparkline={errorSparkline}
          tone={currentErrorPercent > 1 ? "bad" : "normal"}
          accent="rose"
        />
        <MetricCard
          label={t("Bandwidth")}
          value={bandwidthQuery.isError || bandwidthQuery.data?.available === false ? "—" : formatRate(currentBandwidth)}
          detail={t("Request + response bytes/s")}
          subDetail={`avg ${formatRate(avgBandwidth)} · peak ${formatRate(peakBandwidth)}`}
          sparkline={bandwidthSeries}
          accent="sky"
        />
        <MetricCard
          label={t("P95 latency")}
          value={`${n(currentP95, 0)} ms`}
          detail={t("Tail latency")}
          subDetail={`p50 ${n(avgP50, 0)} · p99 ${n(peakP99, 0)}`}
          sparkline={p95Sparkline}
          accent="violet"
        />
        <MetricCard
          label={t("Active users")}
          value={n(totalUsers, 0)}
          detail={t("Observed identities")}
          subDetail={`${n(users.active_principals, 0)} ${t("active now")}`}
          sparkline={usersSparkline}
          accent="purple"
        />
        <MetricCard
          label={t("Services")}
          value={n(totalServices, 0)}
          detail={`${n(abnormalServices.length, 0)} ${t("attention")}`}
          subDetail={`${serviceItems.length} ${t("registered")}`}
          sparkline={servicesSparkline}
          tone={abnormalServices.length ? "bad" : "normal"}
          accent="amber"
        />
      </div>

      {/* 2. Main TPS chart beside Important changes */}
      <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,.7fr)]">
        <Panel title={t("Total TPS")} subtitle={t("Five-minute buckets · last seven days")} action={<span className="font-mono text-[11px] font-semibold text-[#5794f2]">{n(totalTps, 2)} TPS</span>}>
          <TpsLineChart data={points} heightClassName="h-60" />
        </Panel>
        <Panel
          title={t("Important changes", "Thay đổi quan trọng")}
          subtitle={t("Recent behavior changes that need context")}
          action={
            <button onClick={() => nav("/changes")} className="text-[11px] font-semibold text-[#5794f2] hover:text-white">
              {t("View all")} <ArrowRight size={12} className="inline" />
            </button>
          }
        >
          {/* Compact change state counter strip */}
          <div className="grid grid-cols-3 gap-1 border-b border-[#2a2d30] bg-[#0e0f12] p-2">
            <button
              type="button"
              onClick={() => nav("/changes?view=attention")}
              className="flex items-center justify-between border border-[#f2495c]/30 bg-[#f2495c]/10 px-2 py-1 text-left transition hover:border-[#f2495c]"
            >
              <span className="text-[10px] font-semibold text-[#f2495c]">{t("Critical")}</span>
              <span className="font-mono text-xs font-bold text-[#f2495c] tabular-nums">{stateCounts.critical}</span>
            </button>
            <button
              type="button"
              onClick={() => nav("/changes?view=attention")}
              className="flex items-center justify-between border border-[#ff9830]/30 bg-[#ff9830]/10 px-2 py-1 text-left transition hover:border-[#ff9830]"
            >
              <span className="text-[10px] font-semibold text-[#ff9830]">{t("Attention")}</span>
              <span className="font-mono text-xs font-bold text-[#ff9830] tabular-nums">{stateCounts.needs_attention}</span>
            </button>
            <button
              type="button"
              onClick={() => nav("/changes")}
              className="flex items-center justify-between border border-[#5794f2]/30 bg-[#5794f2]/10 px-2 py-1 text-left transition hover:border-[#5794f2]"
            >
              <span className="text-[10px] font-semibold text-[#5794f2]">{t("Changed")}</span>
              <span className="font-mono text-xs font-bold text-[#5794f2] tabular-nums">{stateCounts.changed}</span>
            </button>
          </div>

          {importantChanges.length ? (
            <div role="region" aria-label={t("Important changes list")} tabIndex={0} className="max-h-[284px] overflow-y-auto overscroll-contain scrollbar divide-y divide-[#2a2d30] xl:max-h-[196px]">
              {importantChanges.map((change) => (
                <button key={change.id} onClick={() => nav(changeHref(change, filters))} className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition hover:bg-[#181b1f]">
                  <span className={`mt-0.5 border px-1.5 py-0.5 text-[9px] font-bold uppercase ${episodeStatusClass(change.state)}`}>{episodeStatusLabel(change.state, t)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-semibold text-[#d8d9da]">{change.summary}</span>
                    <span className="mt-0.5 block truncate text-[10px] text-[#a7a9ab]">{change.context.target || change.context.caller || t("Estate")}{` · ${change.subject.name}`}</span>
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-[#7b7d80]">{change.last_seen_at ? formatTime(change.last_seen_at, filters.timezone) : "—"}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="grid min-h-36 place-items-center p-4 text-xs text-[#7b7d80]">{t("No behavior changes in the current window.")}</div>
          )}
        </Panel>
      </div>

      {/* 3. Top Services and Top Users tables */}
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <Panel title={t("Top services")} subtitle={t("Service → API health signals ordered by operational risk.")} action={<button onClick={() => nav("/services")} className="text-[11px] font-semibold text-[#5794f2] hover:text-white">{t("View services")} <ArrowRight size={12} className="inline" /></button>}>
          <div className="overflow-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead>
                <tr className="border-b border-[#2a2d30]">
                  <th className="table-head px-3 py-2">{t("Service")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("TPS")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Error")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("P95")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Users")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("APIs")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2a2d30]">
                {serviceHotspots.map((service) => (
                  <tr key={service.name} className="hover:bg-[#181b1f]">
                    <td className="px-3 py-2">
                      <button onClick={() => nav(`/services/${encodeURIComponent(service.name)}`)} className="text-left font-semibold text-[#d8d9da] hover:text-[#5794f2]">{service.name}</button>
                      <span className="block text-[10px] text-[#7b7d80]">{service.environment || "—"}</span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[#5794f2] tabular-nums">{n(service.rps, 2)}</td>
                    <td className={`px-3 py-2 text-right font-mono tabular-nums ${Number(service.error_rate || 0) > 0.01 ? "text-[#f2495c]" : "text-[#73bf69]"}`}>{(Number(service.error_rate || 0) * 100).toFixed(2)}%</td>
                    <td className="px-3 py-2 text-right font-mono text-[#b877d9] tabular-nums">{n(service.p95_latency, 0)} ms</td>
                    <td className="px-3 py-2 text-right font-mono text-[#a7a9ab] tabular-nums">{n(service.principal_count, 0)}</td>
                    <td className="px-3 py-2 text-right font-mono text-[#a7a9ab] tabular-nums">{n(service.operations_count, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!serviceHotspots.length && <div className="p-6 text-center text-xs text-[#7b7d80]">{t("No service health data available.")}</div>}
          </div>
        </Panel>

        <Panel title={t("Top users")} subtitle={t("Identity activity and behavior changes in this window.")} action={<button onClick={() => nav("/users")} className="text-[11px] font-semibold text-[#5794f2] hover:text-white">{t("View users")} <ArrowRight size={12} className="inline" /></button>}>
          <div className="overflow-auto">
            <table className="w-full min-w-[500px] text-left text-xs">
              <thead>
                <tr className="border-b border-[#2a2d30]">
                  <th className="table-head px-3 py-2">{t("User")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("TPS")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Services")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("APIs")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Changes")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2a2d30]">
                {userHotspots.length ? userHotspots.map((user) => (
                  <tr key={user.principal_name} className="hover:bg-[#181b1f]">
                    <td className="px-3 py-2">
                      <button onClick={() => nav(`/users/${encodeURIComponent(user.principal_name)}/activity`)} className="flex items-center gap-1.5 text-left font-semibold text-[#d8d9da] hover:text-[#5794f2]">
                        <UserRound size={13} className="text-[#5794f2]" />{user.principal_name}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[#5794f2] tabular-nums">{n(Number(user.total_requests || 0) / windowSeconds, 2)}</td>
                    <td className="px-3 py-2 text-right font-mono text-[#a7a9ab] tabular-nums">{n(user.unique_targets, 0)}</td>
                    <td className="px-3 py-2 text-right font-mono text-[#a7a9ab] tabular-nums">{n(user.unique_operations, 0)}</td>
                    <td className={`px-3 py-2 text-right font-mono tabular-nums ${(user.recent_changes || 0) > 0 ? "text-[#ff9830]" : "text-[#7b7d80]"}`}>{n(user.recent_changes, 0)}</td>
                  </tr>
                )) : changedUsers.map(([principal, count]) => (
                  <tr key={principal} className="hover:bg-[#181b1f]">
                    <td className="px-3 py-2">
                      <button onClick={() => nav(`/users/${encodeURIComponent(principal)}/activity`)} className="flex items-center gap-1.5 text-left font-semibold text-[#d8d9da] hover:text-[#5794f2]">
                        <UserRound size={13} className="text-[#5794f2]" />{principal}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[#7b7d80]">—</td>
                    <td className="px-3 py-2 text-right font-mono text-[#7b7d80]">—</td>
                    <td className="px-3 py-2 text-right font-mono text-[#7b7d80]">—</td>
                    <td className="px-3 py-2 text-right font-mono text-[#ff9830] tabular-nums">{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!userHotspots.length && !changedUsers.length && <div className="p-6 text-center text-xs text-[#7b7d80]">{t("No users with changes in the current window.")}</div>}
          </div>
        </Panel>
      </div>
    </Page>
  );
}
