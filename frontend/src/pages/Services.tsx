import { ServiceAccessBoard } from "../components/ServiceAccessBoard";
import { useState, type ReactNode } from "react";
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
  ArrowLeft,
  ArrowRight,
} from "lucide-react";
import { EpisodeStatusBadge, type EpisodeResponse } from "../components/EpisodePrimitives";
import { FleetTriage } from "../components/FleetTriage";
import { EntityLink } from "../components/EntityLink";
import { entityPath } from "../entityRoutes";
import { api, queryString } from "../api";
import {
  ErrorState,
  InteractiveMetricCard,
  Loading,
  Page,
  Panel,
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
  const qs = queryString(filters);
  const query = useQuery({
    queryKey: ["services", qs],
    queryFn: () => api<{ items: Service[] }>(`/api/v1/services?${qs}&limit=500`),
  });
  const services = (query.data?.items || []).filter(service =>
    (!filters.service || service.name === filters.service) &&
    (!filters.environment || service.environment === filters.environment) &&
    (!filters.group || service.service_group === filters.group) &&
    (!filters.module || service.service_module === filters.module));
  const environments = new Set(services.map(service => service.environment).filter(Boolean)).size;
  const groups = new Set(services.map(service => service.service_group).filter(Boolean)).size;
  const apiCount = services.reduce((sum, service) => sum + (service.operations_count || 0), 0);
  return <Page eyebrow={t("Service inventory", "Danh mục Service")} title={t("Services")}
    description={t("Find a service, review its signals, and open its operational detail.", "Tìm Service, kiểm tra tín hiệu và mở chi tiết vận hành.")}>
    {query.isLoading ? <Loading /> : query.isError ? <><ErrorState message={query.error.message} /><button className="btn" onClick={() => query.refetch()}>{t("Retry")}</button></> : <>
      <dl className="mb-4 grid grid-cols-2 overflow-hidden rounded border border-line bg-surface lg:grid-cols-4">
        {[
          [t("Observed services", "Service đã quan sát"), n(services.length), t("Selected scope · up to 500", "Phạm vi đã chọn · tối đa 500")],
          [t("APIs", "API"), services.some(service => service.operations_count != null) ? n(apiCount) : "—", t("Across loaded services", "Trên các Service đã tải")],
          [t("Environments", "Môi trường"), n(environments), t("With observed services", "Có Service đã quan sát")],
          [t("Service groups", "Nhóm Service"), n(groups), t("From service metadata", "Theo metadata của Service")],
        ].map(([label, value, note]) => <div key={label} className="min-w-0 border-l border-line px-4 py-3 first:border-l-0 max-lg:[&:nth-child(3)]:border-l-0 max-lg:[&:nth-child(n+3)]:border-t">
          <dt className="text-xs text-muted">{label}</dt>
          <dd className="mt-1 font-mono text-xl tabular-nums text-ink">{value}</dd>
          <dd className="mt-1 text-[11px] text-muted">{note}</dd>
        </div>)}
      </dl>
      {(filters.account || filters.operation) && <p className="mb-3 rounded border border-line px-3 py-2 text-xs text-muted">{t("The catalog aggregates all APIs and principals for each service. Account and operation filters do not narrow this inventory.", "Danh mục tổng hợp tất cả API và principal của từng Service. Bộ lọc account và operation không thu hẹp danh mục này.")}</p>}
      <FleetTriage key={qs} services={services} search={`?${qs}`} catalog />
      <p className="mt-3 text-[11px] text-muted">{t("Observed telemetry is not an availability or SLO measurement. No open anomaly does not establish service health.", "Telemetry quan sát không đo độ sẵn sàng hay SLO. Không có bất thường đang mở chưa đủ để kết luận Service hoạt động tốt.")} {query.data?.items.length === 500 && t("Only the first 500 services are loaded.", "Chỉ tải 500 Service đầu tiên.")}</p>
    </>}
  </Page>;
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
  instances: { name: string; operation: string; requests: number; avg_ms?: number; avg_latency?: number; error_rate?: number }[];
  incoming: { name: string; requests: number; evidence: string }[];
  outgoing: { name: string; requests: number; evidence: string }[];
  bandwidth?: { metrics?: Record<string, number>; series?: unknown[] };
};

