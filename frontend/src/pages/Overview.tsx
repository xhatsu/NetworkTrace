import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, AlertOctagon, Database, Server, Users } from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, MetricCard, Page, Panel, chartTooltip, n } from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import type { SeriesPoint, Summary } from "../types";

type UserSummary = {
  observed_principals: number;
  active_principals: number;
  principals_with_changes: number;
  anonymous_traffic_percentage?: number;
};

type ServiceHealth = {
  name: string;
  anomaly_status?: string;
};

type ChangeEvent = {
  score?: number;
  severity?: string;
  status?: string;
};

const SCORE_COLORS = {
  low: "#22c55e",
  medium: "#f59e0b",
  high: "#f97316",
  critical: "#e11d48",
};

function formatTime(value: number, timezone: string) {
  try {
    const options: Intl.DateTimeFormatOptions = {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    };
    if (timezone !== "local") options.timeZone = timezone;
    return new Intl.DateTimeFormat([], options).format(new Date(Number(value)));
  } catch {
    return new Date(Number(value)).toLocaleString();
  }
}

function formatTooltipTime(value: unknown, timezone: string) {
  if (!value) return "";
  try {
    const options: Intl.DateTimeFormatOptions = {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    };
    if (timezone !== "local") options.timeZone = timezone;
    return new Intl.DateTimeFormat([], options).format(new Date(Number(value)));
  } catch {
    return new Date(Number(value)).toLocaleString();
  }
}

function PlaceholderChart({ message }: { message: string }) {
  return (
    <div className="relative h-[285px] overflow-hidden rounded-lg border border-dashed border-[#383b52] bg-[#0c0d14]">
      <div className="absolute inset-x-8 top-1/2 h-px bg-[#262838]" />
      <div className="absolute inset-y-8 left-1/2 w-px bg-[#262838]" />
      <div className="absolute inset-0 grid place-items-center px-8 text-center">
        <div className="max-w-sm rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-300">
          {message}
        </div>
      </div>
    </div>
  );
}

