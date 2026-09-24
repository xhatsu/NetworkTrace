import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Box,
  Clock,
  Search,
} from "lucide-react";
import { EpisodeStatusBadge, episodeStatusClass, episodeStatusLabel, type EpisodeResponse } from "../components/EpisodePrimitives";
import { api, queryString } from "../api";
import {
  ErrorState,
  InteractiveMetricCard,
  Loading,
  Page,
  Panel,
  TpsLineChart,
  chartTooltip,
  n,
  pct,
} from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import type { SeriesPoint } from "../types";

type Service = {
  name: string;
  environment: string;
  service_group: string;
  service_module: string;
  first_seen_ms: number;
  last_seen_ms: number;
  total_requests?: number;
  total_errors?: number;
  error_rate?: number;
  p95_latency?: number;
  operations_count?: number;
  principal_count?: number;
  rps?: number;
  anomaly_status?: string;
};

export function ServicesPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [filterQuery, setFilterQuery] = useState("");
  const qs = queryString(filters);

  const query = useQuery({
    queryKey: ["services", qs],
    queryFn: () => api<{ items: Service[] }>(`/api/v1/services?${qs}&limit=500`),
  });
  const estateSeriesQuery = useQuery({
    queryKey: ["service-estate-tps", qs],
    queryFn: () => api<{ items: SeriesPoint[] }>(`/api/v1/dashboard/series?${qs}`),
  });
  const filteredItems = [...(query.data?.items || [])].filter((s) => {
    if (!filterQuery) return true;
    const q = filterQuery.toLowerCase();
    return (
      (s.name || "").toLowerCase().includes(q) ||
      (s.service_group || "").toLowerCase().includes(q) ||
      (s.service_module || "").toLowerCase().includes(q) ||
      (s.environment || "").toLowerCase().includes(q)
    );
  }).sort((a, b) => {
    const aNeedsAttention = a.anomaly_status === "abnormal" || Number(a.error_rate || 0) >= 0.05;
    const bNeedsAttention = b.anomaly_status === "abnormal" || Number(b.error_rate || 0) >= 0.05;
    if (aNeedsAttention !== bNeedsAttention) return aNeedsAttention ? -1 : 1;
    return Number(b.total_requests || 0) - Number(a.total_requests || 0);
  });

  return (
    <Page
      eyebrow={t("Inventory & Catalog")}
      title={t("Service Estate Directory")}
      description={t("Observed service nodes with environment segmentation, functional group ownership, and telemetry freshness.")}
      actions={
        <div className="relative w-72">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-cyan-400" />
          <input
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            placeholder={t("Filter by name, group, module…")}
            className="w-full rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] pl-9 pr-3 py-1.5 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] focus:border-cyan-400 focus:bg-white/[0.08] focus:outline-none"
          />
        </div>
      }
    >
      {query.isLoading ? (
        <Loading />
      ) : (
        <>
        <Panel
          title={t("Estate TPS")}
          subtitle={t("Observed throughput across the selected service estate")}
          className="mb-3"
          action={<span className="font-mono text-[11px] text-[#5794f2]">{t("Live")}</span>}
        >
          <TpsLineChart data={estateSeriesQuery.data?.items || []} />
        </Panel>
        <Panel
          title={`${filteredItems.length} ${t("Across")} ${query.data?.items.length || 0} ${t("Registered Services")}`}
          subtitle={t("Operational health and observed traffic by service")}
        >
          <div className="overflow-x-auto scrollbar">
            <table className="w-full min-w-[980px] text-left text-xs">
              <thead>
                <tr>
                  {[t("Service"), t("Environment"), t("Group / Module"), t("TPS"), t("P95"), t("Error"), t("APIs"), t("Users"), t("Health"), t("Last Seen")].map((heading) => (
                    <th className="table-head px-4 py-3" key={heading}>{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((s) => {
                  const abnormal = s.anomaly_status === "abnormal" || Number(s.error_rate || 0) >= 0.05;
                  return (
                    <tr
                      key={s.name}
                      onClick={() => nav(`/services/${encodeURIComponent(s.name)}?${queryString(filters)}`)}
                      className="cursor-pointer border-t border-[rgba(255,255,255,0.08)] transition hover:bg-white/[0.04]"
                    >
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-2 font-semibold text-[#f5f3fa] hover:text-cyan-300">
                          <Box size={14} className="text-violet-300" />
                          {s.name}
                        </span>
                      </td>
                      <td className="px-4 text-[#c4bdd9]">{t(s.environment, s.environment)}</td>
                      <td className="px-4 text-[#c4bdd9]">{s.service_group} · {s.service_module}</td>
                      <td className="px-4 font-mono tabular-nums text-sky-300">{n(Number(s.rps || 0), 2)}</td>
                      <td className="px-4 font-mono tabular-nums text-violet-300">{n(Number(s.p95_latency || 0), 1)} ms</td>
                      <td className={`px-4 font-mono tabular-nums ${Number(s.error_rate || 0) >= 0.05 ? "text-rose-300" : "text-emerald-300"}`}>{pct(Number(s.error_rate || 0))}</td>
                      <td className="px-4 font-mono tabular-nums text-[#c4bdd9]">{n(Number(s.operations_count || 0), 0)}</td>
                      <td className="px-4 font-mono tabular-nums text-[#c4bdd9]">{n(Number(s.principal_count || 0), 0)}</td>
                      <td className="px-4">
                        <span className={`rounded border px-2 py-1 text-[10px] font-semibold uppercase ${abnormal ? "border-rose-500/40 bg-rose-500/10 text-rose-300" : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"}`}>
                          {abnormal ? t("Needs attention") : t("Healthy")}
                        </span>
                      </td>
                      <td className="px-4 text-[#c4bdd9]">{s.last_seen_ms ? new Date(s.last_seen_ms).toLocaleString() : "—"}</td>
                    </tr>
                  );
                })}
                {filteredItems.length === 0 && (
                  <tr><td colSpan={10} className="px-4 py-12 text-center text-xs text-[#c4bdd9]">{t("No services match")} "{filterQuery}".</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
        </>
      )}
    </Page>
  );
}

type Detail = {
  service: Service;
  // The service detail endpoint is backed by the rollup repository, whose
  // native series shape uses `bucket_start`, `requests`, `errors`, and
  // `latency_p95`. Keep the response permissive here and normalize it before
  // handing data to Recharts (which expects the dashboard SeriesPoint shape).
  series?: unknown[];
  operations: {
    name: string;
    requests: number;
    p50_ms: number;
    p95_ms: number;
    p99_ms: number;
    slow_rate: number;
    failure_rate: number;
    status_2xx: number;
    status_4xx: number;
    status_5xx: number;
  }[];
  accounts: { username: string; requests: number }[];
  instances: { name: string; operation: string; requests: number; avg_ms: number }[];
  incoming: { name: string; requests: number; evidence: string }[];
  outgoing: { name: string; requests: number; evidence: string }[];
  bandwidth?: { metrics?: Record<string, number>; series?: unknown[] };
};

type ServiceSeriesPoint = SeriesPoint & {
  requests: number;
  request_bytes_per_second?: number;
  response_bytes_per_second?: number;
  bandwidth_bytes_per_second?: number;
};

type ServiceChartLine = { dataKey: string; label: string; color: string; width?: number; dashed?: boolean };
type ServiceChartVariable = { lines: ServiceChartLine[]; formatAxis: (value: number) => string; minimumAxisMax: number; available: boolean };
type ServiceChartMetric = "tps" | "requests" | "error" | "latency" | "bandwidth";

function serviceNumber(value: unknown) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatServiceByteRate(value: number) {
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let normalized = Math.max(0, Number(value) || 0);
  let unitIndex = 0;
  while (normalized >= 1024 && unitIndex < units.length - 1) {
    normalized /= 1024;
    unitIndex += 1;
  }
  return `${normalized.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function normalizeServiceBandwidth(rows: unknown) {
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const row = value as Record<string, unknown>;
    const rawTimestamp = serviceNumber(row.timestamp_ms);
    const bucketStart = serviceNumber(row.bucket_start);
    const timestampMs = rawTimestamp > 0 ? rawTimestamp : bucketStart > 0 ? bucketStart * 1000 : 0;
    if (!timestampMs) return [];
    return [{
      timestamp_ms: timestampMs,
      request_bytes_per_second: serviceNumber(row.request_bytes_per_second),
      response_bytes_per_second: serviceNumber(row.response_bytes_per_second),
      bandwidth_bytes_per_second: serviceNumber(row.bandwidth_bytes_per_second),
      request_bytes_samples: serviceNumber(row.request_bytes_samples),
      response_bytes_samples: serviceNumber(row.response_bytes_samples),
      bandwidth_available: row.bandwidth_available === true ? 1 : 0,
    }];
  }).sort((a, b) => a.timestamp_ms - b.timestamp_ms);
}

function mergeServiceBandwidth(series: ServiceSeriesPoint[], bandwidthSeries: ReturnType<typeof normalizeServiceBandwidth>) {
  const points = new Map<number, Record<string, number>>();
  series.forEach((point) => points.set(point.timestamp_ms, { ...point, observed_tps: point.tps, baseline_tps: point.baseline_rps }));
  bandwidthSeries.forEach((point) => {
    points.set(point.timestamp_ms, { ...(points.get(point.timestamp_ms) || { timestamp_ms: point.timestamp_ms }), ...point });
  });
  return [...points.values()].sort((a, b) => a.timestamp_ms - b.timestamp_ms);
}

function normalizeServiceSeries(rows: unknown): ServiceSeriesPoint[] {
  if (!Array.isArray(rows)) return [];

  return rows
    .map((value): ServiceSeriesPoint | null => {
      if (!value || typeof value !== "object") return null;
      const row = value as Record<string, unknown>;
      const bucketStart = Number(row.bucket_start ?? 0);
      const rawTimestamp = Number(row.timestamp_ms ?? 0);
      const timestampMs = Number.isFinite(rawTimestamp) && rawTimestamp > 0
        ? rawTimestamp
        : bucketStart > 0
          ? bucketStart * 1000
          : 0;
      if (!timestampMs) return null;

      const requests = Number(row.requests ?? row.request_count ?? 0);
      const errors = Number(row.errors ?? row.error_count ?? 0);
      const bucketSeconds = Math.max(1, Number(row.bucket_size ?? 60));
      const measuredRate = Number(row.tps ?? row.rps ?? NaN);
      const tps = Number.isFinite(measuredRate)
        ? measuredRate
        : requests / bucketSeconds;
      const errorRate = Number(row.http_5xx_rate ?? row.error_rate ?? NaN);
      const failureRate = Number.isFinite(errorRate)
        ? errorRate
        : requests > 0
          ? errors / requests
          : 0;

      return {
        timestamp_ms: timestampMs,
        rps: tps,
        tps,
        requests,
        baseline_rps: Number(row.baseline_rps ?? 0),
        p50_ms: Number(row.p50_ms ?? row.latency_p50 ?? row.latency_avg ?? 0),
        p95_ms: Number(row.p95_ms ?? row.latency_p95 ?? 0),
        p99_ms: Number(row.p99_ms ?? row.latency_p99 ?? 0),
        http_4xx_rate: Number(row.http_4xx_rate ?? 0),
        http_5xx_rate: failureRate,
        success_rate: Number(row.success_rate ?? 1 - failureRate),
        failure_rate: Number(row.failure_rate ?? failureRate),
        sample_count: Number(row.sample_count ?? requests),
      };
    })
    .filter((point): point is ServiceSeriesPoint => point !== null)
    .sort((a, b) => a.timestamp_ms - b.timestamp_ms);
}

function ServicePerformancePanel({
  series,
  bandwidthSeries,
  chartSeries,
  totalRequests,
  totalErrors,
  operationsCount,
  durationSec,
  failureRate,
  worstP95,
  bandwidthMetrics,
}: {
  series: ServiceSeriesPoint[];
  bandwidthSeries: ReturnType<typeof normalizeServiceBandwidth>;
  chartSeries: ReturnType<typeof mergeServiceBandwidth>;
  totalRequests: number;
  totalErrors: number;
  operationsCount: number;
  durationSec: number;
  failureRate: number;
  worstP95: number;
  bandwidthMetrics: Record<string, number>;
}) {
  const { t } = useI18n();
  const [selectedMetric, setSelectedMetric] = useState<ServiceChartMetric>("tps");
  const latest = series[series.length - 1];
  const currentTps = serviceNumber(latest?.tps);
  const averageTps = totalRequests / Math.max(1, durationSec);
  const peakTps = Math.max(0, ...series.map((point) => serviceNumber(point.tps)));
  const currentP95 = serviceNumber(latest?.p95_ms) || worstP95;
  const currentRequestRate = serviceNumber(bandwidthMetrics.request_bytes_per_second);
  const currentResponseRate = serviceNumber(bandwidthMetrics.response_bytes_per_second);
  const currentBandwidth = serviceNumber(bandwidthMetrics.bandwidth_bytes_per_second);
  const hasBandwidth = bandwidthSeries.some((point) => point.bandwidth_available > 0 || point.request_bytes_samples + point.response_bytes_samples > 0);
  const hasBaselineTps = series.some((point) => serviceNumber(point.baseline_rps) > 0);

  const tpsLines: ServiceChartLine[] = [
    { dataKey: "observed_tps", label: t("Observed TPS"), color: "#5794f2", width: 2.4 },
    ...(hasBaselineTps ? [{ dataKey: "baseline_tps", label: t("Baseline TPS"), color: "#7b7d80", dashed: true, width: 1.5 }] : []),
  ];
  const seriesMaximum = (lines: ServiceChartLine[]) => chartSeries.reduce(
    (maximum, point) => lines.reduce((value, line) => Math.max(value, serviceNumber(point[line.dataKey])), maximum), 0,
  );
  const tpsPeak = seriesMaximum(tpsLines);
  const tpsAxisMaximum = tpsPeak > 0 ? tpsPeak : 1;
  const tpsAxisDigits = tpsAxisMaximum < 1
    ? Math.min(8, Math.max(2, Math.ceil(-Math.log10(tpsAxisMaximum / 4)) + 1))
    : 1;
  const formatTpsAxis = (value: number) => `${n(value, tpsAxisDigits)} TPS`;
  const chartVariables: Record<ServiceChartMetric, ServiceChartVariable> = {
    tps: { lines: tpsLines, formatAxis: formatTpsAxis, minimumAxisMax: 0, available: true },
    requests: {
      lines: [{ dataKey: "requests", label: t("Requests / minute"), color: "#b877d9", width: 2 }],
      formatAxis: (value) => `${n(value, 0)}`,
      minimumAxisMax: 1,
      available: true,
    },
    error: {
      lines: [{ dataKey: "failure_rate", label: t("Error rate"), color: "#f2495c", width: 2.2 }],
      formatAxis: (value) => pct(value),
      minimumAxisMax: 0.01,
      available: true,
    },
    latency: {
      lines: [{ dataKey: "p95_ms", label: t("P95 Latency"), color: "#ff9830", width: 2.2 }],
      formatAxis: (value) => `${n(value, 0)} ms`,
      minimumAxisMax: 1,
      available: true,
    },
    bandwidth: {
      lines: [
        { dataKey: "request_bytes_per_second", label: t("Request bytes/s"), color: "#b877d9", width: 2 },
        { dataKey: "response_bytes_per_second", label: t("Response bytes/s"), color: "#56b9a8", width: 2 },
      ],
      formatAxis: formatServiceByteRate,
      minimumAxisMax: 1,
      available: hasBandwidth,
    },
  };
  const selectedVariable = chartVariables[selectedMetric];
  const overlayLines = selectedMetric !== "tps" && selectedVariable.available ? selectedVariable.lines : [];
  const rightVariable = overlayLines.length ? selectedVariable : chartVariables.tps;
  const rightPeak = overlayLines.length ? seriesMaximum(rightVariable.lines) : tpsPeak;
  const rightAxisMaximum = rightPeak > 0 ? rightPeak : rightVariable.minimumAxisMax || 1;
  const chartLegend = [...tpsLines, ...overlayLines];
  const spark = (key: keyof ServiceSeriesPoint) => series.map((point) => ({ timestamp_ms: point.timestamp_ms, value: serviceNumber(point[key]) }));
  const requestSpark = spark("requests");
  const tpsSpark = spark("tps");
  const errorSpark = spark("failure_rate");
  const latencySpark = spark("p95_ms");
  const bandwidthSpark = bandwidthSeries.map((point) => ({ timestamp_ms: point.timestamp_ms, value: point.bandwidth_bytes_per_second }));

  return (
    <div className="mt-4 space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
        <InteractiveMetricCard
          label="TPS"
          value={n(currentTps, 2)}
          detail={`${t("avg")} ${n(averageTps, 2)} · ${t("peak")} ${n(peakTps, 2)}`}
          subDetail={`${n(totalRequests, 0)} ${t("requests")}`}
          data={tpsSpark}
          color="#5794f2"
          selected={selectedMetric === "tps"}
          onSelect={() => setSelectedMetric("tps")}
          valueClass="text-[#5794f2]"
        />
        <InteractiveMetricCard
          label={t("Requests")}
          value={n(totalRequests, 0)}
          detail={t("Server transactions")}
          subDetail={`${n(Math.max(0, ...series.map((point) => point.requests)), 0)}/min peak`}
          data={requestSpark}
          color="#b877d9"
          selected={selectedMetric === "requests"}
          onSelect={() => setSelectedMetric("requests")}
        />
        <InteractiveMetricCard
          label={t("Error rate")}
          value={pct(failureRate)}
          detail={`${n(totalErrors, 0)} ${t("errors")}`}
          data={errorSpark}
          color="#f2495c"
          selected={selectedMetric === "error"}
          onSelect={() => setSelectedMetric("error")}
          valueClass={failureRate >= 0.05 ? "text-[#f2495c]" : "text-[#d8d9da]"}
        />
        <InteractiveMetricCard
          label={t("P95 latency")}
          value={`${n(worstP95, 0)} ms`}
          detail={`${t("Across")} ${n(operationsCount, 0)} ${t("Operations").toLowerCase()}`}
          subDetail={`now ${n(currentP95, 0)} ms`}
          data={latencySpark}
          color="#ff9830"
          selected={selectedMetric === "latency"}
          onSelect={() => setSelectedMetric("latency")}
        />
        <InteractiveMetricCard
          label={t("Bandwidth")}
          value={formatServiceByteRate(currentBandwidth)}
          detail={t("Request + response throughput")}
          subDetail={`↑ ${formatServiceByteRate(currentRequestRate)} · ↓ ${formatServiceByteRate(currentResponseRate)}`}
          data={bandwidthSpark}
          color="#56b9a8"
          selected={selectedMetric === "bandwidth"}
          onSelect={() => setSelectedMetric("bandwidth")}
        />
      </div>

      <Panel title={hasBaselineTps ? t("TPS vs Baseline") : t("TPS")} subtitle={t("TPS on left · selected KPI on right")}>
        <div className="space-y-0">
          <div className="flex h-8 min-w-0 items-center gap-4 overflow-x-auto whitespace-nowrap px-3 text-[10px] text-[#a7a9ab]">
            {chartLegend.map(({ label, color, dashed }) => <span key={label}><span className={`mr-1 inline-block w-3 border-t-2 align-middle ${dashed ? "border-dashed" : ""}`} style={{ borderColor: color }} />{label}</span>)}
          </div>
          <div className="relative h-[230px] px-2 pb-1 pt-1">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartSeries} margin={{ top: 6, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#303236" vertical={false} />
                <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={52} tick={{ fill: "#7b7d80", fontSize: 10 }} tickFormatter={(value) => new Date(Number(value)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} axisLine={{ stroke: "#2a2d30" }} tickLine={false} />
                <YAxis yAxisId="tps" width={48} domain={[0, tpsAxisMaximum]} ticks={[0, 0.25, 0.5, 0.75, 1].map((fraction) => tpsAxisMaximum * fraction)} allowDataOverflow tick={{ fill: "#7b7d80", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(value) => n(Number(value), tpsAxisDigits)} />
                <YAxis yAxisId="metric" orientation="right" width={78} domain={[0, rightAxisMaximum]} allowDataOverflow tick={false} axisLine={false} tickLine={false} />
                <Tooltip {...chartTooltip} labelFormatter={(value) => new Date(Number(value)).toLocaleString()} />
                {tpsLines.map((line) => <Line key={line.dataKey} yAxisId="tps" type="monotone" dataKey={line.dataKey} name={line.label} stroke={line.color} strokeWidth={line.width} strokeDasharray={line.dashed ? "5 4" : undefined} dot={false} connectNulls isAnimationActive={false} />)}
                {overlayLines.map((line) => <Line key={line.dataKey} yAxisId="metric" type="monotone" dataKey={line.dataKey} name={line.label} stroke={line.color} strokeWidth={line.width} strokeDasharray={line.dashed ? "5 4" : undefined} dot={false} connectNulls isAnimationActive={false} />)}
              </LineChart>
            </ResponsiveContainer>
            <div data-testid="service-metric-axis" aria-label={t("Selected metric scale")} className="pointer-events-none absolute bottom-[33px] right-[24px] top-[11px] flex w-[70px] flex-col justify-between text-left text-[10px] text-[#7b7d80]">
              {[1, 0.75, 0.5, 0.25, 0].map((fraction) => <span key={fraction}>{rightVariable.formatAxis(rightAxisMaximum * fraction)}</span>)}
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}

export function ServiceDetailPage() {
  const { name = "" } = useParams();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const qs = queryString({ ...filters, service: undefined });

  const query = useQuery({
    queryKey: ["service", name, qs],
    queryFn: () =>
      api<Detail>(`/api/v1/services/${encodeURIComponent(name)}?${qs}`),
  });
  const serviceChanges = useQuery({
    queryKey: ["service-changes", name, qs],
    queryFn: () => api<EpisodeResponse>(`/api/v1/changes?service=${encodeURIComponent(name)}&limit=10&${qs}`),
  });

  const serviceTraces = useQuery({
    queryKey: ["service-traces", name, qs],
    queryFn: () => api<{ items: any[]; count: number }>(`/api/v1/traces?service=${encodeURIComponent(name)}&limit=5&${qs}`),
  });

  const serviceUsers = useQuery({
    queryKey: ["service-users", name, qs],
    queryFn: () => api<{ items: any[]; total: number }>(`/api/v1/users?target=${encodeURIComponent(name)}&limit=10&${qs}`),
  });

  if (query.isLoading) {
    return (
      <Page eyebrow={t("Service Drilldown")} title={name} description={t("Loading...")}>
        <Loading />
      </Page>
    );
  }

  if (query.error) {
    return (
      <Page eyebrow={t("Service Drilldown")} title={name} description="">
        <ErrorState message={query.error.message} />
      </Page>
    );
  }

  const d = query.data!;
  const serviceObj = typeof d.service === "object" && d.service ? d.service : ((d as any).service_meta || {
    name: (d as any).name || name,
    environment: "production",
    service_group: "Core",
    service_module: "Default",
    first_seen_ms: 0,
    last_seen_ms: 0
  });
  const operations = d.operations || [];
  const total = operations.reduce((a, b) => a + (b.requests || 0), 0);
  const totalErrors = operations.reduce((sum, operation) => sum + (operation.failure_rate || 0) * (operation.requests || 0), 0);
  const p95 = operations.length
    ? Math.max(...operations.map((o) => o.p95_ms || 0))
    : 0;
  const fail =
    operations.reduce((a, b) => a + (b.failure_rate || 0) * (b.requests || 0), 0) /
    Math.max(1, total);
  const incoming = d.incoming || (d as any).callers || [];
  const outgoing = d.outgoing || (d as any).dependencies || [];
  const accounts = d.accounts || ((d as any).principals || []).map((p: any) => ({ username: p.name, requests: p.requests }));
  const instances = d.instances || [];
  const series = normalizeServiceSeries(d.series);
  const bandwidthMetrics = (d as any).bandwidth?.metrics || (d as any).health || {};
  const bandwidthSeries = normalizeServiceBandwidth(d.bandwidth?.series);
  const chartSeries = mergeServiceBandwidth(series, bandwidthSeries);
  const attentionOperations = [...operations]
    .sort((a, b) => {
      const failureDelta = (b.failure_rate || 0) - (a.failure_rate || 0);
      if (Math.abs(failureDelta) > 0.0001) return failureDelta;
      const latencyDelta = (b.p95_ms || 0) - (a.p95_ms || 0);
      if (Math.abs(latencyDelta) > 0.1) return latencyDelta;
      return (b.requests || 0) - (a.requests || 0);
    })
    .slice(0, 5);

  const durationSec = Math.max(
    1,
    (new Date(filters.end).getTime() - new Date(filters.start).getTime()) / 1000,
  );
  const changes = serviceChanges.data?.items || [];
  const traces = serviceTraces.data?.items || [];

  return (
    <Page
      eyebrow={t("Service Drilldown")}
      title={name}
      description={`${serviceObj.service_group || "Core"} / ${serviceObj.service_module || "Default"} · ${t("Environment")}: ${serviceObj.environment || "production"}`}
      actions={
        <button
          className="btn"
          onClick={() => nav(`/services?${qs}`)}
        >
          <ArrowLeft size={13} />
          {t("All Services")}
        </button>
      }
    >
      <ServicePerformancePanel
        key={name}
        series={series}
        bandwidthSeries={bandwidthSeries}
        chartSeries={chartSeries}
        totalRequests={total}
        totalErrors={totalErrors}
        operationsCount={operations.length}
        durationSec={durationSec}
        failureRate={fail}
        worstP95={p95}
        bandwidthMetrics={bandwidthMetrics}
      />

      {/* 4. APIs */}
      <Panel
        title={t("Needs attention")}
        subtitle={t("Operations prioritized by failure rate, latency tail, and observed volume")}
        className="mt-4"
      >
        {attentionOperations.length ? (
          <div className="divide-y divide-[#2a2d30]">
            {attentionOperations.map((operation) => (
              <button
                type="button"
                key={`attention-${operation.name}`}
                onClick={() => nav(`/services/${encodeURIComponent(name)}/apis/${encodeURIComponent(operation.name)}?${qs}`)}
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition hover:bg-[#181b1f]"
              >
                <span className="min-w-0 truncate font-semibold text-[#d8d9da] hover:text-[#5794f2]">{operation.name}</span>
                <span className="flex shrink-0 items-center gap-4 font-mono text-[11px] tabular-nums">
                  <span className={operation.failure_rate > 0.02 ? "text-[#f2495c]" : "text-[#73bf69]"}>{pct(operation.failure_rate || 0)} {t("error")}</span>
                  <span className={operation.p95_ms > 500 ? "text-[#ff9830]" : "text-[#b877d9]"}>{n(operation.p95_ms || 0, 1)} ms p95</span>
                  <span className="text-[#a7a9ab]">{n(operation.requests || 0, 0)} {t("requests")}</span>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-[#7b7d80]">{t("No operations observed in this window")}</div>
        )}
      </Panel>

      <Panel
        title={t("Operation Performance Inventory")}
        subtitle={t("Latency percentiles from merged logarithmic histograms · Status codes breakdown")}
        className="mt-4"
      >
        <div className="overflow-auto scrollbar">
          <table className="w-full min-w-[850px] text-left text-xs">
            <thead>
              <tr className="border-b border-[#2a2d30]">
                {[
                  t("Operation"),
                  t("Volume"),
                  "p50 Median",
                  t("P95 Latency"),
                  "p99 Tail",
                  "Slow >1s %",
                  "Status Codes (2xx / 4xx / 5xx)",
                ].map((h) => (
                  <th key={h} className="table-head px-4 py-2.5">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2d30]">
              {operations.map((o) => (
                <tr
                  key={o.name}
                  onClick={() => nav(`/services/${encodeURIComponent(name)}/apis/${encodeURIComponent(o.name)}?${qs}`)}
                  className="cursor-pointer hover:bg-[#181b1f] transition"
                >
                  <td className="px-4 py-2.5 font-medium text-[#5794f2]">{o.name}</td>
                  <td className="px-4 font-mono tabular-nums text-[#d8d9da]">{n(o.requests)}</td>
                  <td className="px-4 font-mono tabular-nums text-[#7b7d80]">{n(o.p50_ms || 0)} ms</td>
                  <td className="px-4 font-mono tabular-nums text-[#b877d9]">{n(o.p95_ms || 0)} ms</td>
                  <td className="px-4 font-mono tabular-nums text-[#f2495c]">{n(o.p99_ms || 0)} ms</td>
                  <td className="px-4 font-mono tabular-nums text-[#7b7d80]">{pct(o.slow_rate || 0)}</td>
                  <td className="px-4 font-mono tabular-nums">
                    <span className="text-[#73bf69]">{n(o.status_2xx || 0)}</span>
                    <span className="text-[#7b7d80]"> / </span>
                    <span className="text-[#ff9830]">{n(o.status_4xx || 0)}</span>
                    <span className="text-[#7b7d80]"> / </span>
                    <span className="text-[#f2495c]">{n(o.status_5xx || 0)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* 5. Users */}
      <Panel title={t("Users")} subtitle={t("Principals observed using this service · click to open User Workspace")} className="mt-4">
        <div className="overflow-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-[#2a2d30]">
                {[t("Principal Identity"), t("Volume"), t("Callers"), t("Operations"), t("First seen"), t("Last seen"), t("Recent change")].map((h) => (
                  <th className="table-head px-3 py-2" key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2d30]">
              {(serviceUsers.data?.items || []).map((u: any) => (
                <tr key={u.principal_name} onClick={() => nav(`/users/${encodeURIComponent(u.principal_name)}/activity?${qs}`)} className="cursor-pointer hover:bg-[#181b1f] transition">
                  <td className="px-3 py-2 font-mono text-[#5794f2]">{u.principal_name}</td>
                  <td className="px-3 font-mono tabular-nums text-[#d8d9da]">{n(u.total_requests || u.requests || 0, 0)}</td>
                  <td className="px-3 font-mono tabular-nums text-[#a7a9ab]">{u.unique_callers ?? u.callers ?? "—"}</td>
                  <td className="px-3 font-mono tabular-nums text-[#a7a9ab]">{u.unique_operations ?? u.operations ?? "—"}</td>
                  <td className="px-3 text-[#7b7d80]">{u.first_seen ? new Date(u.first_seen).toLocaleString() : "—"}</td>
                  <td className="px-3 text-[#7b7d80]">{u.last_seen ? new Date(u.last_seen).toLocaleString() : "—"}</td>
                  <td className="px-3">{u.recent_changes || u.recent_change ? <span className="rounded-[2px] bg-[#ff9830]/10 border border-[#ff9830]/40 px-1.5 py-0.5 text-[10px] text-[#ff9830]">{t("Changed")}</span> : "—"}</td>
                </tr>
              ))}
              {!(serviceUsers.data?.items || []).length && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-xs text-[#7b7d80]">{t("No users recorded for this service in this window.")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel
          title={t("Account Identity Distribution")}
          subtitle={t("Presented authentication principals on requests to this service")}
        >
          <SimpleTable
            rows={accounts.map((a: any) => ({
              name: a.username || a.name || "unknown",
              requests: a.requests || 0,
            }))}
          />
        </Panel>

        <Panel
          title={t("Instance Load & Distribution")}
          subtitle={t("Traffic balance across recorded nodes")}
        >
          <SimpleTable rows={instances} />
        </Panel>
      </div>

      {/* 6. Latency and errors */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel
          title={t("P95 Latency")}
          subtitle={t("Service latency over time")}
        >
          <ServiceTrendChart
            data={series}
            dataKey="p95_ms"
            color="#f2495c"
            unit="ms"
            label={t("P95 Latency")}
          />
        </Panel>

        {/* 7. Dependencies */}
        <Panel
          title={t("Dependency Relationships")}
          subtitle={t("Confirmed & inferred directional trace links")}
        >
          <div className="p-4 space-y-4">
            <Relation title={t("Incoming Callers")} items={incoming} />
            <Relation title={t("Outgoing Dependencies")} items={outgoing} />
          </div>
        </Panel>
      </div>

      {/* 8. Changes */}
      <Panel
        title={t("Recent Changes")}
        subtitle={t("Evaluated behavior changes for this service")}
        className="mt-4"
        action={<button onClick={() => nav(`/changes?service=${encodeURIComponent(name)}`)} className="text-[11px] font-semibold text-[#5794f2] hover:text-white">{t("View all")} <ArrowRight size={12} className="inline" /></button>}
      >
        {serviceChanges.isLoading ? (
          <Loading />
        ) : changes.length ? (
          <div className="divide-y divide-[#2a2d30]">
            {changes.slice(0, 5).map((change) => (
              <button
                key={change.id}
                onClick={() => nav(`/changes/${encodeURIComponent(change.id)}?${qs}`)}
                className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition hover:bg-[#181b1f]"
              >
                <EpisodeStatusBadge episode={change} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-semibold text-[#d8d9da]">{change.summary}</span>
                  <span className="mt-0.5 block truncate text-[10px] text-[#7b7d80]">{change.context.operation || change.context.target || change.subject.name}</span>
                </span>
                <span className="shrink-0 font-mono text-[10px] text-[#7b7d80]">{change.last_seen_at ? new Date(change.last_seen_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-[#7b7d80]">{t("No behavior changes for this service in the current window.")}</div>
        )}
      </Panel>

      {/* 9. Representative Traces */}
      <Panel
        title={t("Representative Traces")}
        subtitle={t("Recent distributed traces for this service")}
        className="mt-4"
        action={<button onClick={() => nav(`/traces?service=${encodeURIComponent(name)}`)} className="text-[11px] font-semibold text-[#5794f2] hover:text-white">{t("Open in Traces")} <ArrowRight size={12} className="inline" /></button>}
      >
        {serviceTraces.isLoading ? (
          <Loading />
        ) : traces.length ? (
          <div className="overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#2a2d30]">
                  <th className="table-head px-3 py-2">{t("Trace ID")}</th>
                  <th className="table-head px-3 py-2">{t("Operation")}</th>
                  <th className="table-head px-3 py-2">{t("Principal")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Duration")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Status")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2a2d30]">
                {traces.map((tr: any) => (
                  <tr
                    key={tr.trace_id || tr.id}
                    onClick={() => nav(`/traces/${encodeURIComponent(tr.trace_id || tr.id)}`)}
                    className="cursor-pointer hover:bg-[#181b1f] transition"
                  >
                    <td className="px-3 py-2 font-mono text-[#5794f2]">{(tr.trace_id || tr.id || "").slice(0, 16)}…</td>
                    <td className="px-3 text-[#d8d9da]">{tr.operation || tr.name || "—"}</td>
                    <td className="px-3 font-mono text-[#a7a9ab]">{tr.principal_name || tr.user || "—"}</td>
                    <td className="px-3 text-right font-mono tabular-nums text-[#d8d9da]">{tr.duration_ms != null ? `${Number(tr.duration_ms).toFixed(1)} ms` : "—"}</td>
                    <td className="px-3 text-right font-mono">
                      <span className={`rounded-[2px] px-1.5 py-0.5 text-[10px] uppercase font-semibold ${String(tr.status_code || tr.http_status || tr.status).startsWith("5") ? "text-[#f2495c] bg-[#f2495c]/10" : "text-[#73bf69] bg-[#73bf69]/10"}`}>
                        {tr.status_code || tr.http_status || tr.status || "OK"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-[#7b7d80]">{t("No recent traces recorded for this service.")}</div>
        )}
      </Panel>
    </Page>
  );
}

function ServiceTrendChart({
  data,
  dataKey,
  color,
  unit,
  label,
}: {
  data: SeriesPoint[];
  dataKey: "tps" | "p95_ms";
  color: string;
  unit: string;
  label: string;
}) {
  const { t } = useI18n();

  if (!data.length) {
    return (
      <div className="grid h-72 place-items-center p-3">
        <div className="grid h-full w-full place-items-center rounded-lg border border-dashed border-[rgba(255,255,255,0.12)] text-xs text-[#8b949e]">
          {t("No telemetry points in the selected window")}
        </div>
      </div>
    );
  }

  return (
    <div className="h-72 p-3">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
          <XAxis
            dataKey="timestamp_ms"
            type="number"
            domain={["dataMin", "dataMax"]}
            minTickGap={36}
            tickFormatter={(value) =>
              new Date(Number(value)).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })
            }
            stroke="#484f58"
          />
          <YAxis stroke="#484f58" />
          <Tooltip
            {...chartTooltip}
            labelFormatter={(value) => new Date(Number(value)).toLocaleString()}
            formatter={(value: unknown) => [`${n(Number(value), 2)} ${unit}`, label]}
          />
          <Line
            type="monotone"
            dataKey={dataKey}
            name={label}
            stroke={color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: color }}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function Relation({
  title,
  items,
}: {
  title: string;
  items?: { name: string; requests: number; evidence: string }[];
}) {
  const { t } = useI18n();
  const safeItems = items || [];
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-2">
        {title}
      </div>
      {safeItems.length ? (
        <div className="divide-y divide-[rgba(255,255,255,0.04)]">
          {safeItems.slice(0, 6).map((i) => (
            <div
              className="flex items-center justify-between py-2 text-xs"
              key={i.name}
            >
              <span className="font-medium text-[#f0f3f6] truncate max-w-[180px]">{i.name}</span>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${
                    i.evidence === "confirmed"
                      ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                      : "border border-amber-500/30 bg-amber-500/10 text-amber-400"
                  }`}
                >
                  {i.evidence}
                </span>
                <span className="font-mono text-xs tabular-nums text-[#8b949e]">{n(i.requests)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-[rgba(255,255,255,0.08)] p-3 text-center text-[11px] text-[#8b949e]">
          {t("No explicit edge evidence recorded")}
        </div>
      )}
    </div>
  );
}

function SimpleTable({
  rows,
}: {
  rows?: { name: string; operation?: string; requests: number; avg_ms?: number }[];
}) {
  const { t } = useI18n();
  const safeRows = rows || [];
  return (
    <div className="divide-y divide-[rgba(255,255,255,0.04)]">
      {safeRows.map((r) => (
        <div
          key={`${r.name}:${r.operation || ""}`}
          className="flex items-center justify-between px-4 py-2.5 text-xs hover:bg-white/[0.02]"
        >
          <div className="min-w-0">
            <span className="font-medium text-[#f0f3f6]">{r.name}</span>
            {r.operation && (
              <span className="ml-2 text-[10px] text-[#8b949e]">{r.operation}</span>
            )}
          </div>
          <div className="font-mono text-xs tabular-nums text-[#8b949e]">
            {n(r.requests)}
            {r.avg_ms !== undefined && ` · ${n(r.avg_ms)} ms avg`}
          </div>
        </div>
      ))}
      {!safeRows.length && (
        <div className="p-8 text-center text-xs text-[#8b949e]">{t("No records found.")}</div>
      )}
    </div>
  );
}