export type ServiceSeriesPoint = SeriesPoint & {
  requests: number;
  expected_tps?: number;
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

export function normalizeServiceBandwidth(rows: unknown) {
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

export function mergeServiceBandwidth(series: ServiceSeriesPoint[], bandwidthSeries: ReturnType<typeof normalizeServiceBandwidth>) {
  const points = new Map<number, Record<string, number>>();
  series.forEach((point) => points.set(point.timestamp_ms, { ...point, observed_tps: point.tps, expected_tps: point.baseline_rps }));
  bandwidthSeries.forEach((point) => {
    points.set(point.timestamp_ms, { ...(points.get(point.timestamp_ms) || { timestamp_ms: point.timestamp_ms }), ...point });
  });
  return [...points.values()].sort((a, b) => a.timestamp_ms - b.timestamp_ms);
}

export function normalizeServiceSeries(rows: unknown): ServiceSeriesPoint[] {
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
        expected_tps: Number(row.baseline_rps ?? row.baseline_tps ?? 0),
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

export function ServicePerformancePanel({
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
  aside,
  latencyDetail,
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
  aside?: ReactNode;
  latencyDetail?: string;
}) {
  const { t } = useI18n();
  const [selectedMetric, setSelectedMetric] = useState<ServiceChartMetric>("tps");
  const nowMs = Date.now();
  const bucketMs = 60_000;
  const completedSeries = series.filter((p) => p.timestamp_ms + bucketMs <= nowMs);
  const latest = completedSeries.length > 0 ? completedSeries[completedSeries.length - 1] : series[series.length - 1];
  const currentTps = serviceNumber(latest?.tps);
  const averageTps = totalRequests / Math.max(1, durationSec);
  const peakTps = Math.max(0, ...series.map((point) => serviceNumber(point.tps)));
  const currentP95 = serviceNumber(latest?.p95_ms);
  const currentRequestRate = serviceNumber(bandwidthMetrics.request_bytes_per_second);
  const currentResponseRate = serviceNumber(bandwidthMetrics.response_bytes_per_second);
  const currentBandwidth = serviceNumber(bandwidthMetrics.bandwidth_bytes_per_second);
  const hasBandwidth = bandwidthSeries.some((point) => point.bandwidth_available > 0 || point.request_bytes_samples + point.response_bytes_samples > 0);
  const hasExpectedTps = series.some((point) => serviceNumber(point.expected_tps) > 0);

  const tpsLines: ServiceChartLine[] = [
    { dataKey: "observed_tps", label: t("Observed TPS"), color: "var(--series-1)", width: 2.4 },
    ...(hasExpectedTps ? [{ dataKey: "expected_tps", label: t("Expected TPS"), color: "var(--series-2)", dashed: true, width: 1.5 }] : []),
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
      lines: [{ dataKey: "requests", label: t("Requests / minute"), color: "var(--series-3)", width: 2 }],
      formatAxis: (value) => `${n(value, 0)}`,
      minimumAxisMax: 1,
      available: true,
    },
    error: {
      lines: [{ dataKey: "failure_rate", label: t("Error rate"), color: "var(--bad)", width: 2.2 }],
      formatAxis: (value) => pct(value),
      minimumAxisMax: 0.01,
      available: true,
    },
    latency: {
      lines: [{ dataKey: "p95_ms", label: t("P95 Latency"), color: "var(--warn)", width: 2.2 }],
      formatAxis: (value) => `${n(value, 0)} ms`,
      minimumAxisMax: 1,
      available: true,
    },
    bandwidth: {
      lines: [
        { dataKey: "request_bytes_per_second", label: t("Request bytes/s"), color: "var(--series-3)", width: 2 },
        { dataKey: "response_bytes_per_second", label: t("Response bytes/s"), color: "var(--entity-api)", width: 2 },
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
          label={t("Latest bucket TPS", "TPS bucket cuối")}
          value={series.length ? n(currentTps, 2) : "—"}
          detail={`${t("avg")} ${n(averageTps, 2)} · ${t("peak")} ${n(peakTps, 2)}`}
          subDetail={`${n(totalRequests, 0)} ${t("requests")}`}
          data={tpsSpark}
          color="var(--series-1)"
          selected={selectedMetric === "tps"}
          onSelect={() => setSelectedMetric("tps")}
        />
        <InteractiveMetricCard
          label={t("Requests")}
          value={n(totalRequests, 0)}
          detail={t("Server transactions")}
          subDetail={`${n(Math.max(0, ...series.map((point) => point.requests)), 0)}/min peak`}
          data={requestSpark}
          color="var(--series-3)"
          selected={selectedMetric === "requests"}
          onSelect={() => setSelectedMetric("requests")}
        />
        <InteractiveMetricCard
          label={t("Error rate")}
          value={pct(failureRate)}
          detail={`≈ ${n(totalErrors, 0)} ${t("errors")}`}
          data={errorSpark}
          color="var(--bad)"
          selected={selectedMetric === "error"}
          onSelect={() => setSelectedMetric("error")}
          valueClass={failureRate >= 0.05 ? "text-bad" : "text-ink"}
        />
        <InteractiveMetricCard
          label={t("Max bucket P95", "P95 bucket lớn nhất")}
          value={`${n(worstP95, 0)} ms`}
          detail={latencyDetail ?? `${t("Across")} ${n(operationsCount, 0)} ${t("Operations").toLowerCase()}`}
          subDetail={`${t("Latest bucket", "Bucket cuối")} ${n(currentP95, 0)} ms`}
          data={latencySpark}
          color="var(--warn)"
          selected={selectedMetric === "latency"}
          onSelect={() => setSelectedMetric("latency")}
        />
        <InteractiveMetricCard
          label={t("Bandwidth")}
          value={hasBandwidth ? formatServiceByteRate(currentBandwidth) : "—"}
          detail={t("Request + response throughput")}
          subDetail={`↑ ${formatServiceByteRate(currentRequestRate)} · ↓ ${formatServiceByteRate(currentResponseRate)}`}
          data={bandwidthSpark}
          color="var(--entity-api)"
          selected={selectedMetric === "bandwidth"}
          onSelect={() => setSelectedMetric("bandwidth")}
        />
      </div>

      {!series.length && <p className="text-xs text-muted">{t("No telemetry points in the selected window")}</p>}
      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-5">
        <div className={aside ? "min-w-0 lg:col-span-3" : "col-span-full min-w-0"}>
          <Panel
            title={hasExpectedTps ? t("TPS vs Expected") : t("TPS")}
            subtitle={t("TPS on left · selected KPI on right")}
            className="flex h-full flex-col"
          >
            <div className="flex flex-1 flex-col justify-between space-y-0">
              <div className="flex h-8 min-w-0 items-center gap-4 overflow-x-auto whitespace-nowrap px-3 text-[10px] text-muted">
                {chartLegend.map(({ label, color, dashed }) => <span key={label}><span className={`mr-1 inline-block w-3 border-t-2 align-middle ${dashed ? "border-dashed" : ""}`} style={{ borderColor: color }} />{label}</span>)}
              </div>
              <div className="relative h-[230px] px-2 pb-1 pt-1">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartSeries} margin={{ top: 6, right: 16, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={52} tick={{ fill: "var(--muted)", fontSize: 10 }} tickFormatter={(value) => new Date(Number(value)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                    <YAxis yAxisId="tps" width={48} domain={[0, tpsAxisMaximum]} ticks={[0, 0.25, 0.5, 0.75, 1].map((fraction) => tpsAxisMaximum * fraction)} allowDataOverflow tick={{ fill: "var(--muted)", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(value) => n(Number(value), tpsAxisDigits)} />
                    <YAxis yAxisId="metric" orientation="right" width={78} domain={[0, rightAxisMaximum]} allowDataOverflow tick={false} axisLine={false} tickLine={false} />
                    <Tooltip {...chartTooltip} labelFormatter={(value) => new Date(Number(value)).toLocaleString()} />
                    {tpsLines.map((line) => <Line key={line.dataKey} yAxisId="tps" type="monotone" dataKey={line.dataKey} name={line.label} stroke={line.color} strokeWidth={line.width} strokeDasharray={line.dashed ? "5 4" : undefined} dot={false} connectNulls isAnimationActive={false} />)}
                    {overlayLines.map((line) => <Line key={line.dataKey} yAxisId="metric" type="monotone" dataKey={line.dataKey} name={line.label} stroke={line.color} strokeWidth={line.width} strokeDasharray={line.dashed ? "5 4" : undefined} dot={false} connectNulls isAnimationActive={false} />)}
                  </LineChart>
                </ResponsiveContainer>
                <div data-testid="service-metric-axis" aria-label={t("Selected metric scale")} className="pointer-events-none absolute bottom-[33px] right-[24px] top-[11px] flex w-[70px] flex-col justify-between text-left text-[10px] text-muted">
                  {[1, 0.75, 0.5, 0.25, 0].map((fraction) => <span key={fraction}>{rightVariable.formatAxis(rightAxisMaximum * fraction)}</span>)}
                </div>
              </div>
            </div>
          </Panel>
        </div>
        {aside && (
          <div className="min-w-0 lg:col-span-2">
            {aside}
          </div>
        )}
      </div>
    </div>
  );
}

export function RecentChangesPanel({ query, viewAllHref, search, emptyText }: {
  query: { isLoading: boolean; isError: boolean; error: Error | null; data?: EpisodeResponse };
  viewAllHref: string;
  search: string;
  emptyText: string;
}) {
  const { t } = useI18n();
  const nav = useNavigate();
  const changes = query.data?.items || [];
  return (
    <Panel
      title={t("Recent Changes")}
      subtitle={t("Latest episodes · up to 10 loaded, 5 shown", "Episode gần nhất · tải tối đa 10, hiển thị 5")}
      className="flex h-full flex-col min-w-0"
      action={
        <button onClick={() => nav(viewAllHref)} className="shrink-0 text-[11px] font-semibold text-ink hover:underline">
          {t("View all")} <ArrowRight size={12} className="inline" />
        </button>
      }
    >
      {query.isLoading ? (
        <div className="flex flex-1 items-center justify-center p-6"><Loading /></div>
      ) : query.isError ? (
        <div className="p-4"><ErrorState message={query.error?.message || ""} /></div>
      ) : changes.length ? (
        <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-line max-h-[262px]">
          {changes.slice(0, 5).map((change) => (
            <div key={change.id} className="flex items-start gap-2.5 px-3 py-2 transition hover:bg-hover">
              <span className="shrink-0"><EpisodeStatusBadge episode={change} /></span>
              <span className="min-w-0 flex-1">
                <EntityLink
                  entity={{ kind: "change", id: change.id }}
                  search={search}
                  title={change.summary}
                  className="block truncate text-xs font-semibold text-ink hover:underline"
                >
                  {change.summary}
                </EntityLink>
                <div className="mt-0.5 truncate text-[10px] text-muted">
                  {change.context.operation && change.context.target
                    ? <EntityLink entity={{ kind: "api", service: change.context.target, operation: change.context.operation }}>{change.context.operation}</EntityLink>
                    : change.context.target
                      ? <EntityLink entity={{ kind: "service", name: change.context.target }}>{change.context.target}</EntityLink>
                      : change.subject.type === "user"
                        ? <EntityLink entity={{ kind: "user", principal: change.subject.name }}>{change.subject.name}</EntityLink>
                        : <EntityLink entity={{ kind: "service", name: change.subject.name }}>{change.subject.name}</EntityLink>}
                </div>
              </span>
              <span className="shrink-0 font-mono text-[10px] text-muted">{change.last_seen_at ? new Date(change.last_seen_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-xs text-muted">{emptyText}</div>
      )}
    </Panel>
  );
}

export function ServiceDetailPage() {
  const { name = "" } = useParams();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const qs = queryString({ ...filters, service: undefined });
  const [detailTab, setDetailTab] = useState("operations");
  const [operationSearch, setOperationSearch] = useState("");
  const [operationPage, setOperationPage] = useState(0);

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
  const visibleOperations = operations.filter(operation => operation.name.toLowerCase().includes(operationSearch.toLowerCase())).sort((a, b) => b.requests * b.failure_rate - a.requests * a.failure_rate || b.requests - a.requests);
  const lastOperationPage = Math.max(0, Math.ceil(visibleOperations.length / 15) - 1);
  const currentOperationPage = Math.min(operationPage, lastOperationPage);
  const total = operations.reduce((a, b) => a + (b.requests || 0), 0);
  const totalErrors = operations.reduce((sum, operation) => sum + (operation.failure_rate || 0) * (operation.requests || 0), 0);
  const p95 = operations.length
    ? Math.max(...operations.map((o) => o.p95_ms || 0))
    : 0;
  const fail =
    operations.reduce((a, b) => a + (b.failure_rate || 0) * (b.requests || 0), 0) /
    Math.max(1, total);
  const accounts = d.accounts || ((d as any).principals || []).map((p: any) => ({ username: p.name, requests: p.requests }));
  const instances = d.instances || [];
  const series = normalizeServiceSeries(d.series);
  const bandwidthMetrics = (d as any).bandwidth?.metrics || (d as any).health || {};
  const bandwidthSeries = normalizeServiceBandwidth(d.bandwidth?.series);
  const chartSeries = mergeServiceBandwidth(series, bandwidthSeries);
  const attentionOperations = [...operations]
    .sort((a, b) => {
      const failureDelta = b.requests * (b.failure_rate || 0) - a.requests * (a.failure_rate || 0);
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
  const traces = serviceTraces.data?.items || [];

  return (
    <Page
      eyebrow={t("Service Drilldown")}
      title={name}
      description={`${serviceObj.service_group || "Core"} / ${serviceObj.service_module || "Default"} · ${t("Environment")}: ${serviceObj.environment || "production"}`}
      actions={<div className="flex flex-wrap gap-2">
        <button
          className="btn"
          onClick={() => nav(`/services?${qs}`)}
        >
          <ArrowLeft size={13} />
          {t("All Services")}
        </button>
        <button className="btn" onClick={() => nav(`/traces?${qs}&service=${encodeURIComponent(name)}`)}>{t("Open in Traces")} <ArrowRight size={13} /></button>
        </div>
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
        aside={
          <RecentChangesPanel
            query={serviceChanges}
            viewAllHref={`/changes?${qs}&service=${encodeURIComponent(name)}`}
            search={`?${qs}`}
            emptyText={t("No behavior changes for this service in the current window.")}
          />
        }
      />

      <div className="mt-4 space-y-4">
        <ServiceAccessBoard key={`${name}:${qs}`} service={name} accounts={accounts} operations={operations} filters={filters} />
      </div>
      <div className="mt-5 flex flex-wrap gap-2 border-b border-line pb-3" role="group" aria-label={t("Service detail views", "Góc nhìn Service")}>
        {[["operations", "APIs", operations.length], ["users", t("Users"), serviceUsers.data?.total ?? "—"], ["instances", t("Instances", "Instance"), instances.length], ["traces", t("Traces"), traces.length]].map(([value, label, count]) => <button key={value} aria-pressed={detailTab === value} className={`rounded border px-3 py-2 text-xs ${detailTab === value ? "border-accent bg-accent-soft text-ink font-semibold" : "border-line-strong text-muted hover:text-ink"}`} onClick={() => setDetailTab(String(value))}>{label} <span className="ml-2 font-mono">{count}</span></button>)}
      </div>
      {detailTab === "operations" && <>
      {/* 4. APIs */}
      <Panel
        title={t("Investigation priorities", "Ưu tiên điều tra")}
        subtitle={t("Operations ranked by estimated failed requests, then latency", "API xếp theo số request lỗi ước tính, sau đó Latency")}
        className="mt-4"
      >
        {attentionOperations.length ? (
          <div className="divide-y divide-line">
            {attentionOperations.map((operation) => (
              <EntityLink
                entity={{ kind: "api", service: name, operation: operation.name }}
                search={`?${qs}`}
                key={`attention-${operation.name}`}
                className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left transition hover:bg-hover"
              >
                <span className="min-w-0 truncate font-semibold text-ink hover:underline">{operation.name}</span>
                <span className="flex flex-wrap items-center gap-3 font-mono text-[11px] tabular-nums">
                  <span className={operation.failure_rate > 0.02 ? "text-bad" : "text-good"}>{pct(operation.failure_rate || 0)} {t("error")}</span>
                  <span className={operation.p95_ms > 500 ? "text-warn" : "text-entity-user"}>{n(operation.p95_ms || 0, 1)} ms p95</span>
                  <span className="text-muted">{n(operation.requests || 0, 0)} {t("requests")}</span>
                </span>
              </EntityLink>
            ))}
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-muted">{t("No operations observed in this window")}</div>
        )}
      </Panel>

      <Panel
        title={t("Operation Performance Inventory")}
        subtitle={t("Maximum bucket percentiles · error rate weighted by requests", "Phân vị bucket lớn nhất · tỷ lệ lỗi có trọng số theo request")}
        action={<input aria-label={t("Search APIs", "Tìm API")} placeholder={t("Search APIs", "Tìm API")} value={operationSearch} onChange={event => { setOperationSearch(event.target.value); setOperationPage(0); }} className="w-40 max-w-full rounded border border-line-strong bg-surface-2 px-3 py-2 text-xs" />}
        className="mt-4"
      >
        <div className="overflow-auto scrollbar">
          <table className="w-full min-w-[850px] text-left text-xs">
            <thead>
              <tr className="border-b border-line">
                {[
                  t("Operation"),
                  t("Volume"),
                  t("Max bucket P50", "P50 bucket lớn nhất"),
                  t("Max bucket P95", "P95 bucket lớn nhất"),
                  t("Max bucket P99", "P99 bucket lớn nhất"),
                  t("Error rate"),
                  t("Traffic share", "Tỷ trọng request"),
                ].map((h) => (
                  <th key={h} className="table-head px-4 py-2.5">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {visibleOperations.slice(currentOperationPage * 15, currentOperationPage * 15 + 15).map((o) => (
                <tr
                  key={o.name}
                  onClick={() => nav(entityPath({ kind: "api", service: name, operation: o.name }) + `?${qs}`)}
                  className="cursor-pointer hover:bg-hover transition"
                >
                  <td className="px-4 py-2.5 font-medium text-ink"><EntityLink entity={{ kind: "api", service: name, operation: o.name }} search={`?${qs}`} className="hover:underline">{o.name}</EntityLink></td>
                  <td className="px-4 font-mono tabular-nums text-ink text-ink">{n(o.requests)}</td>
                  <td className="px-4 font-mono tabular-nums text-muted text-muted">{n(o.p50_ms || 0)} ms</td>
                  <td className="px-4 font-mono tabular-nums text-entity-user">{n(o.p95_ms || 0)} ms</td>
                  <td className="px-4 font-mono tabular-nums text-bad text-bad">{n(o.p99_ms || 0)} ms</td>
                  <td className="px-4 font-mono tabular-nums text-warn text-warn">{pct(o.failure_rate || 0)}</td>
                  <td className="px-4 font-mono tabular-nums">{pct(total ? o.requests / total : 0)}</td>
                </tr>
              ))}
              {!visibleOperations.length && <tr><td colSpan={7} className="p-8 text-center text-muted">{t("No matching APIs", "Không có API phù hợp")}</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line p-3 text-xs text-muted">
          <span>{visibleOperations.length ? currentOperationPage * 15 + 1 : 0}–{Math.min(currentOperationPage * 15 + 15, visibleOperations.length)} / {visibleOperations.length} APIs</span>
          <div className="flex gap-2"><button className="btn disabled:opacity-40" disabled={currentOperationPage === 0} onClick={() => setOperationPage(currentOperationPage - 1)}>{t("Previous", "Trước")}</button><button className="btn disabled:opacity-40" disabled={currentOperationPage === lastOperationPage} onClick={() => setOperationPage(currentOperationPage + 1)}>{t("Next", "Tiếp")}</button></div>
        </div>
      </Panel>

      </>}
      {detailTab === "users" && <>
      {/* 5. Users */}
      <Panel title={t("Users")} subtitle={t("Observed principals · up to 10 loaded", "Principal đã quan sát · tải tối đa 10")} className="mt-4">
        {serviceUsers.isLoading ? <Loading /> : serviceUsers.isError ? <ErrorState message={serviceUsers.error.message} /> :
        <div className="overflow-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-line">
                {[t("Principal Identity"), t("Volume"), t("Callers"), t("Operations"), t("First seen"), t("Last seen"), t("Recent change")].map((h) => (
                  <th className="table-head px-3 py-2" key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(serviceUsers.data?.items || []).map((u: any) => (
                <tr key={u.principal_name} onClick={() => nav(entityPath({ kind: "user", principal: u.principal_name }) + `?${qs}`)} className="cursor-pointer hover:bg-hover transition">
                  <td className="px-3 py-2 font-mono text-ink"><EntityLink entity={{ kind: "user", principal: u.principal_name }} search={`?${qs}`} className="hover:underline">{u.principal_name}</EntityLink></td>
                  <td className="px-3 font-mono tabular-nums text-ink text-ink">{n(u.total_requests || u.requests || 0, 0)}</td>
                  <td className="px-3 font-mono tabular-nums text-muted text-muted">{u.unique_callers ?? u.callers ?? "—"}</td>
                  <td className="px-3 font-mono tabular-nums text-muted text-muted">{u.unique_operations ?? u.operations ?? "—"}</td>
                  <td className="px-3 text-muted text-muted">{u.first_seen ? new Date(u.first_seen).toLocaleString() : "—"}</td>
                  <td className="px-3 text-muted text-muted">{u.last_seen ? new Date(u.last_seen).toLocaleString() : "—"}</td>
                  <td className="px-3">{u.recent_changes || u.recent_change ? <span className="rounded-[2px] border border-warn px-1.5 py-0.5 text-[10px] text-warn font-semibold">{t("Changed")}</span> : "—"}</td>
                </tr>
              ))}
              {!(serviceUsers.data?.items || []).length && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-xs text-muted">{t("No users recorded for this service in this window.")}</td></tr>
              )}
            </tbody>
          </table>
        </div>}
      </Panel>

      <div className="mt-4">
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

      </div></>}
      {detailTab === "instances" && <div className="mt-4">
        <Panel
          title={t("Instance Load & Distribution")}
          subtitle={t("Traffic balance across recorded nodes")}
        >
          <SimpleTable rows={instances.map(instance => ({ ...instance, avg_ms: instance.avg_ms ?? instance.avg_latency }))} />
        </Panel>
      </div>

      }
      {detailTab === "traces" && <>
      {/* 9. Representative Traces */}
      <Panel
        title={t("Representative Traces")}
        subtitle={t("Recent distributed traces for this service")}
        className="mt-4"
        action={<button onClick={() => nav(`/traces?${qs}&service=${encodeURIComponent(name)}`)} className="text-[11px] font-semibold text-ink hover:underline">{t("Open in Traces")} <ArrowRight size={12} className="inline" /></button>}
      >
        {serviceTraces.isLoading ? (
          <Loading />
        ) : serviceTraces.isError ? (<ErrorState message={serviceTraces.error.message} />) : traces.length ? (
          <div className="overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-line">
                  <th className="table-head px-3 py-2">{t("Trace ID")}</th>
                  <th className="table-head px-3 py-2">{t("Operation")}</th>
                  <th className="table-head px-3 py-2">{t("Principal")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Duration")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Status")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {traces.map((tr: any) => (
                  <tr
                    key={tr.trace_id || tr.id}
                    onClick={() => nav(`/traces/${encodeURIComponent(tr.trace_id || tr.id)}`)}
                    className="cursor-pointer hover:bg-hover transition"
                  >
                    <td className="px-3 py-2 font-mono text-ink">{(tr.trace_id || tr.id || "").slice(0, 16)}…</td>
                    <td className="px-3 text-ink">{tr.operation || tr.name || "—"}</td>
                    <td className="px-3 font-mono text-muted">{tr.principal_name || tr.user || "—"}</td>
                    <td className="px-3 text-right font-mono tabular-nums text-ink">{tr.duration_ms != null ? `${Number(tr.duration_ms).toFixed(1)} ms` : "—"}</td>
                    <td className="px-3 text-right font-mono">
                      <span className={`rounded-[2px] border px-1.5 py-0.5 text-[10px] uppercase font-semibold ${String(tr.status_code || tr.http_status || tr.status).startsWith("5") ? "text-bad border-bad" : "text-good border-good"}`}>
                        {tr.status_code || tr.http_status || tr.status || "OK"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-muted">{t("No recent traces recorded for this service.")}</div>
        )}
      </Panel></>}
    </Page>
  );
}

function SimpleTable({
  rows,
}: {
  rows?: { name: string; operation?: string; requests: number; avg_ms?: number }[];
}) {
  const { t } = useI18n();
  const safeRows = rows || [];
  const total = safeRows.reduce((sum, row) => sum + row.requests, 0);
  return (
    <div className="divide-y divide-line">
      {safeRows.map((r) => (
        <div
          key={`${r.name}:${r.operation || ""}`}
          className="flex items-center justify-between px-4 py-2.5 text-xs hover:bg-hover"
        >
          <div className="min-w-0">
            <span className="break-all font-medium text-ink">{r.name}</span>
            {r.operation && (
              <span className="ml-2 text-[10px] text-muted">{r.operation}</span>
            )}
          </div>
          <div className="shrink-0 pl-3 text-right font-mono text-xs tabular-nums text-muted">
            {n(r.requests)} · {pct(total ? r.requests / total : 0)}
            {r.avg_ms !== undefined && ` · ${n(r.avg_ms)} ms avg`}
          </div>
        </div>
      ))}
      {!safeRows.length && (
        <div className="p-8 text-center text-xs text-muted">{t("No records found.")}</div>
      )}
    </div>
  );
}
