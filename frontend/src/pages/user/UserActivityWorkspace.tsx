import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useOutletContext } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Clock3,
  ExternalLink,
  Fingerprint,
  Globe2,
  KeyRound,
  Search,
  Server,
  UserRound,
  X,
} from "lucide-react";
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

type ActivityView = "behavior" | "access";
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
  baseline_error_rate?: number;
  baseline_p95?: number;
  errors?: number;
  error_rate?: number;
  latency_p50?: number;
  latency_p95?: number;
  latency_p99?: number;
  request_bytes?: number;
  response_bytes?: number;
  request_bytes_per_second?: number;
  response_bytes_per_second?: number;
  bandwidth_bytes_per_second?: number;
};

type BandwidthResponse = {
  available?: boolean;
  metrics?: { bandwidth_bytes_per_second?: number };
  series?: Array<PerformancePoint & { request_count?: number; request_samples?: number; response_samples?: number }>;
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
  request_bytes?: number;
  response_bytes?: number;
  bandwidth_bytes_per_second?: number;
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
  requestBytes: number;
  responseBytes: number;
  bandwidth: number;
  firstSeen?: number;
  lastSeen?: number;
};

type AccessChoice = Aggregate & {
  name: string;
  items: RelationshipItem[];
  relationCount: number;
};

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
    requestBytes: items.reduce((sum, item) => sum + finite(item.request_bytes), 0),
    responseBytes: items.reduce((sum, item) => sum + finite(item.response_bytes), 0),
    bandwidth: items.reduce((sum, item) => sum + finite(item.bandwidth_bytes_per_second), 0),
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

function MetricTile({ label, value, detail, valueClass = "text-[#d8d9da]" }: { label: string; value: string; detail: string; valueClass?: string }) {
  return (
    <div className="metric-panel p-3">
      <div className="text-[10px] font-semibold uppercase tracking-[.08em] text-[#a7a9ab]">{label}</div>
      <div className={`mt-2 font-mono text-xl font-semibold tabular-nums ${valueClass}`}>{value}</div>
      <div className="mt-1 truncate text-[10px] text-[#7b7d80]" title={detail}>{detail}</div>
    </div>
  );
}

