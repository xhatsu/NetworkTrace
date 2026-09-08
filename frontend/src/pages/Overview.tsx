import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  AlertOctagon,
  ArrowRight,
  Clock,
  ExternalLink,
  Layers,
  RefreshCw,
  Zap,
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
import type { Anomaly, SeriesPoint, Summary } from "../types";

type Degraded = {
  service_name: string;
  name: string;
  current_p95_ms: number;
  baseline_p95_ms: number;
  absolute_change_ms: number;
  relative_change: number | null;
  current_samples: number;
  baseline_samples: number;
};

type Rankings = {
  services: {
    name: string;
    requests: number;
    avg_ms: number;
    failure_rate: number;
  }[];
  operations: {
    service_name: string;
    name: string;
    requests: number;
    avg_ms: number;
    slow_rate: number;
  }[];
  accounts: { name: string; requests: number }[];
  degraded_absolute: Degraded[];
  degraded_relative: Degraded[];
};

type Heat = {
  service_name: string;
  bucket_ms: number;
  samples: number;
  avg_ms: number;
  failure_rate: number;
};

export function OverviewPage() {
  const { filters, setFilter } = useFilters();
  const nav = useNavigate();
  const qs = queryString(filters);

  const summary = useQuery({
    queryKey: ["summary", qs],
    queryFn: () => api<Summary>(`/api/v1/dashboard/summary?${qs}`),
    refetchInterval: 60000,
  });

  const series = useQuery({
    queryKey: ["series", qs],
    queryFn: () =>
      api<{ items: SeriesPoint[] }>(`/api/v1/dashboard/series?${qs}`),
    refetchInterval: 60000,
  });

  const ranks = useQuery({
    queryKey: ["rankings", qs],
    queryFn: () => api<Rankings>(`/api/v1/dashboard/rankings?${qs}`),
  });

  const heat = useQuery({
    queryKey: ["heatmap", qs],
    queryFn: () => api<{ items: Heat[] }>(`/api/v1/dashboard/heatmap?${qs}`),
  });

  const anomalies = useQuery({
    queryKey: ["anomalies", qs],
    queryFn: () => api<{ items: Anomaly[] }>(`/api/v1/anomalies?${qs}`),
  });
  const userChanges = useQuery({
    queryKey: ["overview-user-changes", qs],
    queryFn: () => api<{items: Array<{id:number;principal_name:string;change_type:string;detected_at:number;severity:string}>}>(`/api/v1/user-changes?${qs}&limit=5`),
  });

  if (summary.isLoading || series.isLoading) {
    return (
      <Page
        eyebrow="System Health"
        title="Live Estate Overview"
        description="Observed OpenTelemetry server transactions with transparent coverage."
      >
        <Loading />
      </Page>
    );
  }

  if (summary.error || series.error) {
    return (
      <Page
        eyebrow="System Health"
        title="Live Estate Overview"
        description=""
      >
        <ErrorState
          message={(summary.error || series.error)?.message || "Unable to load estate metrics."}
        />
      </Page>
    );
  }

  const s = summary.data!;
  const points = series.data?.items || [];

  return (
    <Page
      eyebrow="Estate Monitor"
      title="Transaction Health & Latency Distribution"
      description="Real-time OpenTelemetry ingestion metrics, latency percentiles, error rates, and identity distributions."
      actions={
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-md border border-[rgba(255,255,255,0.08)] bg-white/[0.02] px-2.5 py-1 text-xs text-[#8b949e]">
            <RefreshCw size={12} className="text-emerald-400" />
            <span>Updated {age(s.latest_ingested_ms)}</span>
          </div>
          <div className="chip">
            Coverage: <span className="font-mono text-[#f0f3f6]">{s.sampling_coverage}</span>
          </div>
        </div>
      }
    >
      {/* 8 Primary Signal Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <MetricCard
          label="Observed RPS"
          value={n(s.observed_rps, 2)}
          detail={`${n(s.total_requests)} HTTP in window`}
        />
        <MetricCard
          label="Observed TPS"
          value={n(s.observed_tps, 2)}
          detail={
            s.tps_equals_rps
              ? "Equivalent to RPS"
              : "All server transactions"
          }
        />
        <MetricCard
          label="Total Volume"
          value={n(s.total_requests)}
          detail={`${n(s.sample_count)} span records`}
        />
        <MetricCard
          label="Active Services"
          value={n(s.active_services, 0)}
          detail="Traffic in window"
        />
        <MetricCard
          label="System Accounts"
          value={n(s.active_accounts, 0)}
          detail="Presented identities"
        />
        <MetricCard
          label="p95 Latency"
          value={`${n(s.p95_latency_ms)} ms`}
          detail={`Log merged · n=${n(s.sample_count)}`}
          tone={s.p95_latency_ms > 500 ? "bad" : "normal"}
        />
        <MetricCard
          label="HTTP 5xx Rate"
          value={pct(s.http_5xx_rate)}
          detail="Server-side errors"
          tone={s.http_5xx_rate > 0.02 ? "bad" : "normal"}
        />
        <MetricCard
          label="Active Anomalies"
          value={String(s.active_anomalies)}
          detail="Open or acknowledged"
          tone={s.active_anomalies ? "bad" : "good"}
        />
      </div>

      {/* Primary Charts: Throughput and Latency */}
      <div className="mt-4 grid gap-4 lg:grid-cols-12">
        <Panel
          title="Throughput & Baselines"
          subtitle="60s bucketed HTTP RPS and server TPS vs historical baseline"
          className="lg:col-span-7"
        >
          <div className="h-[290px] p-3">
            <ResponsiveContainer>
              <ComposedChart data={points}>
                <defs>
                  <linearGradient id="rpsGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis
                  dataKey="timestamp_ms"
                  tickFormatter={(v) => formatTime(v, filters.timezone)}
                  minTickGap={50}
                  stroke="#484f58"
                />
                <YAxis width={40} stroke="#484f58" />
                <Tooltip
                  {...chartTooltip}
                  labelFormatter={(v) => formatTime(Number(v), filters.timezone)}
                />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Area
                  type="monotone"
                  dataKey="rps"
                  name="Observed RPS"
                  stroke="#818cf8"
                  fill="url(#rpsGrad)"
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="tps"
                  name="Observed TPS"
                  stroke="#10b981"
                  strokeWidth={1.5}
                  dot={false}
                />
                <Line
                  dataKey="baseline_rps"
                  name="Robust Baseline"
                  stroke="#64748b"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                  dot={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel
          title="Latency Distribution"
          subtitle="Merged logarithmic histogram percentiles (p50 / p95 / p99)"
          className="lg:col-span-5"
        >
          <div className="h-[290px] p-3">
            <ResponsiveContainer>
              <AreaChart data={points}>
                <defs>
                  <linearGradient id="p95Grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#818cf8" stopOpacity={0.2} />
                    <stop offset="100%" stopColor="#818cf8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis
                  dataKey="timestamp_ms"
                  tickFormatter={(v) => formatTime(v, filters.timezone)}
                  minTickGap={50}
                  stroke="#484f58"
                />
                <YAxis width={45} stroke="#484f58" unit="ms" />
                <Tooltip {...chartTooltip} />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Area
                  dataKey="p99_ms"
                  name="p99 Latency"
                  stroke="#f43f5e"
                  fill="#f43f5e"
                  fillOpacity={0.05}
                  strokeWidth={1.5}
                />
                <Area
                  dataKey="p95_ms"
                  name="p95 Latency"
                  stroke="#818cf8"
                  fill="url(#p95Grad)"
                  strokeWidth={1.5}
                />
                <Area
                  dataKey="p50_ms"
                  name="p50 Median"
                  stroke="#10b981"
                  fill="#10b981"
                  fillOpacity={0.05}
                  strokeWidth={1.5}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      {/* Latency Heatmap and Error Rate Series */}
      <div className="mt-4 grid gap-4 lg:grid-cols-12">
        <Panel
          title="Service × Time Heatmap"
          subtitle="5-minute bucketed average latency — click any service to drill into detailed traces"
          className="lg:col-span-7"
        >
          <Heatmap
            rows={heat.data?.items || []}
            timezone={filters.timezone}
            onService={(name) =>
              nav(`/services/${encodeURIComponent(name)}?${qs}`)
            }
          />
        </Panel>

        <Panel
          title="Error & Status Rates"
          subtitle="HTTP 5xx, 4xx, and outcome failure proportions per minute"
          className="lg:col-span-5"
        >
          <div className="h-[270px] p-3">
            <ResponsiveContainer>
              <AreaChart data={points}>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis
                  dataKey="timestamp_ms"
                  tickFormatter={(v) => formatTime(v, filters.timezone)}
                  minTickGap={50}
                  stroke="#484f58"
                />
                <YAxis
                  tickFormatter={(v) => `${Math.round(v * 100)}%`}
                  width={42}
                  stroke="#484f58"
                />
                <Tooltip
                  {...chartTooltip}
                  formatter={(v) => `${(Number(v) * 100).toFixed(2)}%`}
                />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Area
                  dataKey="http_5xx_rate"
                  name="HTTP 5xx"
                  stackId="status"
                  stroke="#ef4444"
                  fill="#ef4444"
                  fillOpacity={0.25}
                />
                <Area
                  dataKey="http_4xx_rate"
                  name="HTTP 4xx"
                  stackId="status"
                  stroke="#f59e0b"
                  fill="#f59e0b"
                  fillOpacity={0.2}
                />
                <Line
                  dataKey="failure_rate"
                  name="Failure Rate"
                  stroke="#c084fc"
                  strokeWidth={1.5}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      {/* Rankings: Services, Operations, Accounts */}
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Panel
          title="Top Services by Volume"
          subtitle="Click to view operation breakdown and dependency edges"
        >
          <RankTable
            rows={ranks.data?.services || []}
            onClick={(name) =>
              nav(`/services/${encodeURIComponent(name)}?${qs}`)
            }
          />
        </Panel>

        <Panel
          title="Top Operations"
          subtitle="Transaction count and slow rate fraction (>1s)"
        >
          <div className="overflow-auto max-h-[360px] scrollbar">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01]">
                  <th className="table-head px-4 py-2.5">Operation</th>
                  <th className="table-head text-right pr-4">Requests</th>
                  <th className="table-head text-right pr-4">Slow %</th>
                </tr>
              </thead>
              <tbody>
                {(ranks.data?.operations || []).map((row) => (
                  <tr
                    key={`${row.service_name}-${row.name}`}
                    className="cursor-pointer border-b border-[rgba(255,255,255,0.04)] transition hover:bg-white/[0.04]"
                    onClick={() => {
                      setFilter("operation", row.name);
                      nav(
                        `/services/${encodeURIComponent(row.service_name)}?${queryString({ ...filters, operation: row.name })}`,
                      );
                    }}
                  >
                    <td className="max-w-[190px] px-4 py-2.5">
                      <div className="truncate text-xs font-medium text-[#f0f3f6]">
                        {row.name}
                      </div>
                      <div className="truncate text-[10px] text-[#8b949e]">
                        {row.service_name}
                      </div>
                    </td>
                    <td className="text-right pr-4 font-mono text-xs tabular-nums text-[#c9d1d9]">
                      {n(row.requests)}
                    </td>
                    <td className="text-right pr-4 font-mono text-xs tabular-nums text-[#8b949e]">
                      {pct(row.slow_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel
          title="Identity Volume (Accounts)"
          subtitle="Presented request identity volume distribution"
        >
          <div className="h-[320px] p-3">
            <ResponsiveContainer>
              <BarChart data={ranks.data?.accounts || []} layout="vertical">
                <CartesianGrid stroke="rgba(255,255,255,0.05)" horizontal={false} />
                <XAxis type="number" hide />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={100}
                  tick={{ fill: "#8b949e", fontSize: 11 }}
                  stroke="#484f58"
                />
                <Tooltip {...chartTooltip} />
                <Bar
                  dataKey="requests"
                  fill="#6366f1"
                  radius={[0, 4, 4, 0]}
                  onClick={(row) =>
                    nav(
                      `/accounts/${encodeURIComponent(String(row.name))}?${qs}`,
                    )
                  }
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      {/* Degradations */}
      <Panel
        title="Top Degraded Operations"
        subtitle="p95 latency shifts versus prior baseline window (calculated from merged histograms)"
        className="mt-4"
      >
        <div className="grid gap-px bg-[rgba(255,255,255,0.06)] lg:grid-cols-2">
          <DegradedTable
            title="Largest Absolute Increase (ms)"
            rows={ranks.data?.degraded_absolute || []}
          />
          <DegradedTable
            title="Largest Relative Increase (%)"
            rows={ranks.data?.degraded_relative || []}
          />
        </div>
      </Panel>

      {/* Recent Anomalies */}
      <Panel
        title="Recent Structural Anomalies"
        subtitle="Wilson score and MAD baseline deviations with calculated evidence"
        className="mt-4"
        action={
          <button
            onClick={() => nav(`/anomalies?${qs}`)}
            className="btn text-indigo-400 hover:text-indigo-300"
          >
            View all findings
            <ArrowRight size={12} />
          </button>
        }
      >
        <div className="overflow-auto scrollbar">
          <table className="w-full min-w-[860px]">
            <thead>
              <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01]">
                {[
                  "Severity",
                  "Entity / Type",
                  "Current Value",
                  "Expected Baseline",
                  "Delta",
                  "Samples",
                  "Detected",
                  "Status",
                ].map((h) => (
                  <th className="table-head px-4 py-2.5" key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {anomalies.data?.items.slice(0, 6).map((a) => (
                <tr
                  key={a.id}
                  onClick={() => nav(`/anomalies/${a.id}`)}
                  className="cursor-pointer border-b border-[rgba(255,255,255,0.04)] transition hover:bg-white/[0.03]"
                >
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                        a.severity === "critical"
                          ? "border border-rose-500/30 bg-rose-500/10 text-rose-400"
                          : a.severity === "warning"
                            ? "border border-amber-500/30 bg-amber-500/10 text-amber-400"
                            : "border border-indigo-500/30 bg-indigo-500/10 text-indigo-400"
                      }`}
                    >
                      {a.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-xs font-medium text-[#f0f3f6]">{a.entity_id}</div>
                    <div className="text-[10px] text-[#8b949e]">
                      {a.anomaly_type.replaceAll("_", " ")}
                    </div>
                  </td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#f0f3f6]">
                    {n(a.current_value)} {a.unit}
                  </td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">
                    {a.baseline_value === null ? "—" : n(a.baseline_value)}
                  </td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#f43f5e]">
                    {a.percent_change == null && a.delta_percentage == null
                      ? (a.absolute_difference != null ? n(a.absolute_difference) : "n/a")
                      : `${Number(a.percent_change ?? a.delta_percentage ?? 0) > 0 ? "+" : ""}${Number(a.percent_change ?? a.delta_percentage ?? 0).toFixed(0)}%`}
                  </td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">
                    {n(a.current_samples)}
                  </td>
                  <td className="px-4 text-xs text-[#8b949e]">
                    {age(a.last_detected_ms)}
                  </td>
                  <td className="px-4">
                    <span className="chip uppercase text-[10px]">{a.status}</span>
                  </td>
                </tr>
              ))}
              {!anomalies.data?.items.length && (
                <tr>
                  <td
                    colSpan={8}
                    className="p-12 text-center text-xs text-[#8b949e]"
                  >
                    No anomalies detected in the selected time window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Recent User Behavior Changes" subtitle="Credential relationship changes during the selected period" className="mt-4" action={<button className="btn" onClick={()=>nav(`/user-changes?${qs}`)}>View all <ArrowRight size={12}/></button>}>
        <div className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-5">{(userChanges.data?.items||[]).map(change=><button key={change.id} onClick={()=>nav(`/users/${encodeURIComponent(change.principal_name)}?${qs}`)} className="rounded-lg border border-white/[.07] bg-white/[.02] p-3 text-left hover:border-indigo-500/40"><div className="font-mono text-xs text-indigo-300">{change.principal_name}</div><div className="mt-2 text-[10px] font-semibold uppercase text-amber-400">{change.change_type.replaceAll("_"," ")}</div><div className="mt-1 text-[10px] text-[#8b949e]">{age(change.detected_at)}</div></button>)}{!userChanges.data?.items.length&&<div className="p-3 text-xs text-[#8b949e]">No user behavior changes in this window.</div>}</div>
      </Panel>

      {/* Footer caveats / methodology */}
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[rgba(255,255,255,0.06)] pt-4 text-[11px] text-[#8b949e]">
        <div className="flex items-center gap-2">
          <Clock size={12} className="text-indigo-400" />
          <span>60-second rollup granularity</span>
          <span>·</span>
          <span>Fixed logarithmic histogram bounds (48 bins)</span>
          <span>·</span>
          <span>Percentiles never averaged</span>
        </div>
        <div>
          <span>Observed records only · No business throughput claim</span>
        </div>
      </div>
    </Page>
  );
}

function RankTable({
  rows,
  onClick,
}: {
  rows: Rankings["services"];
  onClick: (name: string) => void;
}) {
  const max = Math.max(...rows.map((r) => r.requests), 1);
  return (
    <div className="divide-y divide-[rgba(255,255,255,0.04)]">
      {rows.map((r, i) => (
        <button
          key={r.name}
          onClick={() => onClick(r.name)}
          className="group grid w-full grid-cols-[24px_1fr_auto] items-center gap-3 px-4 py-2.5 text-left transition hover:bg-white/[0.03]"
        >
          <span className="font-mono text-[10px] text-[#6e7681]">
            {String(i + 1).padStart(2, "0")}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-xs font-medium text-[#f0f3f6] group-hover:text-indigo-300 transition">
              {r.name}
            </span>
            <span className="mt-1 block h-1 w-full overflow-hidden rounded-full bg-white/[0.06]">
              <span
                className="block h-full rounded-full bg-indigo-500 transition-all duration-300"
                style={{ width: `${(r.requests / max) * 100}%` }}
              />
            </span>
          </span>
          <span className="font-mono text-xs tabular-nums text-[#8b949e]">
            {n(r.requests)}
          </span>
        </button>
      ))}
    </div>
  );
}

function DegradedTable({ title, rows }: { title: string; rows: Degraded[] }) {
  return (
    <div className="bg-[#0e1116] p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-3">
        {title}
      </div>
      <div className="divide-y divide-[rgba(255,255,255,0.04)]">
        {rows.slice(0, 6).map((row) => (
          <div
            key={`${row.service_name}:${row.name}`}
            className="grid grid-cols-[1fr_auto] gap-3 py-2.5 first:pt-0 last:pb-0"
          >
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-[#f0f3f6]">{row.name}</div>
              <div className="mt-0.5 truncate text-[10px] text-[#8b949e]">
                {row.service_name} · n={n(row.current_samples)} vs {n(row.baseline_samples)}
              </div>
            </div>
            <div className="text-right font-mono text-xs tabular-nums">
              <div className={row.absolute_change_ms > 0 ? "text-[#f43f5e]" : "text-[#10b981]"}>
                {row.absolute_change_ms > 0 ? "+" : ""}
                {n(row.absolute_change_ms)} ms
              </div>
              <div className="mt-0.5 text-[10px] text-[#8b949e]">
                {row.relative_change == null
                  ? "n/a"
                  : `${Number(row.relative_change) > 0 ? "+" : ""}${(Number(row.relative_change) * 100).toFixed(0)}%`}
              </div>
            </div>
          </div>
        ))}
        {!rows.length && (
          <div className="py-8 text-center text-xs text-[#8b949e]">
            No operations with sufficient comparison samples in both windows.
          </div>
        )}
      </div>
    </div>
  );
}

function Heatmap({
  rows,
  onService,
  timezone,
}: {
  rows: Heat[];
  onService: (name: string) => void;
  timezone: string;
}) {
  const services = [...new Set(rows.map((r) => r.service_name))].slice(0, 12);
  const buckets = [...new Set(rows.map((r) => r.bucket_ms))]
    .sort((a, b) => a - b)
    .slice(-24);
  const lookup = new Map(rows.map((r) => [`${r.service_name}:${r.bucket_ms}`, r]));

  return (
    <div className="overflow-auto p-4 scrollbar">
      <div
        className="grid min-w-[620px] gap-1.5"
        style={{
          gridTemplateColumns: `140px repeat(${Math.max(1, buckets.length)}, 1fr)`,
        }}
      >
        {services.map((service) => (
          <div className="contents" key={service}>
            <button
              onClick={() => onService(service)}
              className="truncate pr-2 text-left text-[11px] font-medium text-[#8b949e] hover:text-[#f0f3f6] transition"
              title={service}
            >
              {service}
            </button>
            {buckets.map((bucket) => {
              const cell = lookup.get(`${service}:${bucket}`);
              const intensity = Math.min(1, (cell?.avg_ms || 0) / 650);
              return (
                <button
                  key={bucket}
                  onClick={() => onService(service)}
                  title={`${service} · ${formatTime(bucket, timezone)} · ${cell?.avg_ms || 0} ms average · n=${cell?.samples || 0}`}
                  className="h-5 rounded-[3px] border border-white/[0.04] transition hover:scale-105 hover:border-white/20"
                  style={{
                    backgroundColor: cell
                      ? `color-mix(in srgb, #f43f5e ${Math.round(intensity * 90)}%, #161b22)`
                      : "#0e1116",
                  }}
                  aria-label={`${service}, ${cell?.avg_ms || 0} milliseconds average, ${cell?.samples || 0} samples`}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-end gap-2 text-[10px] text-[#8b949e]">
        <span>Optimal</span>
        <span className="h-1.5 w-24 rounded-full bg-gradient-to-r from-[#161b22] to-[#f43f5e]" />
        <span>Elevated Latency</span>
      </div>
    </div>
  );
}

function formatTime(value: number, timezone: string) {
  return new Intl.DateTimeFormat([], {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone === "local" ? undefined : timezone,
  }).format(new Date(value));
}
