import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Activity, ArrowLeft, ArrowRight, Users } from "lucide-react";
import { type EpisodeResponse } from "../components/EpisodePrimitives";
import { AccessExplorer, type ExplorerFilters } from "../components/AccessExplorer";
import { EntityLink } from "../components/EntityLink";
import { entityPath } from "../entityRoutes";
import { api, queryString } from "../api";
import { ErrorState, Loading, Page, Panel, n, pct } from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import {
  RecentChangesPanel,
  ServicePerformancePanel,
  mergeServiceBandwidth,
  normalizeServiceBandwidth,
  normalizeServiceSeries,
} from "./Services";

// ---------------------------------------------------------------------------
// API catalog (/apis): every observed API across all Services.
// ---------------------------------------------------------------------------

type ApiRow = {
  service: string;
  name: string;
  total_requests: number;
  total_errors: number;
  error_rate: number;
  p95_latency: number;
  caller_count: number;
  principal_count: number;
  first_seen_ms: number;
  last_seen_ms: number;
  rps: number;
  anomaly_status: string;
};

const CATALOG_LIMIT = 2000;
const PAGE_SIZE = 15;

export function ApisPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const qs = queryString({ ...filters, service: undefined, operation: undefined, account: undefined });
  const query = useQuery({
    queryKey: ["apis", qs],
    queryFn: () => api<{ items: ApiRow[] }>(`/api/v1/apis?${qs}&limit=${CATALOG_LIMIT}`),
  });
  const items = (query.data?.items || []).filter(row => !filters.service || row.service === filters.service);
  const services = new Set(items.map(row => row.service)).size;
  const withErrors = items.filter(row => row.error_rate > 0).length;
  const anomalies = items.filter(row => row.anomaly_status === "abnormal").length;

  return (
    <Page
      eyebrow={t("API inventory", "Danh mục API")}
      title="APIs"
      description={t("Find an API across every Service, review its signals, and open its callers, users and traces.", "Tìm API trên mọi Service, kiểm tra tín hiệu và mở caller, user và Trace của nó.")}
    >
      {query.isLoading ? <Loading /> : query.isError ? <><ErrorState message={query.error.message} /><button className="btn" onClick={() => query.refetch()}>{t("Retry")}</button></> : <>
        <dl className="mb-4 grid grid-cols-2 overflow-hidden rounded border border-line bg-surface lg:grid-cols-4">
          {[
            [t("Observed APIs", "API đã quan sát"), n(items.length), t(`Selected window · up to ${CATALOG_LIMIT}`, `Khoảng đã chọn · tối đa ${CATALOG_LIMIT}`)],
            [t("Services", "Service"), n(services), t("Owning these APIs", "Sở hữu các API này")],
            [t("Open anomalies", "Bất thường đang mở"), n(anomalies), t("APIs with an open anomaly", "API có bất thường đang mở")],
            [t("With errors", "Có lỗi"), n(withErrors), t("Error rate above zero", "Tỷ lệ lỗi lớn hơn 0")],
          ].map(([label, value, note]) => <div key={label} className="min-w-0 border-l border-line px-4 py-3 first:border-l-0 max-lg:[&:nth-child(3)]:border-l-0 max-lg:[&:nth-child(n+3)]:border-t">
            <dt className="text-xs text-muted">{label}</dt>
            <dd className="mt-1 font-mono text-xl tabular-nums text-ink">{value}</dd>
            <dd className="mt-1 text-[11px] text-muted">{note}</dd>
          </div>)}
        </dl>
        {(filters.account || filters.operation) && <p className="mb-3 rounded border border-line px-3 py-2 text-xs text-muted">{t("The catalog aggregates all callers and users of each API. Account and operation filters do not narrow this inventory.", "Danh mục tổng hợp mọi caller và user của từng API. Bộ lọc account và operation không thu hẹp danh mục này.")}</p>}
        <ApiDirectory key={qs} rows={items} search={`?${qs}`} />
        <p className="mt-3 text-[11px] text-muted">{t("Observed telemetry is not an availability or SLO measurement. No open anomaly does not establish API health.", "Telemetry quan sát không đo độ sẵn sàng hay SLO. Không có bất thường đang mở chưa đủ để kết luận API hoạt động tốt.")} {query.data?.items.length === CATALOG_LIMIT && t(`Only the first ${CATALOG_LIMIT} APIs by requests are loaded.`, `Chỉ tải ${CATALOG_LIMIT} API nhiều request nhất.`)}</p>
      </>}
    </Page>
  );
}

