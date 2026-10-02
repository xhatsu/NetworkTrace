import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { ArrowRight, Fingerprint, Globe2, Server } from "lucide-react";
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
import { api, queryString } from "../../api";
import { useFilters } from "../../App";
import { ErrorState, InteractiveMetricCard, Loading, Panel, chartTooltip, minMaxDownsample, n } from "../../components";
import { useI18n } from "../../i18n";
import { EntityLink } from "../../components/EntityLink";
import { AccessExplorer, type ExplorerFilters } from "../../components/AccessExplorer";
import type { EpisodeResponse } from "../../components/EpisodePrimitives";
import { entityPath } from "../../entityRoutes";
import { RecentChangesPanel } from "../Services";

type DetailTab = "services" | "apis" | "callers" | "ips" | "traces";
type ChartMetric = "tps" | "error" | "latency" | "bandwidth";
type ChartSeriesLine = {
  dataKey: string;
  label: string;
  color: string;
  width?: number;
  dashed?: boolean;
};
type ChartVariable = {
  lines: ChartSeriesLine[];
  formatAxis: (value: number) => string;
  minimumAxisMax: number;
  available: boolean;
};

type PerformancePoint = {
  bucket_start?: number;
  timestamp_ms?: number;
  requests?: number;
  rps?: number;
  tps?: number;
  baseline_rps?: number;
  expected_tps?: number;
  baseline_error_rate?: number;
  baseline_p95?: number;
  errors?: number;
  error_rate?: number;
  latency_p50?: number;
  latency_p95?: number;
  latency_p99?: number;
  request_bytes?: number;
  response_bytes?: number;
  request_bytes_samples?: number;
  response_bytes_samples?: number;
  request_bytes_per_second?: number;
  response_bytes_per_second?: number;
  bandwidth_bytes_per_second?: number;
};

type RelationshipItem = {
  source_ip: string;
  caller_service?: string;
  service?: string;
  api?: string;
  request_count?: number;
  error_count?: number;
  tps?: number;
  error_rate?: number;
  p95_latency_ms?: number;
  first_seen_ms?: number;
  last_seen_ms?: number;
  source_ip_role?: string;
  role_label?: string;
  attribution_confidence?: string;
  is_load_balancer?: boolean;
  is_new_ip?: boolean;
};

type RelationshipPage = {
  items: RelationshipItem[];
  next_cursor?: string | null;
};

type Aggregate = {
  requestCount: number;
  errorCount: number;
  tps: number;
  errorRate: number;
  p95: number;
  firstSeen?: number;
  lastSeen?: number;
};

type Party = Aggregate & { name: string; services: number; apis: number; callers: number; ips: number; role?: string; isNew?: boolean };

/** The IP rollup spells APIs "service/operation"; the operation alone is what entity routes use. */
function operationOf(item: RelationshipItem) {
  const api = item.api || "";
  const prefix = `${item.service || ""}/`;
  return item.service && api.startsWith(prefix) ? api.slice(prefix.length) : api;
}

/** Group the user's relationship rows by one dimension (Service, API, caller or source IP). */
function groupParties(items: RelationshipItem[], keyOf: (item: RelationshipItem) => string): Party[] {
  const grouped = new Map<string, RelationshipItem[]>();
  items.forEach((item) => {
    const key = keyOf(item);
    if (key) grouped.set(key, [...(grouped.get(key) || []), item]);
  });
  return [...grouped.entries()].map(([name, rows]) => ({
    name,
    ...aggregate(rows),
    services: new Set(rows.map((row) => row.service).filter(Boolean)).size,
    apis: new Set(rows.map((row) => `${row.service}|${operationOf(row)}`)).size,
    callers: new Set(rows.map((row) => row.caller_service).filter(Boolean)).size,
    ips: new Set(rows.map((row) => row.source_ip).filter(Boolean)).size,
    role: rows.find((row) => row.role_label)?.role_label || rows[0]?.source_ip_role,
    isNew: rows.some((row) => row.is_new_ip),
  })).sort((left, right) => right.requestCount - left.requestCount || left.name.localeCompare(right.name));
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, index) => index);

function finite(value: unknown) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatTps(value: number) {
  const rate = finite(value);
  return n(rate, rate === 0 ? 1 : rate < 0.01 ? 4 : rate < 0.1 ? 3 : rate < 1 ? 2 : 1);
}

function timestamp(value: unknown) {
  const parsed = finite(value);
  return parsed > 0 && parsed < 10_000_000_000 ? parsed * 1000 : parsed;
}

function aggregate(items: RelationshipItem[]): Aggregate {
  const requestCount = items.reduce((sum, item) => sum + finite(item.request_count), 0);
  const explicitErrors = items.reduce((sum, item) => sum + finite(item.error_count), 0);
  const estimatedErrors = items.reduce((sum, item) => sum + finite(item.request_count) * finite(item.error_rate), 0);
  const errorCount = explicitErrors || estimatedErrors;
  const firstSeenValues = items.map((item) => finite(item.first_seen_ms)).filter(Boolean);
  const lastSeenValues = items.map((item) => finite(item.last_seen_ms)).filter(Boolean);
  return {
    requestCount,
    errorCount,
    tps: items.reduce((sum, item) => sum + finite(item.tps), 0),
    errorRate: requestCount ? errorCount / requestCount : 0,
    p95: Math.max(0, ...items.map((item) => finite(item.p95_latency_ms))),
    firstSeen: firstSeenValues.length ? Math.min(...firstSeenValues) : undefined,
    lastSeen: lastSeenValues.length ? Math.max(...lastSeenValues) : undefined,
  };
}

function percent(value: number) {
  const normalized = finite(value);
  return `${(normalized * 100).toFixed(normalized > 0 && normalized < 0.001 ? 2 : 1)}%`;
}

