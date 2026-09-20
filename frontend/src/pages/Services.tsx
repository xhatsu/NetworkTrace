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
  ArrowLeft,
  Box,
  Search,
} from "lucide-react";
import { api, queryString } from "../api";
import {
  ErrorState,
  Loading,
  MetricCard,
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
};

function normalizeServiceSeries(rows: unknown): SeriesPoint[] {
  if (!Array.isArray(rows)) return [];

  return rows
    .map((value): SeriesPoint | null => {
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
    .filter((point): point is SeriesPoint => point !== null)
    .sort((a, b) => a.timestamp_ms - b.timestamp_ms);
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
  const serviceUsers = useQuery({
    queryKey: ["service-users", name, qs],
    queryFn: () => api<{items: Array<{principal_name:string;requests:number;callers:number;operations:number;first_seen:number;last_seen:number;recent_change:number}>}>(`/api/v1/services/${encodeURIComponent(name)}/users?${qs}`),
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
  const latestTps = series.length ? series[series.length - 1].tps : 0;
  const bandwidthMetrics = (d as any).bandwidth?.metrics || (d as any).health || {};
  const bandwidthBytesPerSecond = Number(bandwidthMetrics.bandwidth_bytes_per_second || 0);
  const formatMiBRate = (value: number) => `${(Math.max(0, Number(value) || 0) / (1024 * 1024)).toFixed(2)} MiB/s`;
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
      <Panel
        title={t("TPS")}
        subtitle={t("Observed service throughput over the selected window")}
        action={<span className="font-mono text-[11px] text-[#5794f2]">{n(latestTps, 2)} TPS</span>}
      >
        <TpsLineChart data={series} />
      </Panel>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <MetricCard
          label={t("Observed Volume")}
          value={n(total)}
          detail={t("Server transactions")}
        />
        <MetricCard
          label={t("Request Rate")}
          value={`${n(total / durationSec, 2)}/s`}
          detail={t("Observed rate in window")}
        />
        <MetricCard
          label={t("Worst Operation p95")}
          value={`${n(p95)} ms`}
          detail={`${t("Across")} ${operations.length} ${t("Operations").toLowerCase()}`}
          tone={p95 > 500 ? "bad" : "normal"}
        />
        <MetricCard
          label={t("Failure Rate")}
          value={pct(fail)}
          detail={`n=${n(total)} ${t("requests")}`}
          tone={fail > 0.02 ? "bad" : "normal"}
        />
        <MetricCard
          label={t("Bandwidth")}
          value={formatMiBRate(bandwidthBytesPerSecond)}
          detail={t("Request + response throughput")}
          accent="sky"
        />
      </div>

      <Panel
        title={t("Needs attention")}
        subtitle={t("Operations prioritized by failure rate, latency tail, and observed volume")}
        className="mt-4"
      >
        {attentionOperations.length ? (
          <div className="divide-y divide-[rgba(255,255,255,0.06)]">
            {attentionOperations.map((operation) => (
              <button
                type="button"
                key={`attention-${operation.name}`}
                onClick={() => nav(`/services/${encodeURIComponent(name)}/apis/${encodeURIComponent(operation.name)}?${qs}`)}
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition hover:bg-white/[0.04]"
              >
                <span className="min-w-0 truncate font-medium text-[#f5f3fa]">{operation.name}</span>
                <span className="flex shrink-0 items-center gap-4 font-mono text-[11px] tabular-nums">
                  <span className={operation.failure_rate > 0.02 ? "text-rose-300" : "text-emerald-300"}>{pct(operation.failure_rate || 0)} {t("error")}</span>
                  <span className={operation.p95_ms > 500 ? "text-amber-300" : "text-violet-300"}>{n(operation.p95_ms || 0, 1)} ms p95</span>
                  <span className="text-[#c4bdd9]">{n(operation.requests || 0, 0)} {t("requests")}</span>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-[#c4bdd9]">{t("No operations observed in this window")}</div>
        )}
      </Panel>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel
          title={t("P95 Latency")}
          subtitle={t("Service latency over time")}
        >
          <ServiceTrendChart
            data={series}
            dataKey="p95_ms"
            color="#f43f5e"
            unit="ms"
            label={t("P95 Latency")}
          />
        </Panel>

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

      <Panel
        title={t("Operation Performance Inventory")}
        subtitle={t("Latency percentiles from merged logarithmic histograms · Status codes breakdown")}
        className="mt-4"
      >
        <div className="overflow-auto scrollbar">
          <table className="w-full min-w-[850px]">
            <thead>
              <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01]">
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
            <tbody>
              {operations.map((o) => (
                <tr
                  key={o.name}
                  onClick={() => nav(`/services/${encodeURIComponent(name)}/apis/${encodeURIComponent(o.name)}?${qs}`)}
                  className="cursor-pointer border-b border-[rgba(255,255,255,0.04)] transition hover:bg-white/[0.03]"
                >
                  <td className="px-4 py-3 text-xs font-medium text-cyan-300">{o.name}</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#c9d1d9]">{n(o.requests)}</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">{n(o.p50_ms || 0)} ms</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#818cf8]">{n(o.p95_ms || 0)} ms</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#f43f5e]">{n(o.p99_ms || 0)} ms</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">{pct(o.slow_rate || 0)}</td>
                  <td className="px-4 font-mono text-xs tabular-nums">
                    <span className="text-emerald-400">{n(o.status_2xx || 0)}</span>
                    <span className="text-[#6e7681]"> / </span>
                    <span className="text-amber-400">{n(o.status_4xx || 0)}</span>
                    <span className="text-[#6e7681]"> / </span>
                    <span className="text-rose-400">{n(o.status_5xx || 0)}</span>
                  </td>
                </tr>
              ))}
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
      <Panel title={t("Users")} subtitle={t("Principals observed using this service · click to open User Intelligence")} className="mt-4">
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                {[t("Principal Identity"), t("Volume"), t("Callers"), t("Operations"), t("First seen"), t("Last seen"), t("Recent change")].map((h) => (
                  <th className="table-head px-3 py-2" key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(serviceUsers.data?.items || []).map((u) => (
                <tr key={u.principal_name} onClick={() => nav(`/users/${encodeURIComponent(u.principal_name)}?${qs}`)} className="cursor-pointer border-t border-white/[.05] hover:bg-white/[.03]">
                  <td className="px-3 py-2 font-mono text-indigo-300">{u.principal_name}</td>
                  <td className="px-3 font-mono">{n(u.requests, 0)}</td>
                  <td className="px-3 font-mono">{u.callers}</td>
                  <td className="px-3 font-mono">{u.operations}</td>
                  <td className="px-3 text-[#8b949e]">{new Date(u.first_seen).toLocaleString()}</td>
                  <td className="px-3 text-[#8b949e]">{new Date(u.last_seen).toLocaleString()}</td>
                  <td className="px-3">{u.recent_change ? <span className="rounded bg-amber-500/10 px-2 py-1 text-amber-400">{t("Changed")}</span> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
