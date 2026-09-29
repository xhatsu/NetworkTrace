import { useState } from "react";
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
import { ErrorState, Loading, MetricCard, Page, Panel, chartTooltip, n } from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import type { SeriesPoint, Summary } from "../types";
import { isEpisodeAttention, episodeStatusClass, episodeStatusLabel, type Episode, type EpisodeResponse } from "../components/EpisodePrimitives";
import { EntityLink } from "../components/EntityLink";
import { ZoomableDashboardChart } from "../components/ZoomableDashboardChart";

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
  total_requests?: number;
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

type TrendLine = { key: string; label: string; color: string; dash?: string };

function MetricTrend({ data, lines, timezone, formatValue }: {
  data: Array<{ timestamp_ms: number; [key: string]: unknown }>;
  lines: TrendLine[];
  timezone: string;
  formatValue: (value: number) => string;
}) {
  const { t } = useI18n();
  if (!data.length) return <div className="grid h-56 place-items-center text-xs text-[#a7a9ab]">{t("No telemetry points in the selected window")}</div>;
  return <>
    <div className="h-56 px-2 pt-2" role="img" aria-label={lines.map((line) => line.label).join(", ")}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} syncId="overview-metrics" syncMethod="value" margin={{ top: 5, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#303236" vertical={false} />
          <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={65} tick={{ fill: "#a7a9ab", fontSize: 12 }} tickFormatter={(value) => formatTime(Number(value), timezone)} axisLine={false} tickLine={false} />
          <YAxis width={70} domain={[0, "auto"]} tick={{ fill: "#a7a9ab", fontSize: 12 }} tickFormatter={formatValue} axisLine={false} tickLine={false} />
          <Tooltip {...chartTooltip} labelFormatter={(value) => formatTime(Number(value), timezone)} formatter={(value: unknown, name: unknown) => [formatValue(Number(value)), String(name)]} />
          {lines.map((line) => <Line key={line.key} type="linear" dataKey={line.key} name={line.label} stroke={line.color} strokeDasharray={line.dash} strokeWidth={1.8} dot={false} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
    <div className="flex flex-wrap gap-x-4 gap-y-1 px-3 pb-2 text-[11px] text-[#a7a9ab]">
      {lines.map((line) => <span key={line.key} className="inline-flex items-center gap-1.5"><span className="w-4 border-t-2" style={{ borderColor: line.color, borderTopStyle: line.dash ? "dashed" : "solid" }} />{line.label}</span>)}
    </div>
  </>;
}

function ChangeActivity({ changes, timezone }: { changes: Episode[]; timezone: string }) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<number | null>(null);
  const days = [t("Mon", "T2"), t("Tue", "T3"), t("Wed", "T4"), t("Thu", "T5"), t("Fri", "T6"), t("Sat", "T7"), t("Sun", "CN")];
  const dayKeys = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const formatter = new Intl.DateTimeFormat("en-GB", { weekday: "short", hour: "2-digit", hourCycle: "h23", ...(timezone === "local" ? {} : { timeZone: timezone }) });
  const cells = Array.from({ length: 168 }, () => ({ count: 0, critical: 0, attention: 0 }));
  for (const change of changes) {
    if (!Number.isFinite(change.started_at)) continue;
    const parts = formatter.formatToParts(new Date(change.started_at));
    const day = dayKeys.indexOf(parts.find((part) => part.type === "weekday")?.value || "");
    const hour = Number(parts.find((part) => part.type === "hour")?.value);
    if (day < 0 || !Number.isFinite(hour)) continue;
    const cell = cells[day * 24 + hour];
    cell.count += 1;
    cell.critical += Number(change.state === "critical");
    cell.attention += Number(change.state === "needs_attention");
  }
  const peak = Math.max(1, ...cells.map((cell) => cell.count));
  const activeIndex = selected ?? cells.findIndex((cell) => cell.count === peak);
  const active = cells[activeIndex];
  return <div className="px-3 pb-3 pt-2">
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] table-fixed border-separate border-spacing-[3px] text-[10px]" aria-label={t("Episode starts by weekday and hour", "Thời điểm bắt đầu thay đổi theo thứ và giờ")}>
        <thead><tr><th className="w-9" /><th colSpan={24} className="text-left font-normal text-[#a7a9ab]">{t("Hour", "Giờ")} · {timezone}</th></tr><tr><th />{Array.from({ length: 24 }, (_, hour) => <th key={hour} className="font-mono font-normal text-[#a7a9ab]">{hour % 3 === 0 ? String(hour).padStart(2, "0") : ""}</th>)}</tr></thead>
        <tbody>{days.map((day, index) => <tr key={day}><th scope="row" className="text-left font-normal text-[#a7a9ab]">{day}</th>{cells.slice(index * 24, index * 24 + 24).map((cell, hour) => {
          const key = index * 24 + hour;
          const label = `${day} ${String(hour).padStart(2, "0")}:00 · ${cell.count} ${t("episodes", "thay đổi")}`;
          return <td key={hour} className="h-5 p-0"><button type="button" aria-label={label} title={label} onMouseEnter={() => setSelected(key)} onFocus={() => setSelected(key)} onClick={() => setSelected(key)} className="h-full w-full rounded-[2px] font-mono text-[10px] outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#d8d9da]" style={{ background: cell.count ? `rgba(87, 148, 242, ${0.22 + 0.78 * cell.count / peak})` : "#181b1f", color: cell.count / peak > 0.6 ? "#0b0c0e" : "#d8d9da" }}>{cell.count || ""}</button></td>;
        })}</tr>)}</tbody>
      </table>
    </div>
    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#a7a9ab]">
      <span aria-live="polite">{active ? <>{days[Math.floor(activeIndex / 24)]} {String(activeIndex % 24).padStart(2, "0")}:00 · <strong className="text-[#d8d9da]">{active.count} {t("episodes", "thay đổi")}</strong> · {active.critical} {t("Critical")} · {active.attention} {t("Needs attention")}</> : t("No behavior changes in the current window.")}</span>
      <span className="inline-flex items-center gap-1.5">0 <span className="h-2 w-3 bg-[#181b1f]" /><span className="h-2 w-3 bg-[#5794f2]/30" /><span className="h-2 w-3 bg-[#5794f2]/60" /><span className="h-2 w-3 bg-[#5794f2]" />{peak}</span>
    </div>
  </div>;
}

export function OverviewPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [chartEngine, setChartEngine] = useState<"recharts" | "echarts">(() => {
    try { return window.localStorage.getItem("tracescope-dashboard-chart") === "echarts" ? "echarts" : "recharts"; } catch { return "recharts"; }
  });
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
  const totalUsers = Number(users.observed_principals || summary.active_accounts || 0);
  const totalServices = Number(summary.active_services || serviceItems.length || 0);
  const abnormalServices = serviceItems.filter((service) => service.anomaly_status === "abnormal");

  const windowSeconds = Math.max(1, (new Date(filters.end).getTime() - new Date(filters.start).getTime()) / 1000);
  const chartPoints = points.map((point) => ({ ...point }));
  const stateRank: Record<Episode["state"], number> = { expected: 0, changed: 1, watch: 2, needs_attention: 3, critical: 4 };
  const importantChanges = changes.filter(isEpisodeAttention).sort((a, b) => (stateRank[b.state] - stateRank[a.state]) || (b.last_seen_at - a.last_seen_at)).slice(0, 6);
  const usersWithChanges = changes.reduce<Record<string, number>>((acc, change) => {
    const user = change.subject.type === "user" ? change.subject.name : undefined;
    if (user && user !== "unknown" && user !== "-anonymous-") acc[user] = (acc[user] || 0) + 1;
    return acc;
  }, {});
  const changedUsers = Object.entries(usersWithChanges).sort(([, a], [, b]) => b - a).slice(0, 6);

  const attentionChanges = changes.filter(isEpisodeAttention);
  const criticalCount = attentionChanges.filter((change) => change.state === "critical").length;
  const changesReady = !changesQuery.isLoading && !changesQuery.isError;
  const changeCoverage = changesReady ? `${changes.length}/${changesQuery.data?.total ?? changes.length} ${t("episodes loaded", "thay đổi đã tải")}` : "—";

  // 1. TPS sparkline & secondary metrics
  const tpsSparkline = points.map((p) => Number(p.tps ?? p.rps ?? 0));
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

  return (
    <Page
      eyebrow={t("Observability Dashboard")}
      title={t("Operational Overview")}
      description={t("Fleet-scale operations: spot exceptions, prioritize services, investigate impact.", "Vận hành toàn hệ thống: nhận diện bất thường, ưu tiên Service, điều tra tác động.")}
      actions={
        <button onClick={() => nav("/changes")} className="btn">
          <AlertOctagon size={14} className="text-[#ff9830]" />
          {t("View behavior changes")}
        </button>
      }
    >
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-[1fr_1fr_1fr_1.2fr] [&_.metric-meta]:flex-col [&_.metric-meta]:items-start">
        <MetricCard label="TPS" value={n(totalTps, 2)} detail={t("Current throughput")} subDetail={`${t("Avg", "TB")} ${n(avgTps, 2)} · ${t("Peak", "Đỉnh")} ${n(peakTps, 2)}`} sparkline={tpsSparkline} accent="sky" />
        <MetricCard label={t("Bandwidth")} value={bandwidthQuery.isError || bandwidthQuery.data?.available === false ? "—" : formatRate(currentBandwidth)} detail={t("Request + response bytes/s")} subDetail={bandwidthQuery.isError || bandwidthQuery.data?.available === false ? "—" : `${t("Avg", "TB")} ${formatRate(avgBandwidth)} · ${t("Peak", "Đỉnh")} ${formatRate(peakBandwidth)}`} sparkline={bandwidthQuery.isError || bandwidthQuery.data?.available === false ? undefined : bandwidthSeries} accent="cyan" />
        <button type="button" onClick={() => nav("/changes?view=attention")} className="panel p-3 text-left hover:border-[#ff9830] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#ff9830]">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[#a7a9ab]">{t("Needs attention")}</span>
          <span className="mt-1 block font-mono text-2xl font-semibold text-[#ff9830]">{changesReady ? n(attentionChanges.length, 0) : "—"}</span>
          <span className="mt-1 block text-[11px] text-[#a7a9ab]">{changesReady ? criticalCount : "—"} {t("Critical")} · {t("Unresolved episodes", "Thay đổi chưa xử lý")}</span>
          <span className="mt-1 block text-[10px] text-[#a7a9ab]">{changeCoverage} <ArrowRight size={12} className="inline" /></span>
        </button>
        <div className="panel flex flex-col justify-center p-3">
          <span className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[#a7a9ab]">{t("Observed footprint", "Phạm vi quan sát")}</span>
          <div className="grid grid-cols-2 divide-x divide-[#2a2d30]">
            <button type="button" onClick={() => nav("/services")} className="pr-2 text-left hover:text-[#5794f2]"><span className="flex items-center gap-1.5 text-xs text-[#a7a9ab]"><Server size={12} />Services</span><strong className="font-mono text-xl">{n(totalServices, 0)}</strong><span className="mt-1 block text-[10px] text-[#a7a9ab]">{servicesQuery.isError || servicesQuery.isLoading ? "—" : abnormalServices.length} {t("with anomalies", "có bất thường")}</span></button>
            <button type="button" onClick={() => nav("/users")} className="pl-3 text-left hover:text-[#b877d9]"><span className="flex items-center gap-1.5 text-xs text-[#a7a9ab]"><UserRound size={12} />{t("Active users")}</span><strong className="font-mono text-xl">{n(users.active_principals, 0)}</strong><span className="mt-1 block text-[10px] text-[#a7a9ab]">{n(totalUsers, 0)} {t("observed", "đã quan sát")}</span></button>
          </div>
        </div>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1.8fr)_minmax(320px,1fr)]">
        <Panel title={t("Total TPS")} subtitle={`${n(summary.total_requests, 0)} ${t("Requests")} · ${t("Selected window", "Khoảng đã chọn")}`} action={<div className="flex items-center gap-2"><span className="font-mono text-xs text-[#5794f2]">{n(totalTps, 2)} TPS</span><div className="flex items-center gap-1 rounded border border-[#34373b] p-0.5 text-[10px]"><button type="button" aria-pressed={chartEngine === "recharts"} className={`px-2 py-1 ${chartEngine === "recharts" ? "bg-[#5794f2]/20 text-[#d8d9da]" : "text-[#7b7d80]"}`} onClick={() => { setChartEngine("recharts"); localStorage.setItem("tracescope-dashboard-chart", "recharts"); }}>Recharts</button><button type="button" aria-pressed={chartEngine === "echarts"} className={`px-2 py-1 ${chartEngine === "echarts" ? "bg-[#5794f2]/20 text-[#d8d9da]" : "text-[#7b7d80]"}`} onClick={() => { setChartEngine("echarts"); localStorage.setItem("tracescope-dashboard-chart", "echarts"); }}>ECharts</button></div></div>}>
          {chartEngine === "echarts" ? <ZoomableDashboardChart data={chartPoints} timezone={filters.timezone} /> : <MetricTrend data={chartPoints} timezone={filters.timezone} formatValue={(value) => n(value, 2)} lines={[{ key: "tps", label: "TPS", color: "#5794f2" }, { key: "baseline_rps", label: "Baseline", color: "#a7a9ab", dash: "4 4" }]} />}
        </Panel>
        <Panel title={t("HTTP error rate", "Tỷ lệ lỗi HTTP")} subtitle={t("4xx and 5xx failure signals across the selected window", "Tín hiệu lỗi 4xx và 5xx trong khoảng thời gian đã chọn")} action={<span className="font-mono text-xs text-[#f2495c]">{n(Number(latestPoint?.http_5xx_rate || 0) * 100, 2)}% 5xx</span>}>
          <MetricTrend data={chartPoints} timezone={filters.timezone} formatValue={(value) => `${n(value * 100, 2)}%`} lines={[{ key: "http_4xx_rate", label: "HTTP 4xx", color: "#ff9830" }, { key: "http_5xx_rate", label: "HTTP 5xx", color: "#f2495c" }]} />
        </Panel>
      </div>

      <div className="mt-3">
        <Panel title={t("When behavior changes", "Hành vi thay đổi khi nào")} subtitle={t("Episode starts by weekday × hour · selected window", "Số thay đổi bắt đầu theo thứ × giờ · khoảng đã chọn")} action={<span className="text-[10px] text-[#a7a9ab]">{changeCoverage}</span>}>
          {changesQuery.isLoading ? <Loading /> : changesQuery.isError ? <div className="p-6 text-xs text-[#a7a9ab]">{t("Change data unavailable", "Chưa có dữ liệu thay đổi")}</div> : <ChangeActivity changes={changes.filter((change) => change.started_at >= new Date(filters.start).getTime() && change.started_at <= new Date(filters.end).getTime())} timezone={filters.timezone} />}
        </Panel>
      </div>
      <p className="mt-2 text-right text-[10px] text-[#a7a9ab]">{t("Latest telemetry", "Telemetry mới nhất")}: {summary.latest_ingested_ms ? formatTime(summary.latest_ingested_ms, filters.timezone) : "—"}</p>

      <div className="mt-5 mb-2 text-xs font-semibold uppercase tracking-wider text-[#a7a9ab]">{t("Investigation & affected entities", "Điều tra & thực thể bị ảnh hưởng")}</div>
      <div>
        <Panel
          title={t("Unresolved priority changes", "Thay đổi ưu tiên chưa xử lý")}
          subtitle={`${t("Critical first · up to 6 episodes", "Nghiêm trọng trước · tối đa 6 thay đổi")} · ${changeCoverage}`}
          action={
            <button onClick={() => nav("/changes")} className="text-[11px] font-semibold text-[#5794f2] hover:text-white">
              {t("View all")} <ArrowRight size={12} className="inline" />
            </button>
          }
        >
          {importantChanges.length ? (
            <div role="region" aria-label={t("Important changes list")} tabIndex={0} className="max-h-[284px] overflow-y-auto overscroll-contain scrollbar divide-y divide-[#2a2d30] xl:max-h-[196px]">
              {importantChanges.map((change) => (
                <div key={change.id} className="flex items-start gap-2.5 px-3 py-2 transition hover:bg-[#181b1f]">
                  <span className={`mt-0.5 border px-1.5 py-0.5 text-[10px] font-bold uppercase ${episodeStatusClass(change.state)}`}>{episodeStatusLabel(change.state, t)}</span>
                  <span className="min-w-0 flex-1">
                    <EntityLink entity={{ kind: "change", id: change.id }} search={`?${queryString(filters)}`} className="block truncate text-xs font-semibold text-[#d8d9da] hover:text-[#5794f2]">{change.summary}</EntityLink>
                    <span className="mt-0.5 flex flex-wrap gap-x-1 text-[10px] text-[#a7a9ab]">
                      {change.context.target && <EntityLink entity={{ kind: "service", name: change.context.target }}>{change.context.target}</EntityLink>}
                      {change.context.caller && <EntityLink entity={{ kind: "service", name: change.context.caller }}>{change.context.caller}</EntityLink>}
                      {change.subject.type === "user"
                        ? <EntityLink entity={{ kind: "user", principal: change.subject.name }}>{change.subject.name}</EntityLink>
                        : <EntityLink entity={{ kind: "service", name: change.subject.name }}>{change.subject.name}</EntityLink>}
                    </span>
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-[#7b7d80]">{change.last_seen_at ? formatTime(change.last_seen_at, filters.timezone) : "—"}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid min-h-36 place-items-center p-4 text-xs text-[#7b7d80]">{changesQuery.isError ? t("Change data unavailable", "Chưa có dữ liệu thay đổi") : changesQuery.isLoading ? t("Loading", "Đang tải") : t("No unresolved attention episodes in the loaded results.", "Không có thay đổi cần chú ý chưa xử lý trong kết quả đã tải.")}</div>
          )}
        </Panel>
      </div>

      {/* Secondary context follows the operational triage queue. */}
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
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
                      <EntityLink entity={{ kind: "user", principal: user.principal_name }} className="flex items-center gap-1.5 text-left font-semibold text-[#d8d9da] hover:text-[#5794f2]">
                        <UserRound size={13} className="text-[#5794f2]" />{user.principal_name}
                      </EntityLink>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[#5794f2] tabular-nums">{n(Number(user.total_requests || 0) / windowSeconds, 2)}</td>
                    <td className="px-3 py-2 text-right font-mono text-[#a7a9ab] tabular-nums">{n(user.unique_targets, 0)}</td>
                    <td className="px-3 py-2 text-right font-mono text-[#a7a9ab] tabular-nums">{n(user.unique_operations, 0)}</td>
                    <td className={`px-3 py-2 text-right font-mono tabular-nums ${(user.recent_changes || 0) > 0 ? "text-[#ff9830]" : "text-[#7b7d80]"}`}>{n(user.recent_changes, 0)}</td>
                  </tr>
                )) : changedUsers.map(([principal, count]) => (
                  <tr key={principal} className="hover:bg-[#181b1f]">
                    <td className="px-3 py-2">
                      <EntityLink entity={{ kind: "user", principal }} className="flex items-center gap-1.5 text-left font-semibold text-[#d8d9da] hover:text-[#5794f2]">
                        <UserRound size={13} className="text-[#5794f2]" />{principal}
                      </EntityLink>
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
