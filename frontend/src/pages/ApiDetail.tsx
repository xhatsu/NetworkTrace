import { useMemo } from "react";
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
import { Activity, ArrowLeft, ArrowRight, Network, Users } from "lucide-react";
import { EpisodeStatusBadge, type EpisodeResponse } from "../components/EpisodePrimitives";
import { api, queryString } from "../api";
import { ErrorState, Loading, MetricCard, Page, Panel, TpsLineChart, chartTooltip, n, pct } from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";

type Metrics = {
  tps: number;
  request_count: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  error_rate: number;
  http_4xx_rate: number;
  http_5xx_rate: number;
  request_bytes: number;
  response_bytes: number;
  average_request_bytes: number;
  average_response_bytes: number;
  unique_principals: number;
  unique_source_ips: number;
  first_seen_ms?: number | null;
  last_seen_ms?: number | null;
  change?: { status?: string; tps_change_pct?: number; latency_change_pct?: number; error_rate_delta?: number };
};

type SeriesRow = {
  bucket_start?: number;
  timestamp_ms?: number;
  tps?: number;
  request_count?: number;
  p95_latency_ms?: number;
  error_rate?: number;
};

type DetailResponse = {
  entity: { name?: string; type?: string; service?: string; api?: string };
  metrics: Metrics;
  series: SeriesRow[];
  changes?: Record<string, unknown>;
};

type PrincipalNode = {
  id: string;
  name: string;
  principal?: string;
  metrics?: Partial<Metrics> & { change?: { status?: string } };
};

type ExpansionResponse = { nodes?: PrincipalNode[] };

type ConnectionNode = {
  id: string;
  name: string;
  metrics?: Partial<Metrics>;
};

type ConnectionResponse = { nodes?: ConnectionNode[] };

function toNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatTime(value?: number | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function normalizeSeries(rows: SeriesRow[] | undefined) {
  return (rows || [])
    .map((row) => ({
      timestamp_ms: toNumber(row.timestamp_ms, toNumber(row.bucket_start) * 1000),
      tps: toNumber(row.tps),
      p95_ms: toNumber(row.p95_latency_ms),
      error_rate: toNumber(row.error_rate),
    }))
    .filter((row) => row.timestamp_ms > 0)
    .sort((a, b) => a.timestamp_ms - b.timestamp_ms);
}

export function ApiDetailPage() {
  const { name = "", api: rawApi = "" } = useParams();
  const service = name;
  const apiName = rawApi;
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const qs = queryString({ ...filters, service: undefined, operation: undefined }, { window: "7d" });
  const encodedService = encodeURIComponent(service);
  const encodedApi = encodeURIComponent(apiName);

  const detailQuery = useQuery({
    queryKey: ["api-detail", service, apiName, qs],
    queryFn: () => api<DetailResponse>(`/api/v1/topology/apis/${encodedApi}/metrics?service=${encodedService}&${qs}`),
    enabled: Boolean(service && apiName),
  });
  const principalQuery = useQuery({
    queryKey: ["api-principals", service, apiName, qs],
    queryFn: () => api<ExpansionResponse>(`/api/v1/topology/services/${encodedService}/apis/${encodedApi}/principals?${qs}`),
    enabled: Boolean(service && apiName),
  });
  const connectionQuery = useQuery({
    queryKey: ["api-connections", service, apiName, qs],
    queryFn: () => api<ConnectionResponse>(`/api/v1/topology/services/${encodedService}/api-connections?api=${encodedApi}&${qs}`),
    enabled: Boolean(service && apiName),
  });
  const apiChanges = useQuery({
    queryKey: ["api-changes", service, apiName, qs],
    queryFn: () => api<EpisodeResponse>(`/api/v1/changes?service=${encodedService}&q=${encodedApi}&limit=10&${qs}`),
    enabled: Boolean(service && apiName),
  });
  const apiTraces = useQuery({
    queryKey: ["api-traces", service, apiName, qs],
    queryFn: () => api<{ items: any[]; count: number }>(`/api/v1/traces?service=${encodedService}&operation=${encodedApi}&limit=5&${qs}`),
    enabled: Boolean(service && apiName),
  });

  const data = detailQuery.data;
  const metrics = data?.metrics;
  const series = useMemo(() => normalizeSeries(data?.series), [data?.series]);
  const users = principalQuery.data?.nodes || [];
  const callers = connectionQuery.data?.nodes || [];
  const changes = apiChanges.data?.items || [];
  const traces = apiTraces.data?.items || [];

  if (detailQuery.isLoading) {
    return <Page eyebrow={t("API Drilldown")} title={apiName} description={t("Loading...")}><Loading /></Page>;
  }
  if (detailQuery.error || !data || !metrics) {
    return <Page eyebrow={t("API Drilldown")} title={apiName} description=""><ErrorState message={detailQuery.error?.message || t("API telemetry is unavailable in this window")} /></Page>;
  }

  const displayName = data.entity?.name || apiName;
  const changeStatus = metrics.change?.status || "normal";

  return (
    <Page
      eyebrow={t("API Drilldown")}
      title={displayName}
      description={`${t("Service")}: ${service} · ${t("Observed API performance and identity context")}`}
      actions={(
        <button type="button" className="btn" onClick={() => nav(`/services/${encodeURIComponent(service)}?${qs}`)}>
          <ArrowLeft size={13} /> {t("Back to service")}
        </button>
      )}
    >
      {/* 1. Header context */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-[#a7a9ab]">
        <button type="button" onClick={() => nav(`/services/${encodeURIComponent(service)}?${qs}`)} className="inline-flex items-center gap-1.5 rounded-[2px] border border-[#5794f2]/40 bg-[#5794f2]/10 px-2 py-1 font-mono text-[#5794f2] hover:underline">
          <Activity size={12} /> {service}
        </button>
        <span className="text-[#7b7d80]">/</span>
        <span className="font-mono text-[#d8d9da]">{displayName}</span>
        <span className={`rounded-[2px] border px-2 py-0.5 text-[10px] font-semibold uppercase ${changeStatus === "changed" || changeStatus === "new" ? "border-[#ff9830]/40 bg-[#ff9830]/10 text-[#ff9830]" : "border-[#73bf69]/40 bg-[#73bf69]/10 text-[#73bf69]"}`}>
          {changeStatus}
        </span>
      </div>

      {/* 2. TPS vs Baseline */}
      <Panel
        title={t("TPS")}
        subtitle={t("Observed API throughput over the selected window")}
        className="mt-3"
        action={<span className="font-mono text-[11px] text-[#5794f2]">{n(series[series.length - 1]?.tps || 0, 2)} TPS</span>}
      >
        <TpsLineChart data={series.map(({ timestamp_ms, tps }) => ({ timestamp_ms, tps }))} />
      </Panel>

      {/* 3. Compact health metrics */}
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard label={t("TPS")} value={n(metrics.tps, 2)} detail={t("Observed API throughput")} accent="sky" />
        <MetricCard label={t("Requests")} value={n(metrics.request_count, 0)} detail={t("Selected seven-day window")} accent="cyan" />
        <MetricCard label={t("P95 Latency")} value={`${n(metrics.p95_latency_ms, 1)} ms`} detail={`p50 ${n(metrics.p50_latency_ms, 1)} ms · p99 ${n(metrics.p99_latency_ms, 1)} ms`} accent="violet" tone={metrics.p95_latency_ms > 500 ? "bad" : "normal"} />
        <MetricCard label={t("Error %")} value={pct(metrics.error_rate)} detail={`${n(metrics.unique_principals, 0)} ${t("users")}`} accent="rose" tone={metrics.error_rate >= 0.02 ? "bad" : "normal"} />
      </div>

      {/* 4. Errors and latency */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title={t("P95 latency over time")} subtitle={t("Tail latency in milliseconds")}>
          <ApiLineChart data={series} dataKey="p95_ms" color="#b877d9" unit="ms" label={t("P95 Latency")} />
        </Panel>
        <Panel title={t("API reliability and volume")} subtitle={t("Supporting metrics from the same observed window")}>
          <div className="grid grid-cols-2 gap-3 p-3 text-xs sm:grid-cols-4">
            <InfoMetric label="4xx" value={pct(metrics.http_4xx_rate)} tone="text-[#ff9830]" />
            <InfoMetric label="5xx" value={pct(metrics.http_5xx_rate)} tone="text-[#f2495c]" />
            <InfoMetric label={t("Request bytes")} value={n(metrics.request_bytes, 0)} tone="text-[#5794f2]" />
            <InfoMetric label={t("Response bytes")} value={n(metrics.response_bytes, 0)} tone="text-[#b877d9]" />
          </div>
          <div className="grid grid-cols-2 gap-4 border-t border-[#2a2d30] px-3 py-2.5 text-[11px] text-[#a7a9ab]">
            <div><span className="block text-[#7b7d80]">{t("First seen")}</span>{formatTime(metrics.first_seen_ms)}</div>
            <div><span className="block text-[#7b7d80]">{t("Last seen")}</span>{formatTime(metrics.last_seen_ms)}</div>
          </div>
        </Panel>
      </div>

      {/* 5. Users */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title={t("Users using this API")} subtitle={t("Service → API → User investigation path")}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-xs">
              <thead><tr className="border-b border-[#2a2d30]">{[t("User"), t("Requests"), t("TPS"), t("Error %"), t("P95"), t("Change")].map((heading) => <th className="table-head px-3 py-2" key={heading}>{heading}</th>)}</tr></thead>
              <tbody className="divide-y divide-[#2a2d30]">
                {users.map((user) => {
                  const userMetrics = user.metrics || {};
                  return (
                    <tr key={user.id || user.name} onClick={() => nav(`/users/${encodeURIComponent(user.name)}/activity?${qs}`)} className="cursor-pointer hover:bg-[#181b1f] transition">
                      <td className="px-3 py-2 font-mono text-[#5794f2]"><Users size={12} className="mr-1 inline" />{user.name}</td>
                      <td className="px-3 font-mono tabular-nums text-[#d8d9da]">{n(userMetrics.request_count || 0, 0)}</td>
                      <td className="px-3 font-mono tabular-nums text-[#5794f2]">{n(userMetrics.tps || 0, 2)}</td>
                      <td className="px-3 font-mono tabular-nums text-[#f2495c]">{pct(userMetrics.error_rate || 0)}</td>
                      <td className="px-3 font-mono tabular-nums text-[#b877d9]">{n(userMetrics.p95_latency_ms || 0, 1)} ms</td>
                      <td className="px-3"><span className="text-[10px] uppercase text-[#a7a9ab]">{userMetrics.change?.status || "normal"}</span></td>
                    </tr>
                  );
                })}
                {!users.length && <tr><td colSpan={6} className="px-3 py-8 text-center text-[#7b7d80]">{t("No users observed for this API")}</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* 6. Dependencies */}
        <Panel title={t("Caller services")} subtitle={t("Observed source relationships for this API")}>
          <div className="divide-y divide-[#2a2d30]">
            {callers.map((caller) => (
              <div key={caller.id || caller.name} className="flex items-center justify-between px-3 py-2.5 text-xs hover:bg-[#181b1f]">
                <button type="button" onClick={() => nav(`/services/${encodeURIComponent(caller.name)}?${qs}`)} className="font-semibold text-[#d8d9da] hover:text-[#5794f2]">{caller.name}</button>
                <span className="font-mono text-[#5794f2] tabular-nums">{n(caller.metrics?.tps || 0, 2)} TPS <span className="text-[#7b7d80]">· {pct(caller.metrics?.error_rate || 0)}</span></span>
              </div>
            ))}
            {!callers.length && <div className="p-8 text-center text-xs text-[#7b7d80]">{t("No caller relationships observed for this API")}</div>}
          </div>
        </Panel>
      </div>

      {/* 7. Changes */}
      <Panel
        title={t("Recent Changes")}
        subtitle={t("Evaluated behavior changes for this API")}
        className="mt-4"
        action={<button onClick={() => nav(`/changes?service=${encodeURIComponent(service)}&q=${encodeURIComponent(apiName)}`)} className="text-[11px] font-semibold text-[#5794f2] hover:text-white">{t("View all")} <ArrowRight size={12} className="inline" /></button>}
      >
        {apiChanges.isLoading ? (
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
          <div className="p-6 text-center text-xs text-[#7b7d80]">{t("No behavior changes for this API in the current window.")}</div>
        )}
      </Panel>

      {/* 8. Representative Traces */}
      <Panel
        title={t("Representative Traces")}
        subtitle={t("Recent distributed traces executing this API")}
        className="mt-4"
        action={<button onClick={() => nav(`/traces?service=${encodeURIComponent(service)}&operation=${encodeURIComponent(apiName)}`)} className="text-[11px] font-semibold text-[#5794f2] hover:text-white">{t("Open in Traces")} <ArrowRight size={12} className="inline" /></button>}
      >
        {apiTraces.isLoading ? (
          <Loading />
        ) : traces.length ? (
          <div className="overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#2a2d30]">
                  <th className="table-head px-3 py-2">{t("Trace ID")}</th>
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
          <div className="p-6 text-center text-xs text-[#7b7d80]">{t("No recent traces recorded for this API.")}</div>
        )}
      </Panel>
    </Page>
  );
}

function InfoMetric({ label, value, tone }: { label: string; value: string; tone: string }) {
  return <div className="rounded border border-[rgba(255,255,255,0.1)] bg-white/[0.02] p-3"><div className="text-[10px] uppercase tracking-wide text-[#8b949e]">{label}</div><div className={`mt-1 font-mono text-sm ${tone}`}>{value}</div></div>;
}

function ApiLineChart({ data, dataKey, color, unit, label }: { data: Array<{ timestamp_ms: number; tps: number; p95_ms: number }>; dataKey: "tps" | "p95_ms"; color: string; unit: string; label: string }) {
  const { t } = useI18n();
  if (!data.length) return <div className="grid h-64 place-items-center p-4 text-xs text-[#8b949e]">{t("No telemetry points in the selected window")}</div>;
  return <div className="h-64 p-3"><ResponsiveContainer><LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}><CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} /><XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={36} tickFormatter={(value) => new Date(Number(value)).toLocaleDateString([], { month: "short", day: "numeric" })} stroke="#484f58" /><YAxis stroke="#484f58" /><Tooltip {...chartTooltip} labelFormatter={(value) => new Date(Number(value)).toLocaleString()} formatter={(value: unknown) => [`${n(Number(value), 2)} ${unit}`, label]} /><Line type="monotone" dataKey={dataKey} name={label} stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4, fill: color }} connectNulls /></LineChart></ResponsiveContainer></div>;
}