function formatBytes(value: number) {
  const bytes = finite(value);
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${Math.round(bytes)} B`;
}

function formatRate(value: number) {
  return `${formatBytes(value)}/s`;
}

function formatTime(value?: number) {
  return value ? new Date(value).toLocaleString() : "—";
}

function compactTime(value: unknown) {
  return new Date(timestamp(value)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function MetricTile({ label, value, detail, valueClass = "text-ink" }: { label: string; value: string; detail: string; valueClass?: string }) {
  return (
    <div className="metric-panel p-3">
      <div className="text-xs font-semibold uppercase tracking-[.08em] text-muted">{label}</div>
      <div className={`mt-2 font-mono text-xl font-semibold tabular-nums ${valueClass}`}>{value}</div>
      <div className="mt-1 truncate text-xs text-muted" title={detail}>{detail}</div>
    </div>
  );
}


function ActiveHourHeatmapPanel({ hourlyActivity, heatmap, typicalWindow, t }: { hourlyActivity: any[]; heatmap: { cells: number[][]; maximum: number }; typicalWindow?: string; t: (key: string, fallback?: string) => string }) {
  return (
    <div data-testid="activity-heatmap-panel">
      <Panel className="h-full flex flex-col" title={t("Active-hour heatmap")} subtitle={`${t("Typical active window")}: ${typicalWindow || t("Not established")}`}>
      {hourlyActivity.length ? (
        <div data-testid="activity-heatmap-data" className="flex min-h-[230px] flex-1 flex-col p-2.5">
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="mb-1 grid grid-cols-[40px_repeat(24,1fr)] gap-0.5 text-center font-mono text-[10px] text-muted"><span />{HOURS.map((hour) => <span key={hour}>{hour % 3 === 0 ? String(hour).padStart(2, "0") : ""}</span>)}</div>
            <div className="grid flex-1 grid-rows-7 gap-0.5">{DAYS.map((day, dayIndex) => (
              <div key={day} className="grid grid-cols-[40px_repeat(24,1fr)] items-center gap-0.5">
                <span className="font-mono text-[10px] text-muted">{day}</span>
                {HOURS.map((hour) => {
                  const value = heatmap.cells[dayIndex][hour];
                  const opacity = heatmap.maximum ? Math.max(0.08, value / heatmap.maximum) : 0;
                  return <div key={hour} title={`${day} ${String(hour).padStart(2, "0")}:00 · ${n(value, 0)} ${t("requests")}`} className="h-full min-h-5 border border-line" style={{ backgroundColor: value ? `color-mix(in srgb, var(--accent) ${Math.round(opacity * 100)}%, transparent)` : "var(--surface)" }} />;
                })}
              </div>
            ))}</div>
          </div>
        </div>
      ) : <div data-testid="activity-heatmap-empty" className="grid min-h-[230px] flex-1 place-items-center px-4 text-center text-xs text-muted">{t("No historical activity profile has been established yet.")}</div>}
      </Panel>
    </div>
  );
}

function PerformanceSection({
  series,
  t,
  currentTps,
  baselineTps,
  currentErrorRate,
  baselineErrorRate,
  currentP95,
  baselineP95,
  currentBandwidth,
  baselineBandwidth,
  hasBandwidth,
  totalErrors,
  aggregateErrorRate,
  heatmapPanel,
  aside,
}: {
  series: Array<Record<string, any>>;
  t: (key: string, fallback?: string) => string;
  currentTps: number;
  baselineTps: number;
  currentErrorRate: number;
  baselineErrorRate: number;
  currentP95: number;
  baselineP95: number;
  currentBandwidth: number;
  baselineBandwidth: number;
  hasBandwidth: boolean;
  totalErrors: number;
  aggregateErrorRate: number;
  heatmapPanel: ReactNode;
  aside?: ReactNode;
}) {
  const [selectedMetric, setSelectedMetric] = useState<ChartMetric>("tps");
  const [hoveredPoint, setHoveredPoint] = useState<Record<string, any> | null>(null);
  const percentDelta = (current: number, baseline: number) => baseline > 0 ? ((current - baseline) / baseline) * 100 : null;
  const signedPercent = (value: number | null) => value == null ? t("Baseline unavailable", "Baseline không khả dụng") : `${value >= 0 ? "+" : ""}${value.toFixed(0)}% ${t("vs baseline")}`;
  const errorDelta = baselineErrorRate > 0 ? (currentErrorRate - baselineErrorRate) * 100 : null;
  const spark = (key: string) => series.map((point) => ({ timestamp_ms: point.timestamp_ms, value: finite(point[key]) }));

  // Enriched metrics for KPI StatCards
  const avgTps = series.length ? series.reduce((sum, p) => sum + finite(p.observed_tps), 0) / series.length : 0;
  const peakTps = series.length ? Math.max(...series.map((p) => finite(p.observed_tps))) : 0;
  const totalFailed = series.reduce((sum, p) => sum + finite(p.outcome_error), 0);

  const latestTelemetryPoint = [...series].reverse().find((point) => finite(point.requests) > 0) || series[series.length - 1];
  const renderSeries = useMemo(() => minMaxDownsample(series, "observed_tps"), [series]);
  const p50 = finite(latestTelemetryPoint?.latency_p50);
  const p99 = finite(latestTelemetryPoint?.latency_p99);
  const latestBandwidthPoint = [...series].reverse().find((point) => finite(point.request_samples) + finite(point.response_samples) > 0)
    || latestTelemetryPoint;
  const reqBytesSec = finite(latestBandwidthPoint?.request_bytes_per_second);
  const respBytesSec = finite(latestBandwidthPoint?.response_bytes_per_second);

  const statusTotal = (bucket: Record<string, any>) => finite(bucket.outcome_non_error) + finite(bucket.outcome_error);
  const statusSeries = useMemo(() => series.map((point, index) => {
    const total = statusTotal(point);
    const value = (key: string) => total ? finite(point[key]) / total * 100 : 0;
    return {
      ...point,
      __sourceIndex: index,
      outcome_non_error_pct: value("outcome_non_error"),
      outcome_error_pct: value("outcome_error"),
    };
  }), [series]);
  const inspectedPoint = hoveredPoint || latestTelemetryPoint;
  const inspectedTotal = inspectedPoint ? statusTotal(inspectedPoint) : 0;
  const inspectedStatus = inspectedPoint ? [
    [t("Non-error requests"), finite(inspectedPoint.outcome_non_error), "var(--good)"],
    [t("Failed requests"), finite(inspectedPoint.outcome_error), "var(--bad)"],
  ] as Array<[string, number, string]> : [];
  const inspect = (state: any) => {
    const index = Number(state?.activeTooltipIndex);
    const payloadPoint = state?.activePayload?.[0]?.payload;
    const chartX = Number(state?.chartX);
    const plotLeft = Number(state?.offset?.left);
    const plotWidth = Number(state?.offset?.width);
    const hasChartCoordinate = Number.isFinite(chartX) && Number.isFinite(plotLeft) && plotWidth > 0;
    const fraction = hasChartCoordinate ? Math.max(0, Math.min(1, (chartX - plotLeft) / plotWidth)) : 0;
    const activeTimestamp = hasChartCoordinate
      ? finite(series[0]?.timestamp_ms) + fraction * (finite(series[series.length - 1]?.timestamp_ms) - finite(series[0]?.timestamp_ms))
      : Number(state?.activeLabel);
    let rawIndex = Number(payloadPoint?.__sourceIndex ?? index);
    if (Number.isFinite(activeTimestamp) && series.length) {
      let low = 0;
      let high = series.length;
      while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (finite(series[middle].timestamp_ms) < activeTimestamp) low = middle + 1;
        else high = middle;
      }
      const right = Math.min(low, series.length - 1);
      const left = Math.max(0, right - 1);
      rawIndex = Math.abs(finite(series[left].timestamp_ms) - activeTimestamp) <= Math.abs(finite(series[right].timestamp_ms) - activeTimestamp)
        ? left : right;
    }
    setHoveredPoint(state?.isTooltipActive && Number.isInteger(rawIndex) && rawIndex >= 0 ? series[rawIndex] || null : null);
  };
  const selectMetric = (metric: ChartMetric) => {
    setSelectedMetric(metric);
    setHoveredPoint(null);
  };
  const tpsLines: ChartSeriesLine[] = [
    { dataKey: "observed_tps", label: t("Observed TPS"), color: "var(--series-1)", width: 2.4 },
    { dataKey: "expected_tps", label: t("Expected TPS"), color: "var(--series-2)", dashed: true, width: 1.5 },
  ];
  const seriesMaximum = (lines: ChartSeriesLine[]) => series.reduce(
    (maximum, point) => lines.reduce((value, line) => Math.max(value, finite(point[line.dataKey])), maximum), 0,
  );
  const tpsPeak = seriesMaximum(tpsLines);
  const tpsAxisMaximum = tpsPeak > 0 ? tpsPeak : 1;
  const tpsAxisDigits = tpsAxisMaximum < 1
    ? Math.min(8, Math.max(2, Math.ceil(-Math.log10(tpsAxisMaximum / 4)) + 1))
    : 1;
  const formatTpsAxis = (value: number) => n(value, tpsAxisDigits);
  const chartVariables: Record<ChartMetric, ChartVariable> = {
    tps: { lines: tpsLines, formatAxis: (value) => `${formatTpsAxis(value)} TPS`, minimumAxisMax: 0, available: true },
    error: {
      lines: [
        { dataKey: "error_rate", label: t("Observed error rate"), color: "var(--bad)", width: 2.2 },
        { dataKey: "baseline_error_rate", label: t("Baseline error rate"), color: "var(--bad)", dashed: true, width: 1.5 },
      ],
      formatAxis: (value) => `${n(value * 100, 0)}%`,
      minimumAxisMax: 0.05,
      available: true,
    },
    latency: {
      lines: [
        { dataKey: "latency_p50", label: "P50", color: "var(--good)", width: 1.5 },
        { dataKey: "latency_p95", label: "P95", color: "var(--warn)", width: 2.2 },
        { dataKey: "latency_p99", label: "P99", color: "var(--bad)", width: 1.5 },
      ],
      formatAxis: (value) => `${n(value, 0)}ms`,
      minimumAxisMax: 1,
      available: true,
    },
    bandwidth: {
      lines: [
        { dataKey: "request_bytes_per_second", label: t("Request bytes/s"), color: "var(--series-3)", width: 2 },
        { dataKey: "response_bytes_per_second", label: t("Response bytes/s"), color: "var(--entity-api)", width: 2 },
      ],
      formatAxis: (value) => formatRate(value),
      minimumAxisMax: 1,
      available: hasBandwidth,
    },
  };
  const selectedVariable = chartVariables[selectedMetric];
  const overlayLines = selectedMetric !== "tps" && selectedVariable.available ? selectedVariable.lines : [];
  const rightVariable = overlayLines.length ? selectedVariable : chartVariables.tps;
  const rightAxisMaximum = overlayLines.length
    ? Math.max(rightVariable.minimumAxisMax, seriesMaximum(rightVariable.lines) * 1.1)
    : tpsAxisMaximum;
  const chartLegend = [...tpsLines, ...overlayLines];

  return (
    <div className="space-y-3" role="tabpanel">
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
        <InteractiveMetricCard
          label="TPS"
          value={formatTps(currentTps)}
          detail={signedPercent(percentDelta(currentTps, baselineTps))}
          subDetail={`avg ${formatTps(avgTps)} · peak ${formatTps(peakTps)}`}
          data={spark("sparkline_tps")}
          color="var(--series-1)"
          selected={selectedMetric === "tps"}
          onSelect={() => selectMetric("tps")}
        />
        <InteractiveMetricCard
          label={t("Error rate")}
          value={percent(currentErrorRate)}
          detail={errorDelta == null ? `${t("Baseline")}: ${percent(baselineErrorRate)}` : `${errorDelta >= 0 ? "+" : ""}${errorDelta.toFixed(1)}pp ${t("vs baseline")}`}
          subDetail={`${n(totalFailed, 0)} ${t("failed requests")}`}
          data={spark("sparkline_error")}
          color="var(--bad)"
          selected={selectedMetric === "error"}
          onSelect={() => selectMetric("error")}
          valueClass={currentErrorRate >= 0.05 ? "text-bad" : "text-ink"}
        />
        <InteractiveMetricCard
          label="P95 latency"
          value={`${n(currentP95, 0)} ms`}
          detail={signedPercent(percentDelta(currentP95, baselineP95))}
          subDetail={`p50 ${n(p50, 0)} · p99 ${n(p99, 0)}`}
          data={spark("sparkline_p95")}
          color="var(--warn)"
          selected={selectedMetric === "latency"}
          onSelect={() => selectMetric("latency")}
          valueClass={currentP95 >= 1000 ? "text-warn" : "text-ink"}
        />
        <InteractiveMetricCard
          label={t("Bandwidth")}
          value={hasBandwidth ? formatRate(currentBandwidth) : t("Unavailable", "Không có dữ liệu")}
          detail={hasBandwidth ? signedPercent(percentDelta(currentBandwidth, baselineBandwidth)) : "—"}
          subDetail={hasBandwidth ? `↑ ${formatBytes(reqBytesSec)}/s · ↓ ${formatBytes(respBytesSec)}/s` : undefined}
          data={hasBandwidth ? spark("sparkline_bandwidth") : []}
          color="var(--entity-api)"
          selected={selectedMetric === "bandwidth"}
          onSelect={() => selectMetric("bandwidth")}
          valueClass="text-entity-api"
        />
      </div>

      <div className="grid grid-cols-1 items-stretch gap-3 lg:grid-cols-5">
        <Panel className={aside ? "h-full min-w-0 lg:col-span-3" : "col-span-full h-full min-w-0"} title={t("TPS vs Expected", "TPS so với Expected")} subtitle={t("TPS on left · selected KPI on right", "TPS trục trái · KPI được chọn trục phải")}>
          {series.length ? (
            <div className="space-y-0">
              <div className="flex h-8 min-w-0 items-center gap-4 overflow-x-auto whitespace-nowrap px-3 text-[10px] text-muted">
                {chartLegend.map(({ label, color, dashed }) => <span key={label}><span className={`mr-1 inline-block w-3 border-t-2 align-middle ${dashed ? "border-dashed" : ""}`} style={{ borderColor: color }} />{label}</span>)}
              </div>
              <div className="relative h-[230px] px-2 pb-1 pt-1">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart syncId="user-activity-timeline" syncMethod="value" data={renderSeries} onMouseMove={inspect} onMouseLeave={() => setHoveredPoint(null)} margin={{ top: 6, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={52} tick={{ fill: "var(--muted)", fontSize: 10 }} tickFormatter={compactTime} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                  <YAxis yAxisId="tps" width={48} domain={[0, tpsAxisMaximum]} ticks={[0, 0.25, 0.5, 0.75, 1].map((fraction) => tpsAxisMaximum * fraction)} allowDataOverflow tick={{ fill: "var(--muted)", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(value) => formatTpsAxis(Number(value))} />
                  <YAxis yAxisId="metric" orientation="right" width={78} domain={[0, rightAxisMaximum]} allowDataOverflow tick={false} axisLine={false} tickLine={false} />
                  <Tooltip content={() => null} />
                  {tpsLines.map((line) => <Line key={line.dataKey} yAxisId="tps" type="linear" dataKey={line.dataKey} name={line.label} stroke={line.color} strokeWidth={line.width} strokeDasharray={line.dashed ? "5 4" : undefined} dot={false} activeDot={line.dataKey === "observed_tps" ? { r: 4, fill: "var(--text)", stroke: line.color } : false} connectNulls={false} isAnimationActive={false} />)}
                  {overlayLines.map((line) => <Line key={line.dataKey} yAxisId="metric" type="linear" dataKey={line.dataKey} name={line.label} stroke={line.color} strokeWidth={line.width} strokeDasharray={line.dashed ? "5 4" : undefined} dot={false} isAnimationActive={false} />)}
                </LineChart>
              </ResponsiveContainer>
              <div data-testid="activity-right-axis" aria-label={t("Selected metric scale", "Thang đo KPI được chọn")} className="pointer-events-none absolute bottom-[33px] right-[24px] top-[11px] flex w-[70px] flex-col justify-between text-left text-[10px] text-muted">
                {[1, 0.75, 0.5, 0.25, 0].map((fraction) => <span key={fraction}>{rightVariable.formatAxis(rightAxisMaximum * fraction)}</span>)}
              </div>
              </div>

              <div className="border-t border-line px-3 py-1.5 text-[10px] text-muted">
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono">
                  <span>{inspectedPoint ? compactTime(inspectedPoint.timestamp_ms) : "—"}</span>
                  <span>TPS {formatTps(finite(inspectedPoint?.observed_tps))} / {formatTps(finite(inspectedPoint?.expected_tps))}</span>
                  <span>{t("Error rate")} {percent(finite(inspectedPoint?.error_rate))}</span>
                  <span>P50/P95/P99 {n(finite(inspectedPoint?.latency_p50), 0)}/{n(finite(inspectedPoint?.latency_p95), 0)}/{n(finite(inspectedPoint?.latency_p99), 0)} ms</span>
                  {hasBandwidth && <span>{t("Bandwidth")} ↑{formatRate(finite(inspectedPoint?.request_bytes_per_second))} ↓{formatRate(finite(inspectedPoint?.response_bytes_per_second))}</span>}
                </div>
                <div className="mt-0.5 text-muted">{n(totalErrors, 0)} {t("failed requests")} · {percent(aggregateErrorRate)} {t("window error rate")}</div>
              </div>
            </div>
          ) : <div className="grid h-[320px] place-items-center text-xs text-muted">{t("No telemetry points in the selected window")}</div>}
        </Panel>
        {aside && <div className="min-w-0 lg:col-span-2">{aside}</div>}
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <Panel className="flex h-full flex-col" title={t("Request outcomes")} subtitle={t("100% distribution from worker metric buckets")}>
          {series.length ? <>
            <div className="flex flex-wrap gap-x-3 gap-y-1 px-3 py-2 text-[10px] text-muted">
              {inspectedStatus.map(([label, , color]) => <span key={label} className="inline-flex items-center gap-1"><span className="h-2 w-2" style={{ backgroundColor: color }} />{label}</span>)}
            </div>
            <div className="min-h-[230px] flex-1 px-2 pb-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart syncId="user-activity-timeline" syncMethod="value" data={statusSeries} barCategoryGap={0} onMouseMove={inspect} onMouseLeave={() => setHoveredPoint(null)} margin={{ top: 5, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={48} tick={{ fill: "var(--muted)", fontSize: 10 }} tickFormatter={compactTime} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                  <YAxis width={48} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: "var(--muted)", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(value) => `${value}%`} />
                  <Tooltip content={() => null} />
                  <Bar dataKey="outcome_non_error_pct" stackId="status" fill="var(--good)" isAnimationActive={false} />
                  <Bar dataKey="outcome_error_pct" stackId="status" fill="var(--bad)" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="border-t border-line px-3 py-1.5 text-[10px] font-mono text-muted">
              <div>{inspectedPoint ? compactTime(inspectedPoint.timestamp_ms) : "—"}</div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                {inspectedStatus.map(([label, value, color]) => <span key={label} style={{ color }}>{label} {inspectedTotal ? `${(value / inspectedTotal * 100).toFixed(1)}%` : "0%"} ({n(value, 0)})</span>)}
              </div>
            </div>
          </> : <div className="grid min-h-[320px] flex-1 place-items-center px-4 text-center text-xs text-muted">{t("No telemetry points in the selected window")}</div>}
        </Panel>
        {heatmapPanel}
      </div>
    </div>
  );
}

export function UserActivityWorkspace() {
  const { principal, profile } = useOutletContext<{ principal: string; profile: any }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [detailTab, setDetailTab] = useState<DetailTab>("services");
  const [accessFilters, setAccessFilters] = useState<ExplorerFilters>({});

  const principalType = String(profile?.principal_type || "unknown");
  const isHuman = principalType === "human";
  const principalRole = isHuman
    ? t("User", "User")
    : principalType === "unknown"
      ? t("Observed Principal", "Principal quan sát được")
      : t("Credential", "Credential");

  useEffect(() => {
    setDetailTab("services");
    setAccessFilters({});
  }, [principal]);

  const qs = queryString(filters);
  const changesQuery = useQuery({
    queryKey: ["user-recent-changes", principal, qs],
    queryFn: () => api<EpisodeResponse>(`/api/v1/changes?${queryString(filters, { principal, limit: "10" })}`),
    enabled: !!principal,
  });
  const tracesQuery = useQuery({
    queryKey: ["user-traces", principal, qs],
    queryFn: () => api<{ items: any[]; count: number }>(`/api/v1/traces?${queryString(filters, { principal, account: principal, limit: "10" })}`),
    enabled: !!principal,
  });

  const metricsQuery = useQuery({
    queryKey: ["user-metric-buckets", principal, filters],
    queryFn: () => api<PerformancePoint[]>(`/api/v1/principals/${encodeURIComponent(principal)}/metrics?${queryString(filters, { bucket: "300" })}`),
    enabled: !!principal,
  });

  const baselineQuery = useQuery({
    queryKey: ["user-worker-baseline-series", principal, filters],
    queryFn: () => api<{ items: Array<{ timestamp_ms: number; baseline_rps: number }> }>(`/api/v1/dashboard/series?${queryString(filters, { account: principal })}`),
    enabled: !!principal,
  });

  const relationshipQuery = useInfiniteQuery({
    queryKey: ["user-activity-relationships", principal, filters],
    initialPageParam: "",
    queryFn: ({ pageParam }) => api<RelationshipPage>(
      `/api/v1/topology/principals/${encodeURIComponent(principal)}/ips?${queryString(filters, {
        page_size: "500",
        cursor: pageParam || undefined,
      })}`,
    ),
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
    enabled: !!principal,
  });

  const metricSeries = metricsQuery.data || [];
  const baselineSeries = baselineQuery.data?.items || [];
  const mergedSeries = useMemo(() => {
    const parseFilterTime = (value: string) => Number.isFinite(Number(value)) ? timestamp(value) : Date.parse(value);
    const start = parseFilterTime(filters.start);
    const end = parseFilterTime(filters.end);
    const bucketMs = Number.isFinite(start) && Number.isFinite(end) && end - start > 192 * 3_600_000
      ? 3_600_000 : 300_000;
    const bucketStart = (point: PerformancePoint) => Math.floor(timestamp(point.timestamp_ms ?? point.bucket_start) / bucketMs) * bucketMs;
    const metricByBucket = new Map<number, {
      requests: number;
      errors: number;
      latency_p50: number;
      latency_p95: number;
      latency_p99: number;
      request_bytes: number;
      response_bytes: number;
      request_bytes_samples: number;
      response_bytes_samples: number;
    }>();
    metricSeries.forEach((point) => {
      const key = bucketStart(point);
      const current = metricByBucket.get(key) || {
        requests: 0, errors: 0, latency_p50: 0, latency_p95: 0, latency_p99: 0,
        request_bytes: 0, response_bytes: 0, request_bytes_samples: 0, response_bytes_samples: 0,
      };
      current.requests += finite(point.requests);
      current.errors += finite(point.errors);
      current.latency_p50 = Math.max(current.latency_p50, finite(point.latency_p50));
      current.latency_p95 = Math.max(current.latency_p95, finite(point.latency_p95));
      current.latency_p99 = Math.max(current.latency_p99, finite(point.latency_p99));
      current.request_bytes += finite(point.request_bytes);
      current.response_bytes += finite(point.response_bytes);
      current.request_bytes_samples += finite(point.request_bytes_samples);
      current.response_bytes_samples += finite(point.response_bytes_samples);
      metricByBucket.set(key, current);
    });
    const baselineByBucket = new Map(baselineSeries.map((point) => [bucketStart(point), finite(point.baseline_rps)]));
    const measuredRates = [...metricByBucket.values()].map((point) => point.requests / (bucketMs / 1000));
    const median = (values: number[]) => {
      const sorted = [...values].sort((left, right) => left - right);
      return sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
    };
    const fallbackBaseline = median([...baselineByBucket.values()].filter((value) => value > 0)) || median(measuredRates);
    const fallbackErrorRate = median([...metricByBucket.values()].map((point) => point.requests ? point.errors / point.requests : 0));
    const fallbackP95 = median([...metricByBucket.values()].map((point) => point.latency_p95));
    return [...metricByBucket.keys()].sort((left, right) => left - right).map((key) => {
      const metric = metricByBucket.get(key);
      const seconds = bucketMs / 1000;
      const requests = metric?.requests || 0;
      const requestBytes = metric?.request_bytes || 0;
      const responseBytes = metric?.response_bytes || 0;
      return {
        bucket_start: key,
        timestamp_ms: key,
        requests,
        rps: requests / seconds,
        baseline_rps: baselineByBucket.get(key) ?? fallbackBaseline,
        baseline_error_rate: fallbackErrorRate,
        baseline_p95: fallbackP95,
        ...(metric ? {
          errors: metric.errors,
          error_rate: requests ? metric.errors / requests : 0,
          latency_p50: metric.latency_p50,
          latency_p95: metric.latency_p95,
          latency_p99: metric.latency_p99,
        } : {}),
        request_bytes: requestBytes,
        response_bytes: responseBytes,
        request_bytes_samples: metric?.request_bytes_samples || 0,
        response_bytes_samples: metric?.response_bytes_samples || 0,
        request_bytes_per_second: requestBytes / seconds,
        response_bytes_per_second: responseBytes / seconds,
        bandwidth_bytes_per_second: (requestBytes + responseBytes) / seconds,
      };
    });
  }, [metricSeries, baselineSeries, filters.start, filters.end]);
  const series = useMemo(() => mergedSeries.map((point) => {
    return {
      ...point,
      timestamp_ms: timestamp(point.timestamp_ms ?? point.bucket_start),
      observed_tps: finite(point.rps),
      expected_tps: finite(point.baseline_rps),
      sparkline_tps: finite(point.rps),
      sparkline_error: finite(point.error_rate),
      sparkline_p95: finite(point.latency_p95),
      sparkline_bandwidth: finite(point.bandwidth_bytes_per_second),
      outcome_non_error: Math.max(0, finite(point.requests) - finite(point.errors)),
      outcome_error: finite(point.errors),
    };
  }), [mergedSeries]);

  const allRelationships = useMemo(
    () => relationshipQuery.data?.pages.flatMap((page) => page.items || []) || [],
    [relationshipQuery.data],
  );

  const windowSec = useMemo(() => {
    const parse = (value: string) => Number.isFinite(Number(value)) ? timestamp(value) : Date.parse(value);
    return Math.max(1, (parse(filters.end) - parse(filters.start)) / 1000);
  }, [filters.end, filters.start]);
  const serviceParties = useMemo(() => groupParties(allRelationships, (item) => item.service || ""), [allRelationships]);
  const apiParties = useMemo(() => groupParties(allRelationships, (item) => item.service && operationOf(item) ? `${item.service}\u0000${operationOf(item)}` : ""), [allRelationships]);
  const callerParties = useMemo(() => groupParties(allRelationships, (item) => item.caller_service || ""), [allRelationships]);
  const ipParties = useMemo(() => groupParties(allRelationships, (item) => item.source_ip || ""), [allRelationships]);

  const totalRequests = series.reduce((sum, point) => sum + finite(point.requests), 0);
  const totalErrors = series.reduce((sum, point) => sum + finite(point.errors), 0);
  const aggregateErrorRate = totalRequests ? totalErrors / totalRequests : 0;
  const latestPoint = series[series.length - 1];
  const latestTelemetryPoint = [...series].reverse().find((point) => finite(point.requests) > 0) || latestPoint;
  const currentTps = finite(latestTelemetryPoint?.observed_tps);
  const currentErrorRate = finite(latestTelemetryPoint?.error_rate);
  const currentP95 = finite(latestTelemetryPoint?.latency_p95);
  const hasBandwidth = series.some((point) => finite(point.request_bytes_samples) + finite(point.response_bytes_samples) > 0);
  const baselineTps = finite(latestTelemetryPoint?.expected_tps);
  const baselineErrorRate = finite(latestTelemetryPoint?.baseline_error_rate);
  const baselineP95 = finite(latestTelemetryPoint?.baseline_p95);
  const bandwidthPoints = series.filter((point) => finite(point.request_bytes_samples) + finite(point.response_bytes_samples) > 0);
  const latestBandwidthPoint = bandwidthPoints[bandwidthPoints.length - 1];
  const currentBandwidth = finite(latestBandwidthPoint?.bandwidth_bytes_per_second);
  const bandwidthRates = bandwidthPoints.map((point) => finite(point.bandwidth_bytes_per_second)).sort((left, right) => left - right);
  const baselineBandwidth = bandwidthRates.length ? bandwidthRates[Math.floor(bandwidthRates.length / 2)] : 0;
  const percentDelta = (currentValue: number, baselineValue: number) => baselineValue > 0 ? ((currentValue - baselineValue) / baselineValue) * 100 : null;
  const hourlyActivity = useMemo(() => {
    const hours = new Map<string, { day_of_week: number; hour_of_day: number; observation_count: number }>();
    metricSeries.forEach((point) => {
      const date = new Date(timestamp(point.timestamp_ms ?? point.bucket_start));
      if (!Number.isFinite(date.getTime())) return;
      const day_of_week = (date.getUTCDay() + 6) % 7 + 1;
      const hour_of_day = date.getUTCHours();
      const key = `${day_of_week}:${hour_of_day}`;
      const row = hours.get(key) || { day_of_week, hour_of_day, observation_count: 0 };
      row.observation_count += finite(point.requests);
      hours.set(key, row);
    });
    return [...hours.values()];
  }, [metricSeries]);
  const heatmap = useMemo(() => {
    const cells = Array.from({ length: 7 }, () => Array(24).fill(0));
    let maximum = 0;
    hourlyActivity.forEach((row) => {
      const rawDay = finite(row.day_of_week);
      const dayIndex = rawDay >= 1 && rawDay <= 7 ? rawDay - 1 : Math.max(0, Math.min(6, rawDay));
      const hour = Math.max(0, Math.min(23, finite(row.hour_of_day)));
      const value = finite(row.observation_count);
      cells[dayIndex][hour] += value;
      maximum = Math.max(maximum, cells[dayIndex][hour]);
    });
    return { cells, maximum };
  }, [hourlyActivity]);

  const tabs: Array<[DetailTab, string, number]> = [
    ["services", "Services", serviceParties.length],
    ["apis", "APIs", apiParties.length],
    ["callers", t("Caller services"), callerParties.length],
    ["ips", t("Source IPs", "IP nguồn"), ipParties.length],
    ["traces", t("Traces"), tracesQuery.data?.items?.length || 0],
  ];
  const traces = tracesQuery.data?.items || [];
  const search = `?${qs}`;

  return (
    <div className="space-y-3">
      <PerformanceSection
        key={principal}
        series={series}
        t={t}
        currentTps={currentTps}
        baselineTps={baselineTps}
        currentErrorRate={currentErrorRate}
        baselineErrorRate={baselineErrorRate}
        currentP95={currentP95}
        baselineP95={baselineP95}
        currentBandwidth={currentBandwidth}
        baselineBandwidth={baselineBandwidth}
        hasBandwidth={hasBandwidth}
        totalErrors={totalErrors}
        aggregateErrorRate={aggregateErrorRate}
        heatmapPanel={(
          <ActiveHourHeatmapPanel
            hourlyActivity={hourlyActivity}
            heatmap={heatmap}
            typicalWindow={profile?.typical_active_window}
            t={t}
          />
        )}
        aside={(
          <RecentChangesPanel
            query={changesQuery}
            viewAllHref={entityPath({ kind: "user", principal, tab: "changes" }) + search}
            search={search}
            emptyText={t("No behavior changes for this user in the current window.", "Không có thay đổi hành vi của user này trong khoảng hiện tại.")}
          />
        )}
      />

      <Panel
        title={`${t("Access for", "Quyền truy cập của")} ${principal}`}
        subtitle={`${principalRole} (${principalType.replaceAll("_", " ")}) · ${t(
          "Unusual access first, then the Caller Services, Services and APIs of this identity; select a row to see its direct relationships",
          "Truy cập bất thường trước, sau đó là Caller Service, Service và API của danh tính này; chọn một dòng để xem quan hệ trực tiếp",
        )}`}
      >
        <div data-testid="user-access-explorer">
          <AccessExplorer lockedCredential={principal} filters={accessFilters} onFilters={setAccessFilters} />
        </div>
      </Panel>

      <div className="flex flex-wrap gap-2 border-b border-line pb-3 pt-2" role="group" aria-label={t("User detail views", "Góc nhìn User")}>
        {tabs.map(([value, label, count]) => (
          <button key={value} type="button" aria-pressed={detailTab === value} onClick={() => setDetailTab(value)}
            className={`rounded-ctl border px-3 py-2 text-xs ${detailTab === value ? "border-accent bg-accent-soft text-ink font-semibold" : "border-line text-muted hover:text-ink"}`}>
            {label} <span className="ml-2 font-mono">{count}</span>
          </button>
        ))}
      </div>

      {detailTab !== "traces" && (
        relationshipQuery.isLoading ? <Loading /> : relationshipQuery.error ? <ErrorState message={(relationshipQuery.error as Error).message} /> : (
          <Panel
            title={{ services: t("Services this identity reached", "Service danh tính này đã gọi"), apis: t("APIs this identity used", "API danh tính này đã dùng"), callers: t("Caller services sending this identity", "Caller Service gửi danh tính này"), ips: t("Source IP evidence", "Bằng chứng IP nguồn") }[detailTab]}
            subtitle={t("Worker five-minute IP rollup for the selected window · supporting evidence, open a Trace to confirm the request chain", "Rollup IP năm phút của worker trong khoảng đã chọn · bằng chứng hỗ trợ, mở Trace để xác nhận chuỗi request")}
            action={<span className="font-mono text-[11px] text-muted">{allRelationships.length} {t("relationships")}</span>}
          >
            <PartyTable
              kind={detailTab}
              rows={{ services: serviceParties, apis: apiParties, callers: callerParties, ips: ipParties }[detailTab]}
              windowSec={windowSec}
              search={search}
              onOpen={(path) => nav(path)}
              t={t}
            />
            {relationshipQuery.hasNextPage && (
              <div className="border-t border-line p-2 text-center"><button type="button" disabled={relationshipQuery.isFetchingNextPage} onClick={() => relationshipQuery.fetchNextPage()} className="toolbar-control px-3 py-1 text-xs disabled:opacity-50">{relationshipQuery.isFetchingNextPage ? t("Loading…") : t("Load more relationships")}</button></div>
            )}
          </Panel>
        )
      )}

      {detailTab === "traces" && (
        <Panel
          title={t("Representative Traces")}
          subtitle={t("Recent distributed traces carrying this identity", "Trace phân tán gần đây mang danh tính này")}
          action={<Link to={`/traces?${queryString(filters, { principal, account: principal })}`} className="text-[11px] font-semibold text-ink hover:underline">{t("Open in Traces")} <ArrowRight size={12} className="inline" /></Link>}
        >
          {tracesQuery.isLoading ? <Loading /> : tracesQuery.isError ? <ErrorState message={(tracesQuery.error as Error).message} /> : traces.length ? (
            <div className="overflow-auto">
              <table className="w-full text-left text-xs">
                <thead><tr className="border-b border-line">
                  <th className="table-head px-3 py-2">{t("Trace ID")}</th>
                  <th className="table-head px-3 py-2">Service</th>
                  <th className="table-head px-3 py-2">{t("Operation")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Duration")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Status")}</th>
                </tr></thead>
                <tbody className="divide-y divide-line">
                  {traces.map((tr: any) => (
                    <tr key={tr.trace_id || tr.id} onClick={() => nav(`/traces/${encodeURIComponent(tr.trace_id || tr.id)}`)} className="cursor-pointer transition hover:bg-hover">
                      <td className="px-3 py-2 font-mono text-ink">{(tr.trace_id || tr.id || "").slice(0, 16)}…</td>
                      <td className="px-3 text-ink">{tr.service || tr.service_name || tr.target_service || "—"}</td>
                      <td className="px-3 font-mono text-muted">{tr.operation || tr.name || "—"}</td>
                      <td className="px-3 text-right font-mono tabular-nums text-ink">{tr.duration_ms != null ? `${Number(tr.duration_ms).toFixed(1)} ms` : "—"}</td>
                      <td className="px-3 text-right font-mono">
                        <span className={`rounded-ctl border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${String(tr.status_code || tr.http_status || tr.status).startsWith("5") ? "border-bad text-bad" : "border-good text-good"}`}>{tr.status_code || tr.http_status || tr.status || "OK"}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="p-6 text-center text-xs text-muted">{t("No recent traces recorded for this user.", "Không có Trace gần đây cho user này.")}</div>}
        </Panel>
      )}
    </div>
  );
}

function PartyTable({ kind, rows, windowSec, search, onOpen, t }: {
  kind: Exclude<DetailTab, "traces">;
  rows: Party[];
  windowSec: number;
  search: string;
  onOpen: (path: string) => void;
  t: (key: string, fallback?: string) => string;
}) {
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 15;
  const lastPage = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1);
  const current = Math.min(page, lastPage);
  const visible = rows.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);
  const split = (name: string) => { const [service, operation] = name.split("\u0000"); return { service, operation }; };
  const pathOf = (row: Party) => kind === "apis" ? entityPath({ kind: "api", ...split(row.name) }) + search
    : kind === "ips" ? "" : entityPath({ kind: "service", name: row.name }) + search;
  const countHeads: Record<typeof kind, string[]> = {
    services: ["APIs", t("Callers", "Caller"), "IPs"],
    apis: [t("Callers", "Caller"), "IPs"],
    callers: ["Services", "APIs", "IPs"],
    ips: ["Services", "APIs", t("Callers", "Caller")],
  };
  const countsOf = (row: Party) => ({ services: [row.apis, row.callers, row.ips], apis: [row.callers, row.ips], callers: [row.services, row.apis, row.ips], ips: [row.services, row.apis, row.callers] }[kind]);
  const firstHead = { services: "Service", apis: "API", callers: t("Caller Service"), ips: "IP" }[kind];
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-xs">
          <thead><tr className="border-b border-line">
            {[firstHead, t("Requests"), t("Avg TPS", "TPS TB"), t("Error rate"), t("Max bucket P95", "P95 bucket lớn nhất"), ...countHeads[kind], t("Last seen")].map((heading, i) => <th key={heading} className={`table-head px-3 py-2 ${i ? "text-right" : ""}`}>{heading}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-line">
            {visible.map((row) => {
              const path = pathOf(row);
              const label = kind === "apis" ? split(row.name).operation : row.name;
              return (
                <tr key={row.name} onClick={path ? () => onOpen(path) : undefined} className={`transition hover:bg-hover ${path ? "cursor-pointer" : ""}`}>
                  <td className="max-w-[360px] px-3 py-2">
                    <span className="flex items-center gap-1.5 font-mono">
                      {kind === "apis" ? <Fingerprint size={12} className="shrink-0 text-entity-api" /> : kind === "ips" ? <Globe2 size={12} className="shrink-0 text-muted" /> : <Server size={12} className="shrink-0 text-entity-service" />}
                      {kind === "apis" ? <EntityLink entity={{ kind: "api", ...split(row.name) }} search={search} className="truncate text-entity-api hover:underline" title={label}>{label}</EntityLink>
                        : kind === "ips" ? <span className="text-ink">{row.name}</span>
                        : <EntityLink entity={{ kind: "service", name: row.name }} search={search} className="truncate text-entity-service hover:underline">{row.name}</EntityLink>}
                      {row.isNew && kind === "ips" && <span className="border border-warn px-1 text-[10px] text-warn font-semibold">NEW</span>}
                    </span>
                    {kind === "apis" && <span className="text-[10px] text-muted">{split(row.name).service}</span>}
                    {kind === "ips" && row.role && <span className="text-[10px] text-muted">{row.role}</span>}
                  </td>
                  <td className="px-3 text-right font-mono tabular-nums text-ink">{n(row.requestCount, 0)}</td>
                  <td className="px-3 text-right font-mono tabular-nums text-ink">{n(row.requestCount / windowSec, 4)}</td>
                  <td className={`px-3 text-right font-mono tabular-nums ${row.errorRate > 0 ? "text-bad" : "text-muted"}`}>{percent(row.errorRate)}</td>
                  <td className="px-3 text-right font-mono tabular-nums text-entity-user">{n(row.p95, 1)} ms</td>
                  {countsOf(row).map((value, i) => <td key={i} className="px-3 text-right font-mono tabular-nums">{n(value, 0)}</td>)}
                  <td className="px-3 text-right text-muted">{row.lastSeen ? new Date(row.lastSeen).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                </tr>
              );
            })}
            {!rows.length && <tr><td colSpan={9} className="px-3 py-8 text-center text-muted">{t("No relationships observed for this identity in this window.", "Không có quan hệ nào của danh tính này trong khoảng đã chọn.")}</td></tr>}
          </tbody>
        </table>
      </div>
      {rows.length > PAGE_SIZE && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-[11px] text-muted">
          <span>{current * PAGE_SIZE + 1}–{Math.min((current + 1) * PAGE_SIZE, rows.length)} / {rows.length}</span>
          <div className="flex items-center gap-2"><button className="btn disabled:opacity-40" disabled={current === 0} onClick={() => setPage(current - 1)}>{t("Previous", "Trước")}</button><span>{current + 1} / {lastPage + 1}</span><button className="btn disabled:opacity-40" disabled={current === lastPage} onClick={() => setPage(current + 1)}>{t("Next", "Tiếp")}</button></div>
        </div>
      )}
    </>
  );
}