export function OverviewPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const qs = queryString(filters);

  const summaryQuery = useQuery({
    queryKey: ["dashboard-summary", qs],
    queryFn: () => api<Summary>(`/api/v1/dashboard/summary?${qs}`),
    refetchInterval: 60000,
  });
  const seriesQuery = useQuery({
    queryKey: ["dashboard-series", qs],
    queryFn: () => api<{ items: SeriesPoint[]; bucket_seconds?: number }>(`/api/v1/dashboard/series?${qs}`),
    refetchInterval: 60000,
  });
  const usersQuery = useQuery({
    queryKey: ["dashboard-user-summary", qs],
    queryFn: () => api<UserSummary>(`/api/v1/users/summary?${qs}`),
    refetchInterval: 60000,
  });
  const servicesQuery = useQuery({
    queryKey: ["dashboard-services-health", qs],
    queryFn: () => api<{ items: ServiceHealth[] }>(`/api/v1/services?limit=500&${qs}`),
    refetchInterval: 60000,
  });
  const changesQuery = useQuery({
    queryKey: ["dashboard-abnormal-changes", qs],
    queryFn: () => api<{ items: ChangeEvent[]; count?: number }>(`/api/v1/user-changes?limit=500&${qs}`),
    refetchInterval: 60000,
  });

  const isLoading = summaryQuery.isLoading || seriesQuery.isLoading || usersQuery.isLoading;
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
  const changes = changesQuery.data?.items || [];
  const abnormalServices = serviceItems.filter((service) => service.anomaly_status === "abnormal");
  const latestPoint = points[points.length - 1];

  const totalTps = Number(latestPoint?.tps ?? summary.observed_tps ?? summary.observed_rps ?? 0);
  const currentErrorPercent = Number(latestPoint?.http_5xx_rate ?? summary.http_5xx_rate ?? 0) * 100;
  const totalUsers = Number(users.observed_principals || summary.active_accounts || 0);
  const totalServices = Number(summary.active_services || serviceItems.length || 0);
  const abnormalCount = Number(changesQuery.data?.count ?? changes.length);

  const chartPoints = points.map((point) => ({
    ...point,
    error_percent: Number(point.http_5xx_rate || 0) * 100,
  }));

  const scoreBuckets = { low: 0, medium: 0, high: 0, critical: 0 };
  changes.forEach((change) => {
    const score = Math.max(0, Number(change.score || 0));
    if (score >= 75) scoreBuckets.critical += 1;
    else if (score >= 50) scoreBuckets.high += 1;
    else if (score >= 25) scoreBuckets.medium += 1;
    else scoreBuckets.low += 1;
  });
  const scoreDistribution = [{ name: t("Abnormal changes"), ...scoreBuckets }];
  /*
   * This is intentionally derived from the already-loaded change payload.
   * The dashboard API does not expose a separate score histogram endpoint.
   */
  const scoreDistributionForDisplay = scoreDistribution;

  const scoreLegend = [
    ["low", t("0–24 Low")],
    ["medium", t("25–49 Medium")],
    ["high", t("50–74 High")],
    ["critical", t("75–100 Critical")],
  ] as const;

  return (
    <Page
      eyebrow={t("Observability Dashboard")}
      title={t("Operational Overview")}
      description={t("Current five-minute telemetry over the last seven days.")}
      actions={<button onClick={() => nav("/anomalies")} className="btn-cyan text-xs"><AlertOctagon size={14} />{t("Open anomalies")}</button>}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-cyan-500/25 bg-cyan-500/10 px-3.5 py-2.5 text-xs">
        <div className="flex items-center gap-2 font-semibold text-cyan-300"><Activity size={14} />{t("Live dashboard window")}</div>
        <div className="font-mono text-[#94a3b8]">{t("5-minute buckets · 7-day history")}</div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label={t("Total TPS")} value={n(totalTps, 2)} detail={t("Current five-minute throughput")} accent="cyan" />
        <MetricCard label={t("Total Users")} value={n(totalUsers, 0)} detail={t("Observed identities")} accent="violet" />
        <MetricCard label={t("Total Services")} value={n(totalServices, 0)} detail={`${n(abnormalServices.length, 0)} ${t("in bad health")}`} tone={abnormalServices.length ? "bad" : "good"} accent="amber" />
        <MetricCard label={t("Abnormal Changes")} value={n(abnormalCount, 0)} detail={t("Behavior changes in current window")} tone={abnormalCount ? "bad" : "good"} accent="rose" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title={t("Total TPS")} subtitle={t("Five-minute buckets · last seven days")} action={<span className="font-mono text-xs font-bold text-cyan-300">{n(totalTps, 2)} TPS</span>}>
          <div className="h-[285px] p-3">
            <ResponsiveContainer>
              <LineChart data={chartPoints} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="timestamp_ms" tickFormatter={(value) => formatTime(value, filters.timezone)} minTickGap={44} stroke="#766e92" />
                <YAxis width={42} unit=" tps" stroke="#766e92" />
                <Tooltip {...chartTooltip} formatter={(value: any) => [`${Number(value || 0).toFixed(2)} TPS`, t("Total TPS")]} labelFormatter={(value: any) => formatTooltipTime(value, filters.timezone)} />
                <Line type="monotone" dataKey="tps" stroke="#06b6d4" strokeWidth={2} dot={false} name={t("Total TPS")} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title={t("Bandwidth")} subtitle={t("Five-minute buckets · last seven days")} action={<span className="font-mono text-xs text-amber-300">{t("Unavailable")}</span>}>
          <div className="p-3"><PlaceholderChart message={t("Bandwidth is not present in the existing dashboard API payload. Backend/API work is required; no backend change was made.")} /></div>
        </Panel>

        <Panel title={t("Error %")} subtitle={t("HTTP 5xx error rate in five-minute buckets")} action={<span className="font-mono text-xs font-bold text-rose-300">{currentErrorPercent.toFixed(2)}%</span>}>
          <div className="h-[285px] p-3">
            <ResponsiveContainer>
              <LineChart data={chartPoints} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="timestamp_ms" tickFormatter={(value) => formatTime(value, filters.timezone)} minTickGap={44} stroke="#766e92" />
                <YAxis width={42} unit="%" stroke="#766e92" />
                <Tooltip {...chartTooltip} formatter={(value: any) => [`${Number(value || 0).toFixed(2)}%`, t("Error %")]} labelFormatter={(value: any) => formatTooltipTime(value, filters.timezone)} />
                <Line type="monotone" dataKey="error_percent" stroke="#e11d48" strokeWidth={2} dot={false} name={t("Error %")} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-12">
        <Panel title={t("Abnormal Changes by Score")} subtitle={t("Horizontal stacked distribution of observed abnormal-change scores")} className="lg:col-span-8" action={<span className="font-mono text-xs text-rose-300">{n(abnormalCount, 0)} {t("changes")}</span>}>
          <div className="h-[240px] p-3">
            {changes.length === 0 ? <div className="grid h-full place-items-center text-xs text-[#94a3b8]">{t("No abnormal changes in the current seven-day window.")}</div> : (
              <ResponsiveContainer>
                <BarChart data={scoreDistributionForDisplay} layout="vertical" margin={{ top: 18, right: 18, bottom: 8, left: 12 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} stroke="#766e92" />
                  <YAxis type="category" dataKey="name" width={110} stroke="#766e92" tick={{ fill: "#cbd5e1", fontSize: 11 }} />
                  <Tooltip {...chartTooltip} formatter={(value: any, key: any) => [value, key]} />
                  {scoreLegend.map(([key, label]) => <Bar key={key} dataKey={key} stackId="score" name={label} fill={SCORE_COLORS[key]} radius={key === "critical" ? [0, 4, 4, 0] : undefined} />)}
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2 border-t border-[#262838] px-4 py-3">
            {scoreLegend.map(([key, label]) => <div key={key} className="flex items-center gap-1.5 text-[11px] text-[#94a3b8]"><span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: SCORE_COLORS[key] }} />{label}: <strong className="font-mono text-[#f5f3fa]">{scoreDistributionForDisplay[0][key]}</strong></div>)}
          </div>
        </Panel>

        <Panel title={t("Current Health Context")} subtitle={t("Existing service and identity signals") } className="lg:col-span-4">
          <div className="grid gap-3 p-4">
            <button onClick={() => nav("/services")} className="flex items-center justify-between rounded-lg border border-[#262838] bg-[#0c0d14] p-3 text-left transition hover:border-violet-400">
              <span className="flex items-center gap-2 text-xs font-semibold text-[#cbd5e1]"><Server size={15} className="text-violet-400" />{t("Services in bad health")}</span>
              <span className="font-mono text-lg font-bold text-rose-300">{abnormalServices.length}</span>
            </button>
            <button onClick={() => nav("/users")} className="flex items-center justify-between rounded-lg border border-[#262838] bg-[#0c0d14] p-3 text-left transition hover:border-cyan-400">
              <span className="flex items-center gap-2 text-xs font-semibold text-[#cbd5e1]"><Users size={15} className="text-cyan-400" />{t("Active users")}</span>
              <span className="font-mono text-lg font-bold text-cyan-300">{n(users.active_principals || 0, 0)}</span>
            </button>
            <div className="flex items-center justify-between rounded-lg border border-[#262838] bg-[#0c0d14] p-3">
              <span className="flex items-center gap-2 text-xs font-semibold text-[#cbd5e1]"><Database size={15} className="text-emerald-400" />{t("Telemetry coverage")}</span>
              <span className="font-mono text-sm font-bold text-emerald-300">{summary.sampling_coverage || "—"}</span>
            </div>
          </div>
        </Panel>
      </div>
    </Page>
  );
}
