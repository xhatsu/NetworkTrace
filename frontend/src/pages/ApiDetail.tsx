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
import { Activity, ArrowLeft, Network, Users } from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, MetricCard, Page, Panel, chartTooltip, n, pct } from "../components";
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

  const data = detailQuery.data;
  const metrics = data?.metrics;
  const series = useMemo(() => normalizeSeries(data?.series), [data?.series]);
  const users = principalQuery.data?.nodes || [];
  const callers = connectionQuery.data?.nodes || [];

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
      <div className="flex flex-wrap items-center gap-2 text-xs text-[#c4bdd9]">
        <span className="inline-flex items-center gap-1.5 rounded border border-violet-500/40 bg-violet-500/10 px-2 py-1 font-mono text-violet-300"><Activity size={12} /> {service}</span>
        <span className="text-[#64748b]">→</span>
        <span className="font-mono text-cyan-300">{displayName}</span>
        <span className={`rounded border px-2 py-1 font-semibold uppercase ${changeStatus === "changed" || changeStatus === "new" ? "border-amber-500/40 bg-amber-500/10 text-amber-300" : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"}`}>{changeStatus}</span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard label={t("TPS")} value={n(metrics.tps, 2)} detail={t("Observed API throughput")} accent="sky" />
        <MetricCard label={t("Requests")} value={n(metrics.request_count, 0)} detail={t("Selected seven-day window")} accent="cyan" />
        <MetricCard label={t("P95 Latency")} value={`${n(metrics.p95_latency_ms, 1)} ms`} detail={`p50 ${n(metrics.p50_latency_ms, 1)} ms · p99 ${n(metrics.p99_latency_ms, 1)} ms`} accent="violet" tone={metrics.p95_latency_ms > 500 ? "bad" : "normal"} />
        <MetricCard label={t("Error %")} value={pct(metrics.error_rate)} detail={`${n(metrics.unique_principals, 0)} ${t("users")}`} accent="rose" tone={metrics.error_rate >= 0.02 ? "bad" : "normal"} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title={t("TPS over time")} subtitle={t("Five-minute API buckets over the selected history")}>
          <ApiLineChart data={series} dataKey="tps" color="#38bdf8" unit="TPS" label={t("TPS")} />
        </Panel>
        <Panel title={t("P95 latency over time")} subtitle={t("Tail latency in milliseconds") }>
          <ApiLineChart data={series} dataKey="p95_ms" color="#a78bfa" unit="ms" label={t("P95 Latency")} />
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title={t("API reliability and volume")} subtitle={t("Supporting metrics from the same observed window")}>
          <div className="grid grid-cols-2 gap-3 p-4 text-xs sm:grid-cols-4">
            <InfoMetric label="4xx" value={pct(metrics.http_4xx_rate)} tone="text-amber-300" />
            <InfoMetric label="5xx" value={pct(metrics.http_5xx_rate)} tone="text-rose-300" />
            <InfoMetric label={t("Request bytes")} value={n(metrics.request_bytes, 0)} tone="text-cyan-300" />
            <InfoMetric label={t("Response bytes")} value={n(metrics.response_bytes, 0)} tone="text-indigo-300" />
          </div>
          <div className="grid grid-cols-2 gap-4 border-t border-[rgba(255,255,255,0.08)] px-4 py-3 text-[11px] text-[#c4bdd9]">
            <div><span className="block text-[#8b949e]">{t("First seen")}</span>{formatTime(metrics.first_seen_ms)}</div>
            <div><span className="block text-[#8b949e]">{t("Last seen")}</span>{formatTime(metrics.last_seen_ms)}</div>
          </div>
        </Panel>
        <Panel title={t("Service context")} subtitle={t("API remains subordinate to its owning service")}>
          <div className="space-y-3 p-4 text-xs">
            <button type="button" className="flex w-full items-center gap-3 rounded border border-[rgba(255,255,255,0.1)] bg-white/[0.02] p-3 text-left hover:bg-white/[0.05]" onClick={() => nav(`/services/${encodeURIComponent(service)}?${qs}`)}>
              <Network size={16} className="text-violet-300" />
              <span><span className="block font-semibold text-[#f5f3fa]">{service}</span><span className="text-[#8b949e]">{t("Open service investigation")}</span></span>
            </button>
            <div className="text-[#c4bdd9]">{t("This API is observed with")} <strong className="text-cyan-300">{n(metrics.unique_principals, 0)}</strong> {t("users")} and <strong className="text-sky-300">{n(metrics.unique_source_ips, 0)}</strong> {t("source IPs")}.</div>
          </div>
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title={t("Users using this API")} subtitle={t("Service → API → User investigation path")}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-xs">
              <thead><tr>{[t("User"), t("Requests"), t("TPS"), t("Error %"), t("P95"), t("Change")].map((heading) => <th className="table-head px-3 py-2.5" key={heading}>{heading}</th>)}</tr></thead>
              <tbody>
                {users.map((user) => {
                  const userMetrics = user.metrics || {};
                  return <tr key={user.id || user.name} onClick={() => nav(`/users/${encodeURIComponent(user.name)}/overview?${qs}`)} className="cursor-pointer border-t border-[rgba(255,255,255,0.07)] hover:bg-white/[0.04]">
                    <td className="px-3 py-2.5 font-mono text-cyan-300"><Users size={12} className="mr-1 inline" />{user.name}</td>
                    <td className="px-3 font-mono">{n(userMetrics.request_count || 0, 0)}</td>
                    <td className="px-3 font-mono text-sky-300">{n(userMetrics.tps || 0, 2)}</td>
                    <td className="px-3 font-mono text-rose-300">{pct(userMetrics.error_rate || 0)}</td>
                    <td className="px-3 font-mono text-violet-300">{n(userMetrics.p95_latency_ms || 0, 1)} ms</td>
                    <td className="px-3"><span className="text-[10px] uppercase text-[#c4bdd9]">{userMetrics.change?.status || "normal"}</span></td>
                  </tr>;
                })}
                {!users.length && <tr><td colSpan={6} className="px-3 py-8 text-center text-[#8b949e]">{t("No users observed for this API")}</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title={t("Caller services")} subtitle={t("Observed source relationships for this API")}>
          <div className="divide-y divide-[rgba(255,255,255,0.07)]">
            {callers.map((caller) => <div key={caller.id || caller.name} className="flex items-center justify-between px-4 py-3 text-xs"><span className="font-medium text-[#f5f3fa]">{caller.name}</span><span className="font-mono text-sky-300">{n(caller.metrics?.tps || 0, 2)} TPS <span className="text-[#8b949e]">· {pct(caller.metrics?.error_rate || 0)}</span></span></div>)}
            {!callers.length && <div className="p-8 text-center text-[#8b949e]">{t("No caller relationships observed for this API")}</div>}
          </div>
        </Panel>
      </div>
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