function ApiDirectory({ rows, search }: { rows: ApiRow[]; search: string }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [service, setService] = useState("");
  const [sort, setSort] = useState("priority");
  const [page, setPage] = useState(0);
  const services = [...new Set(rows.map(row => row.service))].sort();
  const needle = query.trim().toLowerCase();
  const visibleRows = rows
    .filter(row => !needle || row.name.toLowerCase().includes(needle) || row.service.toLowerCase().includes(needle))
    .filter(row => !service || row.service === service)
    .filter(row => scope === "anomalies" ? row.anomaly_status === "abnormal" : scope === "errors" ? row.error_rate > 0 : true)
    .sort((a, b) => {
      const byName = a.name.localeCompare(b.name) || a.service.localeCompare(b.service);
      if (sort === "name") return byName;
      if (sort === "traffic") return b.total_requests - a.total_requests || byName;
      if (sort === "latency") return b.p95_latency - a.p95_latency || byName;
      if (sort === "users") return b.principal_count - a.principal_count || byName;
      return (sort === "priority" ? Number(b.anomaly_status === "abnormal") - Number(a.anomaly_status === "abnormal") : 0)
        || b.error_rate - a.error_rate || b.total_requests - a.total_requests || byName;
    });
  const lastPage = Math.max(0, Math.ceil(visibleRows.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(page, lastPage);
  const visible = visibleRows.slice(currentPage * PAGE_SIZE, currentPage * PAGE_SIZE + PAGE_SIZE);
  const reset = () => { setQuery(""); setService(""); setScope("all"); setPage(0); };

  return (
    <Panel title={t("API directory", "Danh sách API")} subtitle={t("Open signals first. Select an API to investigate its callers, users and traces.", "Ưu tiên tín hiệu đang mở. Chọn API để kiểm tra caller, user và Trace.")}>
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <div className="flex flex-wrap gap-1" role="group" aria-label={t("API scope", "Phạm vi API")}>
          {[
            ["all", t("All APIs", "Tất cả API"), rows.length],
            ["anomalies", t("Open anomalies", "Bất thường đang mở"), rows.filter(row => row.anomaly_status === "abnormal").length],
            ["errors", t("With errors", "Có lỗi"), rows.filter(row => row.error_rate > 0).length],
          ].map(([value, label, count]) => <button key={value} type="button" aria-pressed={scope === value} onClick={() => { setScope(String(value)); setPage(0); }} className={`rounded border px-2.5 py-1.5 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${scope === value ? "border-accent bg-accent-soft text-ink font-semibold" : "border-line-strong text-muted hover:text-ink"}`}>{label} <span className="ml-1 font-mono">{count}</span></button>)}
        </div>
        <input aria-label={t("Search APIs", "Tìm API")} placeholder={t("Search API path or Service…", "Tìm đường dẫn API hoặc Service…")} value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} className="min-w-0 basis-full rounded border border-line-strong bg-surface-2 px-3 py-2 text-xs text-ink sm:basis-48 sm:flex-1" />
        <select aria-label={t("Owning Service", "Service sở hữu")} value={service} onChange={event => { setService(event.target.value); setPage(0); }} className="max-w-full rounded border border-line-strong bg-surface-2 px-2 py-2 text-xs text-ink">
          <option value="">{t("All services", "Tất cả Service")}</option>
          {services.map(value => <option key={value} value={value}>{value}</option>)}
        </select>
        <select aria-label={t("Sort APIs", "Sắp xếp API")} value={sort} onChange={event => { setSort(event.target.value); setPage(0); }} className="max-w-full rounded border border-line-strong bg-surface-2 px-2 py-2 text-xs text-ink">
          <option value="priority">{t("Priority: signals → errors → requests", "Ưu tiên: tín hiệu → lỗi → request")}</option>
          <option value="errors">{t("Error rate: highest first", "Tỷ lệ lỗi: cao nhất trước")}</option>
          <option value="traffic">{t("Requests: highest first", "Request: nhiều nhất trước")}</option>
          <option value="latency">{t("Max bucket P95: highest first", "P95 bucket lớn nhất: cao nhất trước")}</option>
          <option value="users">{t("Users: most first", "User: nhiều nhất trước")}</option>
          <option value="name">{t("API: A–Z", "API: A–Z")}</option>
        </select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-xs">
          <caption className="sr-only">{t("Observed API metrics; no anomaly does not imply healthy or available.", "Chỉ số API đã quan sát; không có bất thường không đồng nghĩa hoạt động tốt hay sẵn sàng.")}</caption>
          <thead><tr className="border-b border-line">
            {["API", t("Signal", "Tín hiệu"), t("Requests"), t("Avg TPS", "TPS TB"), t("Error rate"), t("Max bucket P95", "P95 bucket lớn nhất"), t("Callers", "Caller"), t("Users"), t("Last seen")].map((label, index) => <th scope="col" key={label} className={`table-head px-3 py-2 ${index > 1 ? "text-right" : ""}`}>{label}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-line">{visible.map(row => <tr key={`${row.service}|${row.name}`} className="hover:bg-hover">
            <td className="max-w-[340px] px-3 py-2.5">
              <EntityLink entity={{ kind: "api", service: row.service, operation: row.name }} search={search} className="block truncate font-mono font-semibold text-ink hover:text-entity-api" title={row.name}>{row.name}</EntityLink>
              <EntityLink entity={{ kind: "service", name: row.service }} search={search} className="text-[10px] text-muted hover:text-ink hover:underline">{row.service}</EntityLink>
            </td>
            <td className="px-3 py-2"><span className={row.anomaly_status === "abnormal" ? "text-warn" : "text-muted"}>{row.anomaly_status === "abnormal" ? t("Open anomaly", "Bất thường đang mở") : t("No open anomaly", "Không có bất thường mở")}</span></td>
            <td className="px-3 py-2 text-right font-mono tabular-nums">{n(row.total_requests, 0)}</td>
            <td className="px-3 py-2 text-right font-mono tabular-nums text-ink">{n(row.rps, 3)}</td>
            <td className={`px-3 py-2 text-right font-mono tabular-nums ${row.error_rate > 0 ? "text-warn" : "text-muted"}`}>{pct(row.error_rate || 0)}</td>
            <td className="px-3 py-2 text-right font-mono tabular-nums">{n(row.p95_latency || 0, 0)} ms</td>
            <td className="px-3 py-2 text-right font-mono tabular-nums">{n(row.caller_count, 0)}</td>
            <td className="px-3 py-2 text-right font-mono tabular-nums">{n(row.principal_count, 0)}</td>
            <td className="px-3 py-2 text-right text-muted">{row.last_seen_ms ? new Date(row.last_seen_ms).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
          </tr>)}</tbody>
        </table>
        {!visibleRows.length && <div className="p-8 text-center text-xs text-muted">{t("No APIs match these filters.", "Không có API phù hợp bộ lọc.")}{(query || service || scope !== "all") && <button className="btn mx-auto mt-3 block" onClick={reset}>{t("Clear filters", "Xóa bộ lọc")}</button>}</div>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-[11px] text-muted">
        <span aria-live="polite">{visibleRows.length ? currentPage * PAGE_SIZE + 1 : 0}–{Math.min((currentPage + 1) * PAGE_SIZE, visibleRows.length)} / {visibleRows.length} {t("matching APIs", "API phù hợp")}</span>
        <div className="flex items-center gap-2"><button className="btn disabled:opacity-40" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{t("Previous", "Trước")}</button><span>{currentPage + 1} / {lastPage + 1}</span><button className="btn disabled:opacity-40" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>{t("Next", "Tiếp")}</button></div>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// API detail (/services/:name/apis/:api): same layout as Service detail.
// ---------------------------------------------------------------------------

type DashboardPoint = Record<string, unknown> & { sample_count?: number };

type TopologyMetrics = {
  entity?: { name?: string };
  metrics?: Record<string, number>;
  series?: unknown[];
};

// One (principal, source IP, API, caller) row from the worker's five-minute IP rollup.
type Relationship = {
  principal?: string;
  source_ip?: string;
  api: string;
  caller_service?: string;
  request_count?: number;
  error_count?: number;
  p95_latency_ms?: number;
  last_seen_ms?: number;
};

type Party = { name: string; requests: number; errorRate: number; p95: number; ips: number; partners: number; lastSeen: number };

const RELATIONSHIP_PAGES = 20;
// Anonymous traffic stays in API volume but is never listed as a user (see the Unknown Users page).
const ANONYMOUS = new Set(["-anonymous-", "anonymous", "unknown"]);

/** Users or callers of the API, from the rows that name it (the rollup spells APIs "service/operation"). */
function parties(rows: Relationship[], key: "principal" | "caller_service", partner: "principal" | "caller_service"): Party[] {
  const groups = new Map<string, { requests: number; errors: number; p95: number; ips: Set<string>; partners: Set<string>; lastSeen: number }>();
  rows.forEach(row => {
    const name = row[key];
    if (!name || (key === "principal" && ANONYMOUS.has(name))) return;
    const g = groups.get(name) || { requests: 0, errors: 0, p95: 0, ips: new Set<string>(), partners: new Set<string>(), lastSeen: 0 };
    g.requests += row.request_count || 0;
    g.errors += row.error_count || 0;
    g.p95 = Math.max(g.p95, row.p95_latency_ms || 0);
    if (row.source_ip) g.ips.add(row.source_ip);
    if (row[partner]) g.partners.add(row[partner]!);
    g.lastSeen = Math.max(g.lastSeen, row.last_seen_ms || 0);
    groups.set(name, g);
  });
  return [...groups].map(([name, g]) => ({
    name, requests: g.requests, errorRate: g.requests ? g.errors / g.requests : 0, p95: g.p95, ips: g.ips.size, partners: g.partners.size, lastSeen: g.lastSeen,
  })).sort((a, b) => b.requests - a.requests || a.name.localeCompare(b.name));
}

export function ApiDetailPage() {
  const { name: service = "", api: apiName = "" } = useParams();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [detailTab, setDetailTab] = useState("users");
  const [accessFilters, setAccessFilters] = useState<ExplorerFilters>({});
  const qs = queryString({ ...filters, service: undefined, operation: undefined });
  const encodedService = encodeURIComponent(service);
  const encodedApi = encodeURIComponent(apiName);
  const enabled = Boolean(service && apiName);

  // Same 60-second worker buckets and expected TPS as the Service page.
  const seriesQuery = useQuery({
    queryKey: ["api-series", service, apiName, qs],
    queryFn: async () => {
      const body = await api<DashboardPoint[] | { items?: DashboardPoint[] }>(`/api/v1/dashboard/series?${qs}&service=${encodedService}&operation=${encodedApi}`);
      return Array.isArray(body) ? body : body.items || [];
    },
    enabled,
  });
  // Bandwidth (and the measured byte samples) comes from the five-minute topology rollup.
  const metricsQuery = useQuery({
    queryKey: ["api-detail", service, apiName, qs],
    queryFn: () => api<TopologyMetrics>(`/api/v1/topology/apis/${encodedApi}/metrics?service=${encodedService}&${qs}`),
    enabled,
  });
  // Same source as the Service access board; paged until exhausted (bounded) and narrowed to this API.
  const relationshipQuery = useQuery({
    queryKey: ["api-relationships", service, apiName, qs],
    queryFn: async () => {
      const rows: Relationship[] = [];
      let cursor = "";
      for (let page = 0; page < RELATIONSHIP_PAGES; page += 1) {
        const body = await api<{ items: Relationship[]; next_cursor?: string | null }>(
          `/api/v1/topology/services/${encodedService}/ips?${qs}&page_size=500${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        rows.push(...body.items.filter(row => row.api === apiName || row.api === `${service}/${apiName}`));
        if (!body.next_cursor) return { rows, truncated: false };
        cursor = body.next_cursor;
      }
      return { rows, truncated: true };
    },
    enabled,
  });
  const changesQuery = useQuery({
    queryKey: ["api-changes", service, apiName, qs],
    queryFn: () => api<EpisodeResponse>(`/api/v1/changes?service=${encodedService}&q=${encodedApi}&limit=10&${qs}`),
    enabled,
  });
  const tracesQuery = useQuery({
    queryKey: ["api-traces", service, apiName, qs],
    queryFn: () => api<{ items: any[]; count: number }>(`/api/v1/traces?service=${encodedService}&operation=${encodedApi}&limit=10&${qs}`),
    enabled,
  });

  const series = useMemo(() => normalizeServiceSeries((seriesQuery.data || []).map(point => ({ ...point, requests: point.sample_count ?? 0 }))), [seriesQuery.data]);
  const bandwidthSeries = useMemo(() => normalizeServiceBandwidth(metricsQuery.data?.series), [metricsQuery.data?.series]);
  const chartSeries = useMemo(() => mergeServiceBandwidth(series, bandwidthSeries), [series, bandwidthSeries]);
  const totals = useMemo(() => {
    const requests = series.reduce((sum, point) => sum + point.requests, 0);
    const errors = series.reduce((sum, point) => sum + point.requests * (point.failure_rate || 0), 0);
    return { requests, errors, failureRate: requests ? errors / requests : 0, worstP95: Math.max(0, ...series.map(point => point.p95_ms || 0)) };
  }, [series]);

  if (seriesQuery.isLoading) {
    return <Page eyebrow={t("API Drilldown")} title={apiName} description={t("Loading...")}><Loading /></Page>;
  }
  if (seriesQuery.error) {
    return <Page eyebrow={t("API Drilldown")} title={apiName} description=""><ErrorState message={seriesQuery.error.message} /></Page>;
  }

  const durationSec = Math.max(1, (new Date(filters.end).getTime() - new Date(filters.start).getTime()) / 1000);
  const relationshipRows = relationshipQuery.data?.rows || [];
  const users = parties(relationshipRows, "principal", "caller_service");
  const callers = parties(relationshipRows, "caller_service", "principal");
  const traces = tracesQuery.data?.items || [];
  const search = `?${qs}`;

  return (
    <Page
      eyebrow={t("API Drilldown")}
      title={apiName}
      description={`${t("Service")}: ${service} · ${t("Observed API performance, access and traces", "Hiệu năng, truy cập và Trace của API")}`}
      actions={<div className="flex flex-wrap gap-2">
        <button className="btn" onClick={() => nav(`/apis?${qs}`)}><ArrowLeft size={13} /> {t("All APIs", "Tất cả API")}</button>
        <EntityLink entity={{ kind: "service", name: service }} search={search} className="btn">{t("Back to service")}</EntityLink>
        <button className="btn" onClick={() => nav(`/traces?${qs}&service=${encodedService}&operation=${encodedApi}`)}>{t("Open in Traces")} <ArrowRight size={13} /></button>
      </div>}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <EntityLink entity={{ kind: "service", name: service }} search={search} className="inline-flex items-center gap-1.5 rounded-[2px] border border-line-strong bg-surface px-2 py-1 font-mono text-ink hover:underline">
          <Activity size={12} /> {service}
        </EntityLink>
        <span className="text-muted">/</span>
        <span className="font-mono text-entity-api">{apiName}</span>
        <span className="ml-2 font-mono text-[11px]">{n(callers.length, 0)} {t("callers", "caller")} · {n(users.length, 0)} {t("users")}</span>
      </div>

      <ServicePerformancePanel
        key={`${service}|${apiName}`}
        series={series}
        bandwidthSeries={bandwidthSeries}
        chartSeries={chartSeries}
        totalRequests={totals.requests}
        totalErrors={totals.errors}
        operationsCount={1}
        durationSec={durationSec}
        failureRate={totals.failureRate}
        worstP95={totals.worstP95}
        bandwidthMetrics={metricsQuery.data?.metrics || {}}
        latencyDetail={t("Highest one-minute P95 in the window", "P95 một phút cao nhất trong khoảng")}
        aside={<RecentChangesPanel
          query={changesQuery}
          viewAllHref={`/changes?${qs}&service=${encodedService}&q=${encodedApi}`}
          search={search}
          emptyText={t("No behavior changes for this API in the current window.")}
        />}
      />

      <Panel
        className="mt-4"
        title={`${t("Access for", "Quyền truy cập của")} ${apiName}`}
        subtitle={t(
          "Unusual access first, then the Caller Services and Users of this API; select a row to see its direct relationships",
          "Truy cập bất thường trước, sau đó là Caller Service và User của API này; chọn một dòng để xem quan hệ trực tiếp",
        )}
      >
        <AccessExplorer service={service} lockedApi={`${service} → ${apiName}`} filters={accessFilters} onFilters={setAccessFilters} />
      </Panel>

      <div className="mt-5 flex flex-wrap gap-2 border-b border-line pb-3" role="group" aria-label={t("API detail views", "Góc nhìn API")}>
        {[["users", t("Users"), users.length], ["callers", t("Caller services"), callers.length], ["traces", t("Traces"), traces.length]].map(([value, label, count]) => (
          <button key={value} aria-pressed={detailTab === value} className={`rounded border px-3 py-2 text-xs ${detailTab === value ? "border-accent bg-accent-soft text-ink font-semibold" : "border-line-strong text-muted hover:text-ink"}`} onClick={() => setDetailTab(String(value))}>
            {label} <span className="ml-2 font-mono">{count}</span>
          </button>
        ))}
      </div>

      {detailTab === "users" && (
        <PartyTable
          title={t("Users using this API")}
          subtitle={t("Observed credentials on requests to this API · worker five-minute IP rollup", "Credential quan sát trên request tới API này · rollup IP năm phút của worker")}
          query={relationshipQuery}
          rows={users}
          durationSec={durationSec}
          kind="user"
          partnerLabel={t("Callers", "Caller")}
          empty={t("No users observed for this API")}
          search={search}
        />
      )}

      {detailTab === "callers" && (
        <PartyTable
          title={t("Caller services")}
          subtitle={t("Services observed calling this API · worker five-minute IP rollup", "Service gọi API này · rollup IP năm phút của worker")}
          query={relationshipQuery}
          rows={callers}
          durationSec={durationSec}
          kind="service"
          partnerLabel={t("Users")}
          empty={t("No caller relationships observed for this API")}
          search={search}
        />
      )}

      {detailTab === "traces" && (
        <Panel
          title={t("Representative Traces")}
          subtitle={t("Recent distributed traces executing this API")}
          className="mt-4"
          action={<button onClick={() => nav(`/traces?${qs}&service=${encodedService}&operation=${encodedApi}`)} className="text-[11px] font-semibold text-ink hover:underline">{t("Open in Traces")} <ArrowRight size={12} className="inline" /></button>}
        >
          {tracesQuery.isLoading ? <Loading /> : tracesQuery.isError ? <ErrorState message={tracesQuery.error.message} /> : traces.length ? (
            <div className="overflow-auto">
              <table className="w-full text-left text-xs">
                <thead><tr className="border-b border-line">
                  <th className="table-head px-3 py-2">{t("Trace ID")}</th>
                  <th className="table-head px-3 py-2">{t("Principal")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Duration")}</th>
                  <th className="table-head px-3 py-2 text-right">{t("Status")}</th>
                </tr></thead>
                <tbody className="divide-y divide-line">
                  {traces.map((tr: any) => (
                    <tr key={tr.trace_id || tr.id} onClick={() => nav(`/traces/${encodeURIComponent(tr.trace_id || tr.id)}`)} className="cursor-pointer transition hover:bg-hover">
                      <td className="px-3 py-2 font-mono text-ink"><Link to={`/traces/${encodeURIComponent(tr.trace_id || tr.id)}`} className="hover:underline">{(tr.trace_id || tr.id || "").slice(0, 16)}…</Link></td>
                      <td className="px-3 font-mono text-muted">{(tr.principal_name || tr.user) ? <EntityLink entity={{ kind: "user", principal: tr.principal_name || tr.user }}>{tr.principal_name || tr.user}</EntityLink> : "—"}</td>
                      <td className="px-3 text-right font-mono tabular-nums text-ink">{tr.duration_ms != null ? `${Number(tr.duration_ms).toFixed(1)} ms` : "—"}</td>
                      <td className="px-3 text-right font-mono">
                        <span className={`rounded-[2px] px-1.5 py-0.5 text-[10px] font-semibold uppercase ${String(tr.status_code || tr.http_status || tr.status).startsWith("5") ? "border border-bad-bd bg-bad-bg text-bad" : "border border-good-bd bg-good-bg text-good"}`}>
                          {tr.status_code || tr.http_status || tr.status || "OK"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="p-6 text-center text-xs text-muted">{t("No recent traces recorded for this API.")}</div>}
        </Panel>
      )}
    </Page>
  );
}

function PartyTable({ title, subtitle, query, rows, durationSec, kind, partnerLabel, empty, search }: {
  title: string;
  subtitle: string;
  query: { isLoading: boolean; isError: boolean; error: Error | null; data?: { truncated: boolean } };
  rows: Party[];
  durationSec: number;
  kind: "user" | "service";
  partnerLabel: string;
  empty: string;
  search: string;
}) {
  const { t } = useI18n();
  const nav = useNavigate();
  const path = (name: string) => entityPath(kind === "user" ? { kind: "user", principal: name } : { kind: "service", name }) + search;
  return (
    <Panel title={title} subtitle={subtitle} className="mt-4">
      {query.isLoading ? <Loading /> : query.isError ? <ErrorState message={query.error?.message || ""} /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-xs">
            <thead><tr className="border-b border-line">
              {[kind === "user" ? t("User") : t("Caller Service"), t("Requests"), t("Avg TPS", "TPS TB"), t("Error rate"), t("Max bucket P95", "P95 bucket lớn nhất"), partnerLabel, "IPs", t("Last seen")].map((heading, i) => <th className={`table-head px-3 py-2 ${i ? "text-right" : ""}`} key={heading}>{heading}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-line">
              {rows.map(row => (
                <tr key={row.name} onClick={() => nav(path(row.name))} className="cursor-pointer transition hover:bg-hover">
                  <td className="px-3 py-2 font-mono text-ink">
                    {kind === "user" ? <Users size={12} className="mr-1 inline" /> : <Activity size={12} className="mr-1 inline" />}
                    <EntityLink entity={kind === "user" ? { kind: "user", principal: row.name } : { kind: "service", name: row.name }} search={search} className="hover:underline">{row.name}</EntityLink>
                  </td>
                  <td className="px-3 text-right font-mono tabular-nums text-ink">{n(row.requests, 0)}</td>
                  <td className="px-3 text-right font-mono tabular-nums text-ink">{n(row.requests / durationSec, 4)}</td>
                  <td className={`px-3 text-right font-mono tabular-nums ${row.errorRate > 0 ? "text-bad" : "text-muted"}`}>{pct(row.errorRate)}</td>
                  <td className="px-3 text-right font-mono tabular-nums text-entity-user">{n(row.p95, 1)} ms</td>
                  <td className="px-3 text-right font-mono tabular-nums">{n(row.partners, 0)}</td>
                  <td className="px-3 text-right font-mono tabular-nums">{n(row.ips, 0)}</td>
                  <td className="px-3 text-right text-muted">{row.lastSeen ? new Date(row.lastSeen).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={8} className="px-3 py-8 text-center text-muted">{empty}</td></tr>}
            </tbody>
          </table>
          {query.data?.truncated && <p className="border-t border-line px-3 py-2 text-[11px] text-muted">{t(`Only the first ${RELATIONSHIP_PAGES * 500} relationship rows of this Service were read.`, `Chỉ đọc ${RELATIONSHIP_PAGES * 500} dòng quan hệ đầu tiên của Service.`)}</p>}
        </div>
      )}
    </Panel>
  );
}