function BoardColumn({ step, title, subtitle, children }: { step: number; title: string; subtitle: string; children: ReactNode }) {
  return (
    <section className="min-h-[310px] border border-[#2a2d30] bg-[#0e0f12]">
      <header className="border-b border-[#2a2d30] px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="grid h-4 w-4 place-items-center rounded-full bg-[#34373b] font-mono text-[9px] text-[#d8d9da]">{step}</span>
          <h3 className="text-[10px] font-semibold uppercase tracking-[.08em] text-[#d8d9da]">{title}</h3>
        </div>
        <p className="mt-1 text-[9px] text-[#7b7d80]">{subtitle}</p>
      </header>
      <div className="max-h-[360px] overflow-y-auto p-2">{children}</div>
    </section>
  );
}

function ActiveHourHeatmapPanel({ hourlyActivity, heatmap, typicalWindow, t }: { hourlyActivity: any[]; heatmap: { cells: number[][]; maximum: number }; typicalWindow?: string; t: (key: string, fallback?: string) => string }) {
  return (
    <div data-testid="activity-heatmap-panel">
      <Panel className="h-full flex flex-col" title={t("Active-hour heatmap")} subtitle={`${t("Typical active window")}: ${typicalWindow || t("Not established")}`}>
      {hourlyActivity.length ? (
        <div data-testid="activity-heatmap-data" className="flex min-h-[230px] flex-1 flex-col p-2.5">
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="mb-1 grid grid-cols-[40px_repeat(24,1fr)] gap-0.5 text-center font-mono text-[9px] text-[#7b7d80]"><span />{HOURS.map((hour) => <span key={hour}>{hour % 3 === 0 ? String(hour).padStart(2, "0") : ""}</span>)}</div>
            <div className="grid flex-1 grid-rows-7 gap-0.5">{DAYS.map((day, dayIndex) => (
              <div key={day} className="grid grid-cols-[40px_repeat(24,1fr)] items-center gap-0.5">
                <span className="font-mono text-[9.5px] text-[#a7a9ab]">{day}</span>
                {HOURS.map((hour) => {
                  const value = heatmap.cells[dayIndex][hour];
                  const opacity = heatmap.maximum ? Math.max(0.08, value / heatmap.maximum) : 0;
                  return <div key={hour} title={`${day} ${String(hour).padStart(2, "0")}:00 · ${n(value, 0)} ${t("requests")}`} className="h-full min-h-5 border border-[#2a2d30]" style={{ backgroundColor: value ? `rgba(184,119,217,${opacity})` : "#0e0f12" }} />;
                })}
              </div>
            ))}</div>
          </div>
        </div>
      ) : <div data-testid="activity-heatmap-empty" className="grid min-h-[230px] flex-1 place-items-center px-4 text-center text-xs text-[#7b7d80]">{t("No historical activity profile has been established yet.")}</div>}
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
    [t("Non-error requests"), finite(inspectedPoint.outcome_non_error), "#73bf69"],
    [t("Failed requests"), finite(inspectedPoint.outcome_error), "#f2495c"],
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
    { dataKey: "observed_tps", label: t("Observed TPS"), color: "#5794f2", width: 2.4 },
    { dataKey: "baseline_tps", label: t("Baseline TPS"), color: "#7b7d80", dashed: true, width: 1.5 },
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
        { dataKey: "error_rate", label: t("Observed error rate"), color: "#f2495c", width: 2.2 },
        { dataKey: "baseline_error_rate", label: t("Baseline error rate"), color: "#f2495c", dashed: true, width: 1.5 },
      ],
      formatAxis: (value) => `${n(value * 100, 0)}%`,
      minimumAxisMax: 0.05,
      available: true,
    },
    latency: {
      lines: [
        { dataKey: "latency_p50", label: "P50", color: "#73bf69", width: 1.5 },
        { dataKey: "latency_p95", label: "P95", color: "#ff9830", width: 2.2 },
        { dataKey: "latency_p99", label: "P99", color: "#f2495c", width: 1.5 },
      ],
      formatAxis: (value) => `${n(value, 0)}ms`,
      minimumAxisMax: 1,
      available: true,
    },
    bandwidth: {
      lines: [
        { dataKey: "request_bytes_per_second", label: t("Request bytes/s"), color: "#b877d9", width: 2 },
        { dataKey: "response_bytes_per_second", label: t("Response bytes/s"), color: "#56b9a8", width: 2 },
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
          color="#5794f2"
          selected={selectedMetric === "tps"}
          onSelect={() => selectMetric("tps")}
          valueClass="text-[#5794f2]"
        />
        <InteractiveMetricCard
          label={t("Error rate")}
          value={percent(currentErrorRate)}
          detail={errorDelta == null ? `${t("Baseline")}: ${percent(baselineErrorRate)}` : `${errorDelta >= 0 ? "+" : ""}${errorDelta.toFixed(1)}pp ${t("vs baseline")}`}
          subDetail={`${n(totalFailed, 0)} ${t("failed requests")}`}
          data={spark("sparkline_error")}
          color="#f2495c"
          selected={selectedMetric === "error"}
          onSelect={() => selectMetric("error")}
          valueClass={currentErrorRate >= 0.05 ? "text-[#f2495c]" : "text-[#d8d9da]"}
        />
        <InteractiveMetricCard
          label="P95 latency"
          value={`${n(currentP95, 0)} ms`}
          detail={signedPercent(percentDelta(currentP95, baselineP95))}
          subDetail={`p50 ${n(p50, 0)} · p99 ${n(p99, 0)}`}
          data={spark("sparkline_p95")}
          color="#ff9830"
          selected={selectedMetric === "latency"}
          onSelect={() => selectMetric("latency")}
          valueClass={currentP95 >= 1000 ? "text-[#ff9830]" : "text-[#d8d9da]"}
        />
        <InteractiveMetricCard
          label={t("Bandwidth")}
          value={hasBandwidth ? formatRate(currentBandwidth) : t("Unavailable", "Không có dữ liệu")}
          detail={hasBandwidth ? signedPercent(percentDelta(currentBandwidth, baselineBandwidth)) : "—"}
          subDetail={hasBandwidth ? `↑ ${formatBytes(reqBytesSec)}/s · ↓ ${formatBytes(respBytesSec)}/s` : undefined}
          data={hasBandwidth ? spark("sparkline_bandwidth") : []}
          color="#56b9a8"
          selected={selectedMetric === "bandwidth"}
          onSelect={() => selectMetric("bandwidth")}
          valueClass="text-[#56b9a8]"
        />
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(300px,.85fr)]">
        <Panel className="h-full min-w-0" title={t("TPS vs Baseline", "TPS so với Baseline")} subtitle={t("TPS on left · selected KPI on right", "TPS trục trái · KPI được chọn trục phải")}>
          {series.length ? (
            <div className="space-y-0">
              <div className="flex h-8 min-w-0 items-center gap-4 overflow-x-auto whitespace-nowrap px-3 text-[10px] text-[#a7a9ab]">
                {chartLegend.map(({ label, color, dashed }) => <span key={label}><span className={`mr-1 inline-block w-3 border-t-2 align-middle ${dashed ? "border-dashed" : ""}`} style={{ borderColor: color }} />{label}</span>)}
              </div>
              <div className="relative h-[230px] px-2 pb-1 pt-1">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart syncId="user-activity-timeline" syncMethod="value" data={renderSeries} onMouseMove={inspect} onMouseLeave={() => setHoveredPoint(null)} margin={{ top: 6, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#303236" vertical={false} />
                  <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={52} tick={{ fill: "#7b7d80", fontSize: 10 }} tickFormatter={compactTime} axisLine={{ stroke: "#2a2d30" }} tickLine={false} />
                  <YAxis yAxisId="tps" width={48} domain={[0, tpsAxisMaximum]} ticks={[0, 0.25, 0.5, 0.75, 1].map((fraction) => tpsAxisMaximum * fraction)} allowDataOverflow tick={{ fill: "#7b7d80", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(value) => formatTpsAxis(Number(value))} />
                  <YAxis yAxisId="metric" orientation="right" width={78} domain={[0, rightAxisMaximum]} allowDataOverflow tick={false} axisLine={false} tickLine={false} />
                  <Tooltip content={() => null} />
                  {tpsLines.map((line) => <Line key={line.dataKey} yAxisId="tps" type="linear" dataKey={line.dataKey} name={line.label} stroke={line.color} strokeWidth={line.width} strokeDasharray={line.dashed ? "5 4" : undefined} dot={false} activeDot={line.dataKey === "observed_tps" ? { r: 4, fill: "#d8d9da", stroke: line.color } : false} connectNulls={false} isAnimationActive={false} />)}
                  {overlayLines.map((line) => <Line key={line.dataKey} yAxisId="metric" type="linear" dataKey={line.dataKey} name={line.label} stroke={line.color} strokeWidth={line.width} strokeDasharray={line.dashed ? "5 4" : undefined} dot={false} isAnimationActive={false} />)}
                </LineChart>
              </ResponsiveContainer>
              <div data-testid="activity-right-axis" aria-label={t("Selected metric scale", "Thang đo KPI được chọn")} className="pointer-events-none absolute bottom-[33px] right-[24px] top-[11px] flex w-[70px] flex-col justify-between text-left text-[10px] text-[#7b7d80]">
                {[1, 0.75, 0.5, 0.25, 0].map((fraction) => <span key={fraction}>{rightVariable.formatAxis(rightAxisMaximum * fraction)}</span>)}
              </div>
              </div>

              <div className="border-t border-[#2a2d30] px-3 py-1.5 text-[10px] text-[#a7a9ab]">
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono">
                  <span>{inspectedPoint ? compactTime(inspectedPoint.timestamp_ms) : "—"}</span>
                  <span>TPS {formatTps(finite(inspectedPoint?.observed_tps))} / {formatTps(finite(inspectedPoint?.baseline_tps))}</span>
                  <span>{t("Error rate")} {percent(finite(inspectedPoint?.error_rate))}</span>
                  <span>P50/P95/P99 {n(finite(inspectedPoint?.latency_p50), 0)}/{n(finite(inspectedPoint?.latency_p95), 0)}/{n(finite(inspectedPoint?.latency_p99), 0)} ms</span>
                  {hasBandwidth && <span>{t("Bandwidth")} ↑{formatRate(finite(inspectedPoint?.request_bytes_per_second))} ↓{formatRate(finite(inspectedPoint?.response_bytes_per_second))}</span>}
                </div>
                <div className="mt-0.5 text-[#7b7d80]">{n(totalErrors, 0)} {t("failed requests")} · {percent(aggregateErrorRate)} {t("window error rate")}</div>
              </div>
            </div>
          ) : <div className="grid h-[320px] place-items-center text-xs text-[#7b7d80]">{t("No telemetry points in the selected window")}</div>}
        </Panel>
        <Panel className="flex h-full flex-col" title={t("Request outcomes")} subtitle={t("100% distribution from worker metric buckets")}>
          {series.length ? <>
            <div className="flex flex-wrap gap-x-3 gap-y-1 px-3 py-2 text-[10px] text-[#a7a9ab]">
              {inspectedStatus.map(([label, , color]) => <span key={label} className="inline-flex items-center gap-1"><span className="h-2 w-2" style={{ backgroundColor: color }} />{label}</span>)}
            </div>
            <div className="min-h-[230px] flex-1 px-2 pb-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart syncId="user-activity-timeline" syncMethod="value" data={statusSeries} barCategoryGap={0} onMouseMove={inspect} onMouseLeave={() => setHoveredPoint(null)} margin={{ top: 5, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#303236" vertical={false} />
                  <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={48} tick={{ fill: "#7b7d80", fontSize: 10 }} tickFormatter={compactTime} axisLine={{ stroke: "#2a2d30" }} tickLine={false} />
                  <YAxis width={48} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: "#7b7d80", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(value) => `${value}%`} />
                  <Tooltip content={() => null} />
                  <Bar dataKey="outcome_non_error_pct" stackId="status" fill="#73bf69" isAnimationActive={false} />
                  <Bar dataKey="outcome_error_pct" stackId="status" fill="#f2495c" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="border-t border-[#2a2d30] px-3 py-1.5 text-[10px] font-mono text-[#a7a9ab]">
              <div>{inspectedPoint ? compactTime(inspectedPoint.timestamp_ms) : "—"}</div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                {inspectedStatus.map(([label, value, color]) => <span key={label} style={{ color }}>{label} {inspectedTotal ? `${(value / inspectedTotal * 100).toFixed(1)}%` : "0%"} ({n(value, 0)})</span>)}
              </div>
            </div>
          </> : <div className="grid min-h-[320px] flex-1 place-items-center px-4 text-center text-xs text-[#7b7d80]">{t("No telemetry points in the selected window")}</div>}
        </Panel>
      </div>

      {heatmapPanel}
    </div>
  );
}

export function UserActivityWorkspace() {
  const { principal, profile } = useOutletContext<{ principal: string; profile: any }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const [activeView, setActiveView] = useState<ActivityView>("behavior");
  const [selectedIp, setSelectedIp] = useState("");
  const [selectedService, setSelectedService] = useState("");
  const [selectedApi, setSelectedApi] = useState("");
  const [ipSearch, setIpSearch] = useState("");

  const principalType = String(profile?.principal_type || "unknown");
  const isHuman = principalType === "human";
  const principalRole = isHuman
    ? t("User", "User")
    : principalType === "unknown"
      ? t("Observed Principal", "Principal quan sát được")
      : t("Credential", "Credential");

  useEffect(() => {
    setActiveView("behavior");
    setSelectedIp("");
    setSelectedService("");
    setSelectedApi("");
    setIpSearch("");
  }, [principal]);

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

  const bandwidthQuery = useQuery({
    queryKey: ["user-bandwidth-rollup", principal, filters],
    queryFn: () => api<BandwidthResponse>(`/api/v1/topology/bandwidth?${queryString(filters, { account: principal, window: "30d" })}`),
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
  const bandwidthSeries = bandwidthQuery.data?.series || [];
  const mergedSeries = useMemo(() => {
    const parseFilterTime = (value: string) => Number.isFinite(Number(value)) ? timestamp(value) : Date.parse(value);
    const start = parseFilterTime(filters.start);
    const end = parseFilterTime(filters.end);
    const bucketMs = Number.isFinite(start) && Number.isFinite(end) && end - start > 192 * 3_600_000
      ? 3_600_000 : 300_000;
    const bucketStart = (point: PerformancePoint) => Math.floor(timestamp(point.timestamp_ms ?? point.bucket_start) / bucketMs) * bucketMs;
    const metricByBucket = new Map<number, { requests: number; errors: number; latency_p50: number; latency_p95: number; latency_p99: number }>();
    metricSeries.forEach((point) => {
      const key = bucketStart(point);
      const current = metricByBucket.get(key) || { requests: 0, errors: 0, latency_p50: 0, latency_p95: 0, latency_p99: 0 };
      current.requests += finite(point.requests);
      current.errors += finite(point.errors);
      current.latency_p50 = Math.max(current.latency_p50, finite(point.latency_p50));
      current.latency_p95 = Math.max(current.latency_p95, finite(point.latency_p95));
      current.latency_p99 = Math.max(current.latency_p99, finite(point.latency_p99));
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
    const grouped = new Map<number, { request_count: number; request_bytes: number; response_bytes: number; request_samples: number; response_samples: number }>();
    bandwidthSeries.forEach((point) => {
      const key = bucketStart(point);
      const current = grouped.get(key) || { request_count: 0, request_bytes: 0, response_bytes: 0, request_samples: 0, response_samples: 0 };
      current.request_count += finite(point.request_count);
      current.request_bytes += finite(point.request_bytes);
      current.response_bytes += finite(point.response_bytes);
      current.request_samples += finite(point.request_samples);
      current.response_samples += finite(point.response_samples);
      grouped.set(key, current);
    });
    return [...new Set([...metricByBucket.keys(), ...grouped.keys()])].sort((left, right) => left - right).map((key) => {
      const metric = metricByBucket.get(key);
      const bytes = grouped.get(key);
      const seconds = bucketMs / 1000;
      const requests = metric?.requests || 0;
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
        ...(bytes ? {
          ...bytes,
          request_bytes_per_second: bytes.request_bytes / seconds,
          response_bytes_per_second: bytes.response_bytes / seconds,
          bandwidth_bytes_per_second: (bytes.request_bytes + bytes.response_bytes) / seconds,
        } : {}),
      };
    });
  }, [metricSeries, baselineSeries, bandwidthSeries, filters.start, filters.end]);
  const series = useMemo(() => mergedSeries.map((point) => {
    return {
      ...point,
      timestamp_ms: timestamp(point.timestamp_ms ?? point.bucket_start),
      observed_tps: finite(point.rps),
      baseline_tps: finite(point.baseline_rps),
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

  const sourceRows = useMemo(() => {
    const grouped = new Map<string, RelationshipItem[]>();
    allRelationships.forEach((item) => {
      if (!item.source_ip) return;
      grouped.set(item.source_ip, [...(grouped.get(item.source_ip) || []), item]);
    });
    return [...grouped.entries()].map(([ip, items]) => ({
      ip,
      items,
      role: items.find((item) => item.role_label)?.role_label || items[0]?.source_ip_role || t("Unknown", "Chưa xác định"),
      confidence: items[0]?.attribution_confidence || "—",
      isLoadBalancer: items.some((item) => item.is_load_balancer),
      isNew: items.some((item) => item.is_new_ip),
      ...aggregate(items),
    })).sort((left, right) => right.requestCount - left.requestCount);
  }, [allRelationships, t]);

  const filteredSources = useMemo(() => {
    const needle = ipSearch.trim().toLowerCase();
    return needle ? sourceRows.filter((source) => `${source.ip} ${source.role}`.toLowerCase().includes(needle)) : sourceRows;
  }, [ipSearch, sourceRows]);

  const selectedIpItems = useMemo(
    () => selectedIp ? allRelationships.filter((item) => item.source_ip === selectedIp) : [],
    [allRelationships, selectedIp],
  );

  const serviceChoices = useMemo<AccessChoice[]>(() => {
    const grouped = new Map<string, RelationshipItem[]>();
    selectedIpItems.forEach((item) => {
      const name = item.service || "";
      if (name) grouped.set(name, [...(grouped.get(name) || []), item]);
    });
    return [...grouped.entries()].map(([name, items]) => ({ name, items, relationCount: new Set(items.map((item) => item.api).filter(Boolean)).size, ...aggregate(items) }))
      .sort((left, right) => right.requestCount - left.requestCount);
  }, [selectedIpItems]);

  const selectedServiceItems = useMemo(
    () => selectedIpItems.filter((item) => item.service === selectedService),
    [selectedIpItems, selectedService],
  );

  const apiChoices = useMemo<AccessChoice[]>(() => {
    const grouped = new Map<string, RelationshipItem[]>();
    selectedServiceItems.forEach((item) => {
      const name = item.api || t("Unknown operation", "Operation chưa xác định");
      grouped.set(name, [...(grouped.get(name) || []), item]);
    });
    return [...grouped.entries()].map(([name, items]) => ({ name, items, relationCount: new Set(items.map((item) => item.caller_service).filter(Boolean)).size, ...aggregate(items) }))
      .sort((left, right) => right.requestCount - left.requestCount);
  }, [selectedServiceItems, t]);

  const selectedApiItems = useMemo(
    () => selectedServiceItems.filter((item) => (item.api || t("Unknown operation", "Operation chưa xác định")) === selectedApi),
    [selectedApi, selectedServiceItems, t],
  );
  const selectedAccessItems = selectedApiItems.length ? selectedApiItems : selectedServiceItems;
  const selectedAccessMetrics = aggregate(selectedAccessItems);

  const callerRows = useMemo(() => {
    const grouped = new Map<string, RelationshipItem[]>();
    selectedAccessItems.forEach((item) => {
      const name = item.caller_service || t("Caller unavailable", "Caller không khả dụng");
      grouped.set(name, [...(grouped.get(name) || []), item]);
    });
    return [...grouped.entries()].map(([name, items]) => ({ name, ...aggregate(items) }))
      .sort((left, right) => right.requestCount - left.requestCount);
  }, [selectedAccessItems, t]);

  useEffect(() => {
    setSelectedService("");
    setSelectedApi("");
  }, [selectedIp]);

  useEffect(() => {
    setSelectedApi("");
  }, [selectedService]);

  const totalRequests = series.reduce((sum, point) => sum + finite(point.requests), 0);
  const totalErrors = series.reduce((sum, point) => sum + finite(point.errors), 0);
  const aggregateErrorRate = totalRequests ? totalErrors / totalRequests : 0;
  const latestPoint = series[series.length - 1];
  const latestTelemetryPoint = [...series].reverse().find((point) => finite(point.requests) > 0) || latestPoint;
  const currentTps = finite(latestTelemetryPoint?.observed_tps);
  const currentErrorRate = finite(latestTelemetryPoint?.error_rate);
  const currentP95 = finite(latestTelemetryPoint?.latency_p95);
  const hasBandwidth = Boolean(bandwidthQuery.data?.available) || series.some((point) => finite(point.request_bytes) > 0 || finite(point.response_bytes) > 0);
  const baselineTps = finite(latestTelemetryPoint?.baseline_rps);
  const baselineErrorRate = finite(latestTelemetryPoint?.baseline_error_rate);
  const baselineP95 = finite(latestTelemetryPoint?.baseline_p95);
  const latestBandwidthPoint = [...bandwidthSeries].reverse().find((point) => finite(point.request_samples) + finite(point.response_samples) > 0);
  const currentBandwidth = latestBandwidthPoint
    ? finite(latestBandwidthPoint.bandwidth_bytes_per_second)
    : finite(bandwidthQuery.data?.metrics?.bandwidth_bytes_per_second);
  const bandwidthRates = bandwidthSeries.map((point) => finite(point.bandwidth_bytes_per_second)).sort((left, right) => left - right);
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

  const views: Array<{ id: ActivityView; label: string; description: string }> = [
    { id: "behavior", label: t("Behavior"), description: t("Current telemetry compared with normal behavior") },
    { id: "access", label: t("Access"), description: t("IP → Service → API drilldown for this identity") },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2a2d30] pb-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-[.1em] text-[#5794f2]">{t("Activity")}</span>
          <span className="text-[#303236]">·</span>
          <span className="text-[11px] text-[#7b7d80]">{views.find((view) => view.id === activeView)?.description}</span>
        </div>
        <div data-testid="user-activity-segments" className="inline-flex border border-[#34373b] bg-[#0e0f12] p-0.5" role="tablist" aria-label={t("Activity view")}>
          {views.map((view) => (
            <button
              key={view.id}
              type="button"
              role="tab"
              aria-selected={activeView === view.id}
              onClick={() => setActiveView(view.id)}
              className={`min-w-[96px] px-2.5 py-1 text-[11px] font-medium transition-colors ${activeView === view.id ? "bg-[#5794f2] text-white font-semibold" : "text-[#a7a9ab] hover:bg-[#202226] hover:text-white"}`}
            >
              {view.label}
            </button>
          ))}
        </div>
      </div>

      {activeView === "behavior" && (
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
        />
      )}

      {activeView === "access" && (
        <div className="space-y-3" role="tabpanel">
          {relationshipQuery.isLoading ? <Loading /> : relationshipQuery.error ? <ErrorState message={(relationshipQuery.error as Error).message} /> : (
            <>
              <Panel
                title={`${t("Access for", "Quyền truy cập của")} ${principal}`}
                subtitle={`${principalRole} (${principalType.replaceAll("_", " ")}) · ${t("Select IP → Service → API")}`}
                action={<span className="font-mono text-[10px] text-[#7b7d80]">{sourceRows.length} IP · {allRelationships.length} {t("relationships")}</span>}
              >
                <div className="grid gap-2 p-2 md:grid-cols-3 xl:grid-cols-[25%_35%_40%]">
                  <BoardColumn step={1} title={t("Selected IP")} subtitle={t("Supporting network evidence")}>
                    <label className="relative mb-2 block">
                      <Search className="absolute left-2 top-2 text-[#7b7d80]" size={12} />
                      <input value={ipSearch} onChange={(event) => setIpSearch(event.target.value)} placeholder={t("Find IP…")} className="toolbar-control h-7 w-full pl-7 pr-7 text-[10px]" />
                      {ipSearch && <button type="button" onClick={() => setIpSearch("")} className="absolute right-2 top-1.5 text-[#7b7d80] hover:text-white"><X size={12} /></button>}
                    </label>
                    <div className="space-y-1">
                      {filteredSources.map((source) => (
                        <button key={source.ip} type="button" onClick={() => setSelectedIp(source.ip === selectedIp ? "" : source.ip)} className={`w-full border p-2 text-left ${source.ip === selectedIp ? "border-[#a7a9ab] bg-[#a7a9ab]/10" : "border-[#2a2d30] bg-[#111217] hover:border-[#34373b]"}`}>
                          <div className="flex items-center justify-between gap-2"><span className="font-mono text-[10px] text-[#d8d9da]">{source.ip}</span>{source.isNew && <span className="border border-[#ff9830]/40 bg-[#ff9830]/10 px-1 text-[8px] text-[#ff9830]">NEW</span>}</div>
                          <div className="mt-1 truncate text-[9px] text-[#7b7d80]">{source.role} · {n(source.requestCount, 0)} {t("requests")}</div>
                        </button>
                      ))}
                      {!filteredSources.length && <div className="px-2 py-6 text-center text-[10px] text-[#7b7d80]">{t("No matching IP evidence")}</div>}
                    </div>
                  </BoardColumn>

                  <BoardColumn step={2} title={t("Service")} subtitle={t("Target Services for the selected IP")}>
                    {!selectedIp ? <div className="grid min-h-44 place-items-center px-3 text-center text-[10px] text-[#7b7d80]">{t("Select an IP to reveal Services")}</div> : (
                      <div className="space-y-1">
                        {serviceChoices.map((service) => (
                          <button key={service.name} type="button" onClick={() => setSelectedService(service.name === selectedService ? "" : service.name)} className={`w-full border p-2 text-left ${service.name === selectedService ? "border-[#5794f2] bg-[#5794f2]/10" : "border-[#2a2d30] bg-[#111217] hover:border-[#34373b]"}`}>
                            <div className="flex items-center gap-1.5"><Server size={11} className="text-[#5794f2]" /><span className="truncate font-mono text-[10px] text-[#8db7fa]">{service.name}</span></div>
                            <div className="mt-1 text-[9px] text-[#7b7d80]">{n(service.tps, 2)} TPS · {service.relationCount} API · {percent(service.errorRate)}</div>
                          </button>
                        ))}
                      </div>
                    )}
                  </BoardColumn>

                  <BoardColumn step={3} title="API" subtitle={t("Operations on the selected Service")}>
                    {!selectedService ? <div className="grid min-h-44 place-items-center px-3 text-center text-[10px] text-[#7b7d80]">{t("Select a Service to reveal APIs")}</div> : (
                      <div className="space-y-1">
                        {apiChoices.map((apiChoice) => (
                          <button key={apiChoice.name} type="button" onClick={() => setSelectedApi(apiChoice.name === selectedApi ? "" : apiChoice.name)} className={`w-full border p-2 text-left ${apiChoice.name === selectedApi ? "border-[#56b9a8] bg-[#56b9a8]/10" : "border-[#2a2d30] bg-[#111217] hover:border-[#34373b]"}`}>
                            <div className="flex items-center gap-1.5"><Fingerprint size={11} className="text-[#56b9a8]" /><span className="truncate font-mono text-[10px] text-[#82d5c4]">{apiChoice.name}</span></div>
                            <div className="mt-1 text-[9px] text-[#7b7d80]">{n(apiChoice.tps, 2)} TPS · {apiChoice.relationCount} {t("callers")} · {percent(apiChoice.errorRate)}</div>
                          </button>
                        ))}
                      </div>
                    )}
                  </BoardColumn>
                </div>
                {relationshipQuery.hasNextPage && (
                  <div className="border-t border-[#2a2d30] p-2 text-center"><button type="button" disabled={relationshipQuery.isFetchingNextPage} onClick={() => relationshipQuery.fetchNextPage()} className="toolbar-control px-3 py-1 text-[10px] disabled:opacity-50">{relationshipQuery.isFetchingNextPage ? t("Loading…") : t("Load more relationships")}</button></div>
                )}
              </Panel>

              {selectedService && (
                <Panel
                  title={selectedApi ? t("Selected API relationship") : t("Selected Service relationship")}
                  subtitle={t("Caller Service is shown separately from the identity observed on its request")}
                  action={<span className="font-mono text-[10px] text-[#7b7d80]">{callerRows.length} {t("callers")}</span>}
                >
                  <div className="border-b border-[#2a2d30] p-3">
                    <div className="flex flex-wrap items-center gap-2 text-[10px]">
                      <span className="inline-flex items-center gap-1 border border-[#a7a9ab]/40 bg-[#a7a9ab]/10 px-2 py-1 font-mono text-[#d8d9da]"><Globe2 size={11} />{selectedIp}</span>
                      <ArrowRight size={12} className="text-[#7b7d80]" />
                      <span className="inline-flex items-center gap-1 border border-[#b877d9]/40 bg-[#b877d9]/10 px-2 py-1 font-mono text-[#d9b4ea]">{isHuman ? <UserRound size={11} /> : <KeyRound size={11} />}{principal}</span>
                      <ArrowRight size={12} className="text-[#7b7d80]" />
                      <span className="inline-flex items-center gap-1 border border-[#5794f2]/40 bg-[#5794f2]/10 px-2 py-1 font-mono text-[#8db7fa]"><Server size={11} />{selectedService}</span>
                      {selectedApi && <><ArrowRight size={12} className="text-[#7b7d80]" /><span className="inline-flex items-center gap-1 border border-[#56b9a8]/40 bg-[#56b9a8]/10 px-2 py-1 font-mono text-[#82d5c4]"><Fingerprint size={11} />{selectedApi}</span></>}
                    </div>
                    <p className="mt-2 text-[10px] text-[#7b7d80]">{t("This board scopes where the identity was observed. The table below shows the Caller Service recorded with each request; open a Trace to confirm the exact request chain and credential propagation.")}</p>
                  </div>

                  <div className="grid grid-cols-2 gap-2 border-b border-[#2a2d30] p-2 lg:grid-cols-4">
                    <MetricTile label="TPS" value={n(selectedAccessMetrics.tps, 2)} detail={`${n(selectedAccessMetrics.requestCount, 0)} ${t("requests")}`} valueClass="text-[#5794f2]" />
                    <MetricTile label={t("Error rate")} value={percent(selectedAccessMetrics.errorRate)} detail={`${n(selectedAccessMetrics.errorCount, 0)} ${t("failures")}`} valueClass={selectedAccessMetrics.errorRate >= 0.05 ? "text-[#f2495c]" : "text-[#73bf69]"} />
                    <MetricTile label="P95" value={`${n(selectedAccessMetrics.p95, 0)} ms`} detail={t("Maximum observed tail latency")} />
                    <MetricTile label={t("Bandwidth")} value={selectedAccessMetrics.requestBytes + selectedAccessMetrics.responseBytes > 0 ? formatRate(selectedAccessMetrics.bandwidth) : t("Unavailable", "Không có dữ liệu")} detail={`${formatBytes(selectedAccessMetrics.requestBytes)} ↑ · ${formatBytes(selectedAccessMetrics.responseBytes)} ↓`} valueClass="text-[#5794f2]" />
                  </div>

                  <div className="overflow-x-auto">
                    <table className="data-table min-w-[860px]">
                      <thead><tr><th className="text-left">{t("Caller Service")}</th><th className="text-right">TPS</th><th className="text-right">{t("Requests")}</th><th className="text-right">{t("Error")}</th><th className="text-right">P95</th><th className="text-right">{t("First seen")}</th><th className="text-right">{t("Last seen")}</th></tr></thead>
                      <tbody>{callerRows.map((caller) => (
                        <tr key={caller.name}>
                          <td className="font-mono text-[11px] text-[#8db7fa]">{caller.name}</td>
                          <td className="text-right font-mono">{n(caller.tps, 2)}</td>
                          <td className="text-right font-mono">{n(caller.requestCount, 0)}</td>
                          <td className={`text-right font-mono ${caller.errorRate >= 0.05 ? "text-[#f2495c]" : "text-[#73bf69]"}`}>{percent(caller.errorRate)}</td>
                          <td className="text-right font-mono">{n(caller.p95, 0)} ms</td>
                          <td className="text-right text-[10px] text-[#7b7d80]">{formatTime(caller.firstSeen)}</td>
                          <td className="text-right text-[10px] text-[#7b7d80]">{formatTime(caller.lastSeen)}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#2a2d30] bg-[#0e0f12] px-3 py-2">
                    <span className="inline-flex items-center gap-1.5 text-[10px] text-[#7b7d80]"><Clock3 size={11} />{formatTime(selectedAccessMetrics.firstSeen)} → {formatTime(selectedAccessMetrics.lastSeen)}</span>
                    <div className="flex gap-2">
                      <Link to={`/traces?principal=${encodeURIComponent(principal)}&service=${encodeURIComponent(selectedService)}`} className="toolbar-control inline-flex items-center gap-1.5 px-2 py-1 text-[10px] text-[#5794f2] hover:text-white">{t("View related Traces")}<ExternalLink size={11} /></Link>
                      {selectedApi && <Link to={`/services/${encodeURIComponent(selectedService)}/apis/${encodeURIComponent(selectedApi)}`} className="toolbar-control inline-flex items-center gap-1.5 px-2 py-1 text-[10px] text-[#56b9a8] hover:text-white">{t("Open API")}<ExternalLink size={11} /></Link>}
                    </div>
                  </div>
                </Panel>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
