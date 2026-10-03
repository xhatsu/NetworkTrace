import { useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Activity, ArrowLeft, ArrowRight, Boxes, Users, Waypoints } from "lucide-react";
import { api } from "../api";
import { ErrorState, Loading, Page, n, pct } from "../components";
import type { EpisodeResponse } from "../components/EpisodePrimitives";
import { entityPath } from "../entityRoutes";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import {
  ServicePerformancePanel, mergeServiceBandwidth, normalizeServiceBandwidth, normalizeServiceSeries,
} from "../pages/Services";
import {
  formatBytes, useRelationships, useSelection, useTimeSearch, windowParams, withSelection, workspacePath,
  type Facet, type RelRow, type Relationships, type Selection,
} from "./model";
import { ServiceFilterBar } from "./ServiceFilter";
import {
  KpiStrip, RelTable, formatTps, SelectionBar, SharedIpsPanel, Tabs, TracesPanel, UnknownUsersPanel, WhatChangedPanel, rowLink,
} from "./parts";

// ---------------------------------------------------------------------------
// Shared page pieces
// ---------------------------------------------------------------------------

/** TPS vs expected (60 s worker buckets) + bandwidth from the relationship rollup. */
function usePerformance(seriesParams: Record<string, string>, data?: Relationships) {
  const { filters } = useFilters();
  const qs = windowParams(filters);
  Object.entries(seriesParams).forEach(([key, value]) => qs.set(key, value));
  const seriesQuery = useQuery({
    queryKey: ["ws-series", qs.toString()],
    queryFn: async () => {
      const body = await api<Array<Record<string, unknown>> | { items?: Array<Record<string, unknown>> }>(`/api/v1/dashboard/series?${qs.toString()}`);
      return Array.isArray(body) ? body : body.items || [];
    },
  });
  const durationSec = Math.max(1, (Date.parse(filters.end) - Date.parse(filters.start)) / 1000 || 1);
  const series = useMemo(() => normalizeServiceSeries((seriesQuery.data || []).map((point) => ({ ...point, requests: point.sample_count ?? 0 }))), [seriesQuery.data]);
  const bandwidthSeries = useMemo(() => normalizeServiceBandwidth(data?.series), [data?.series]);
  const chartSeries = useMemo(() => mergeServiceBandwidth(series, bandwidthSeries), [series, bandwidthSeries]);
  const totals = useMemo(() => {
    const requests = series.reduce((sum, point) => sum + point.requests, 0);
    const errors = series.reduce((sum, point) => sum + point.requests * (point.failure_rate || 0), 0);
    return { requests, errors, failureRate: requests ? errors / requests : 0, worstP95: Math.max(0, ...series.map((point) => point.p95_ms || 0)) };
  }, [series]);
  const summary = data?.summary;
  const span = data ? Math.max(1, (data.window.end_ms - data.window.start_ms) / 1000) : durationSec;
  const bandwidthMetrics: Record<string, number> = summary ? {
    request_bytes_per_second: summary.request_bytes / span,
    response_bytes_per_second: summary.response_bytes / span,
    bandwidth_bytes_per_second: (summary.request_bytes + summary.response_bytes) / span,
  } : {};
  return { seriesQuery, series, bandwidthSeries, chartSeries, totals, durationSec, bandwidthMetrics };
}

function useEpisodes(params: Record<string, string>) {
  const { filters } = useFilters();
  const qs = windowParams(filters);
  Object.entries(params).forEach(([key, value]) => qs.set(key, value));
  qs.set("limit", "10");
  return useQuery({ queryKey: ["ws-episodes", qs.toString()], queryFn: () => api<EpisodeResponse>(`/api/v1/changes?${qs.toString()}`) });
}

function Section({ title, children, className = "" }: { title: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 space-y-3 ${className}`}>
      <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{title}</h3>
      {children}
    </section>
  );
}

function ContextLine({ children }: { children: ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">{children}</div>;
}

function Chip({ to, tone, icon, children }: { to?: string; tone: string; icon?: ReactNode; children: ReactNode }) {
  const cls = `inline-flex items-center gap-1.5 rounded-ctl border border-line-strong bg-surface px-2 py-1 font-mono ${tone}`;
  return to ? <Link to={to} className={`${cls} hover:underline`}>{icon}{children}</Link> : <span className={cls}>{icon}{children}</span>;
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <span className="font-mono text-[11px]"><span className="text-faint">{label}</span> <span className="text-ink">{value}</span></span>;
}

function ProbeError({ error }: { error: Error | null }) {
  return error ? <div className="mt-3"><ErrorState message={error.message} /></div> : null;
}

/** Toggle helper bound to one facet. */
function selector(toggle: (facet: Facet, row: RelRow | null) => void, facet: Facet) {
  return (row: RelRow | null) => toggle(facet, row);
}


// ---------------------------------------------------------------------------
// User workspace: /workspace/users/:principal
// ---------------------------------------------------------------------------

export function UserWorkspacePage() {
  const { principal = "" } = useParams();
  const { t } = useI18n();
  const search = useTimeSearch();
  const sel = useSelection();
  const { selection, toggle } = sel;
  const [limit, setLimit] = useState(200);
  const [tab, setTab] = useState("shared");
  const rel = useRelationships({ principal }, selection, ["caller", "service", "api", "ip", "shared"], limit);
  const perf = usePerformance({ account: principal }, rel.data);
  const episodes = useEpisodes({ principal });
  const data = rel.data;
  const summary = data?.summary;
  const showAll = () => setLimit(1000);
  const apiLink = (row: RelRow) => row.service ? `${workspacePath.api(row.service, row.name)}${withSelection(search, { principal })}` : null;

  return (
    <Page
      eyebrow={t("User", "User")}
      title={principal}
      description={t("Who sends this identity, and which APIs it reaches", "Ai gửi danh tính này và nó truy cập những API nào")}
      actions={<>
        <Link className="btn" to={`${workspacePath.users()}${search}`}><ArrowLeft size={13} /> {t("All users", "Tất cả user")}</Link>
        <Link className="btn" to={`${entityPath({ kind: "user", principal })}${search}`}>{t("Previous view", "Giao diện cũ")}</Link>
      </>}
    >
      <ContextLine>
        <Chip tone="text-entity-user" icon={<Users size={12} />}>{principal}</Chip>
        {summary && <>
          <Stat label={t("callers", "caller")} value={n(summary.callers, 0)} />
          <Stat label="Services" value={n(summary.services, 0)} />
          <Stat label="APIs" value={n(summary.apis, 0)} />
          <Stat label="IPs" value={n(summary.ips, 0)} />
        </>}
      </ContextLine>
      <ProbeError error={rel.error} />

      <ServicePerformancePanel
        key={principal}
        series={perf.series}
        bandwidthSeries={perf.bandwidthSeries}
        chartSeries={perf.chartSeries}
        totalRequests={perf.totals.requests}
        totalErrors={perf.totals.errors}
        operationsCount={summary?.apis || 0}
        durationSec={perf.durationSec}
        failureRate={perf.totals.failureRate}
        worstP95={perf.totals.worstP95}
        bandwidthMetrics={perf.bandwidthMetrics}
        latencyDetail={t("Highest one-minute P95 in the window", "P95 một phút cao nhất trong khoảng")}
        aside={<WhatChangedPanel data={data} episodes={episodes} viewAllHref={`/changes${withSelection(search, {})}&principal=${encodeURIComponent(principal)}`} search={search} />}
      />

      <SelectionBar sel={sel} />

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Section className="lg:col-span-2" title={<>{t("Comes from", "Đến từ")} <ArrowRight size={12} /></>}>
          <RelTable facet="caller" title={t("Caller services", "Caller service")} subtitle={t("Services that sent requests with this identity", "Service gửi request mang danh tính này")}
            result={data?.facets.caller} loading={rel.isLoading} selection={selection} onSelect={selector(toggle, "caller")}
            link={rowLink("caller", search)} columns={["tps", "error", "apis"]} empty={t("No caller service observed", "Không thấy caller service")} onShowAll={showAll} compact />
          <RelTable facet="ip" title={t("Source IPs", "IP nguồn")} subtitle={t("Network addresses this identity came from", "Địa chỉ mạng danh tính này xuất phát")}
            result={data?.facets.ip} loading={rel.isLoading} selection={selection} onSelect={selector(toggle, "ip")}
            columns={["role", "tps", "apis"]} empty={t("No source IP observed", "Không thấy IP nguồn")} onShowAll={showAll} compact />
        </Section>
        <Section className="lg:col-span-3" title={<><ArrowRight size={12} /> {t("Reaches", "Truy cập")}</>}>
          <ServiceFilterBar result={data?.facets.service} options={data?.service_meta_options} sel={sel} label="Service" />
          <RelTable facet="api" title={t("APIs used", "API đã dùng")} subtitle={t("Grouped by owning Service; open an API to see it from this user's side", "Nhóm theo Service sở hữu; mở API để xem từ phía user này")}
            result={data?.facets.api} loading={rel.isLoading} selection={selection} onSelect={selector(toggle, "api")}
            link={apiLink} columns={["tps", "requests", "error", "p95", "callers", "last"]} empty={t("No API observed", "Không thấy API")} onShowAll={showAll} />
        </Section>
      </div>

      <Tabs value={tab} onChange={setTab} tabs={[
        ["shared", t("Shared IPs", "IP dùng chung"), data?.facets.shared?.total],
        ["traces", t("Traces", "Trace"), undefined],
      ]} />
      {tab === "shared" && <SharedIpsPanel data={data} loading={rel.isLoading} search={search} />}
      {tab === "traces" && <TracesPanel params={{ principal }} openHref={`/traces${search}&principal=${encodeURIComponent(principal)}`} />}
    </Page>
  );
}

// ---------------------------------------------------------------------------
// API workspace: /workspace/apis/:service/:api
// ---------------------------------------------------------------------------

export function ApiWorkspacePage() {
  const { service = "", api: apiName = "" } = useParams();
  const { t } = useI18n();
  const search = useTimeSearch();
  const sel = useSelection();
  const { selection, toggle } = sel;
  const [limit, setLimit] = useState(200);
  const [tab, setTab] = useState("unknown");
  const tabsRef = useRef<HTMLDivElement>(null);
  const rel = useRelationships({ service, api: apiName }, selection, ["principal", "caller", "ip", "unknown_ip"], limit);
  const perf = usePerformance({ service, operation: apiName }, rel.data);
  const episodes = useEpisodes({ service, q: apiName });
  const data = rel.data;
  const summary = data?.summary;
  const showAll = () => setLimit(1000);
  const userLink = (row: RelRow) => `${workspacePath.user(row.name)}${withSelection(search, { api: apiName, api_service: service })}`;
  const unknownShare = summary?.requests ? summary.unknown_requests / summary.requests : 0;
  const openUnknown = () => { setTab("unknown"); tabsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); };

  return (
    <Page
      eyebrow="API"
      title={apiName}
      description={t("Who uses this API: identified users, unknown users by IP, and the services calling it", "Ai dùng API này: user đã xác định, user chưa xác định theo IP và service gọi nó")}
      actions={<>
        <Link className="btn" to={`${workspacePath.apis()}${search}`}><ArrowLeft size={13} /> {t("All APIs", "Tất cả API")}</Link>
        <Link className="btn" to={`${entityPath({ kind: "api", service, operation: apiName })}${search}`}>{t("Previous view", "Giao diện cũ")}</Link>
      </>}
    >
      <ContextLine>
        <Chip to={`${workspacePath.service(service)}${search}`} tone="text-entity-service" icon={<Boxes size={12} />}>{service}</Chip>
        <span>/</span>
        <Chip tone="text-entity-api" icon={<Waypoints size={12} />}>{apiName}</Chip>
        {summary && <>
          <Stat label={t("users", "user")} value={n(summary.principals, 0)} />
          <Stat label={t("unknown", "chưa xác định")} value={`${pct(unknownShare)} · ${n(summary.unknown_ips, 0)} IPs`} />
          <Stat label={t("callers", "caller")} value={n(summary.callers, 0)} />
        </>}
      </ContextLine>
      <ProbeError error={rel.error} />

      <ServicePerformancePanel
        key={`${service}|${apiName}`}
        series={perf.series}
        bandwidthSeries={perf.bandwidthSeries}
        chartSeries={perf.chartSeries}
        totalRequests={perf.totals.requests}
        totalErrors={perf.totals.errors}
        operationsCount={1}
        durationSec={perf.durationSec}
        failureRate={perf.totals.failureRate}
        worstP95={perf.totals.worstP95}
        bandwidthMetrics={perf.bandwidthMetrics}
        latencyDetail={t("Highest one-minute P95 in the window", "P95 một phút cao nhất trong khoảng")}
        aside={<WhatChangedPanel data={data} episodes={episodes} viewAllHref={`/changes${search}&service=${encodeURIComponent(service)}&q=${encodeURIComponent(apiName)}`} search={search} />}
      />

      <SelectionBar sel={sel} />

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Section className="lg:col-span-3" title={<><Users size={12} /> {t("Used by", "Được dùng bởi")}</>}>
          <RelTable facet="principal" title={t("Users", "User")} subtitle={t("Identified credentials on requests to this API", "Credential xác định trên request tới API này")}
            result={data?.facets.principal} loading={rel.isLoading} selection={selection} onSelect={selector(toggle, "principal")}
            link={userLink} columns={["tps", "requests", "error", "p95", "callers", "ips", "last"]} empty={t("No identified user", "Không có user xác định")} onShowAll={showAll}
            footer={summary && summary.unknown_requests > 0 ? (
              <button type="button" onClick={openUnknown} className="flex w-full items-center gap-2 border-t border-line px-3 py-2 text-left text-xs hover:bg-hover">
                <span className="font-semibold text-warn">{t("Unknown users", "User chưa xác định")}</span>
                <span className="font-mono text-muted">{n(summary.unknown_requests, 0)} {t("requests", "request")} ({pct(unknownShare)}) · {n(summary.unknown_ips, 0)} IPs</span>
                <ArrowRight size={12} className="ml-auto text-muted" />
              </button>
            ) : null} />
        </Section>
        <Section className="lg:col-span-2" title={<><Activity size={12} /> {t("Called through", "Được gọi qua")}</>}>
          <RelTable facet="caller" title={t("Caller services", "Caller service")} result={data?.facets.caller} loading={rel.isLoading}
            selection={selection} onSelect={selector(toggle, "caller")} link={rowLink("caller", search)}
            columns={["tps", "users", "unknown"]} empty={t("No caller service observed", "Không thấy caller service")} onShowAll={showAll} compact />
          <RelTable facet="ip" title={t("Source IPs", "IP nguồn")} result={data?.facets.ip} loading={rel.isLoading}
            selection={selection} onSelect={selector(toggle, "ip")} columns={["role", "tps", "unknown"]}
            empty={t("No source IP observed", "Không thấy IP nguồn")} onShowAll={showAll} compact />
        </Section>
      </div>

      <div ref={tabsRef} className="scroll-mt-16">
        <Tabs value={tab} onChange={setTab} tabs={[
          ["unknown", t("Unknown users", "User chưa xác định"), data?.facets.unknown_ip?.total],
          ["traces", t("Traces", "Trace"), undefined],
        ]} />
      </div>
      {tab === "unknown" && <UnknownUsersPanel data={data} loading={rel.isLoading} onShowAll={showAll} title={t("Unknown users of this API, by source IP", "User chưa xác định của API này, theo IP nguồn")} />}
      {tab === "traces" && <TracesPanel params={{ service, operation: apiName }} openHref={`/traces${search}&service=${encodeURIComponent(service)}&operation=${encodeURIComponent(apiName)}`} />}
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Service scope: /workspace/services/:service (explore and group, not a target)
// ---------------------------------------------------------------------------

export function ServiceScopePage() {
  const { service = "" } = useParams();
  const { t } = useI18n();
  const search = useTimeSearch();
  const sel = useSelection();
  const { selection, toggle } = sel;
  const [limit, setLimit] = useState(300);
  const rel = useRelationships({ service }, selection, ["api", "principal", "caller", "unknown_ip"], limit);
  const data = rel.data;
  const summary = data?.summary;
  const showAll = () => setLimit(1000);

  return (
    <Page
      eyebrow={t("Service scope", "Phạm vi Service")}
      title={service}
      description={t("A Service groups APIs and users. Pick an API or a user to investigate it.", "Service nhóm API và user. Chọn một API hoặc user để điều tra.")}
      actions={<>
        <Link className="btn" to={`${workspacePath.services()}${search}`}><ArrowLeft size={13} /> {t("All services", "Tất cả Service")}</Link>
        <Link className="btn" to={`${entityPath({ kind: "service", name: service })}${search}`}>{t("Performance view", "Góc nhìn hiệu năng")}</Link>
      </>}
    >
      <ProbeError error={rel.error} />
      {summary ? (
        <KpiStrip items={[
          ["APIs", n(summary.apis, 0)],
          [t("Users", "User"), n(summary.principals, 0)],
          [t("Unknown traffic", "Lưu lượng chưa xác định"), pct(summary.requests ? summary.unknown_requests / summary.requests : 0), `${n(summary.unknown_ips, 0)} IPs`],
          [t("Caller services", "Caller service"), n(summary.callers, 0)],
          [t("Requests", "Request"), n(summary.requests, 0)],
          ["TPS", formatTps(summary.tps)],
          [t("Error rate", "Tỷ lệ lỗi"), pct(summary.error_rate), formatBytes(summary.request_bytes + summary.response_bytes)],
        ]} />
      ) : rel.isLoading ? <Loading /> : null}

      <div className="mt-3">
        <ServiceFilterBar facet="caller" result={data?.facets.caller} options={data?.service_meta_options} sel={sel} label={t("Called through", "Gọi qua")} showMeta={false} />
      </div>
      <SelectionBar sel={sel} />

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Section className="lg:col-span-3" title={<><Waypoints size={12} /> APIs</>}>
          <RelTable facet="api" title={t("APIs in this Service", "API trong Service này")} subtitle={t("Select an API to narrow the users; open it to investigate", "Chọn API để lọc user; mở để điều tra")}
            result={data?.facets.api} loading={rel.isLoading} selection={selection} onSelect={selector(toggle, "api")}
            link={rowLink("api", search)} columns={["tps", "requests", "error", "p95", "users", "unknown"]}
            empty={t("No API observed", "Không thấy API")} onShowAll={showAll} />
        </Section>
        <Section className="lg:col-span-2" title={<><Users size={12} /> {t("Users", "User")}</>}>
          <RelTable facet="principal" title={t("Users of this Service", "User của Service này")} subtitle={t("Select a user to narrow the APIs", "Chọn user để lọc API")}
            result={data?.facets.principal} loading={rel.isLoading} selection={selection} onSelect={selector(toggle, "principal")}
            link={rowLink("principal", search)} columns={["tps", "apis", "ips"]} empty={t("No identified user", "Không có user xác định")} onShowAll={showAll} />
        </Section>
      </div>

      <h3 className="mt-6 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{t("Unknown users", "User chưa xác định")}</h3>
      <UnknownUsersPanel data={data} loading={rel.isLoading} onShowAll={showAll} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Index pages: /workspace/users, /workspace/apis, /workspace/services
// ---------------------------------------------------------------------------

function IndexPage({ kind }: { kind: "users" | "apis" | "services" }) {
  const { t } = useI18n();
  const search = useTimeSearch();
  const sel = useSelection();
  const { selection, toggle } = sel;
  const facets = kind === "services" ? ["service"] : [kind === "users" ? "principal" : "api", "service"];
  const rel = useRelationships({}, selection, facets, 1000);
  const data = rel.data;
  const summary = data?.summary;
  const copy = {
    users: {
      eyebrow: t("Workspace", "Không gian làm việc"), title: t("Users", "User"),
      description: t("Every identified user in the window. Open one to see where it comes from and which APIs it reaches.", "Mọi user đã xác định trong khoảng. Mở một user để xem nguồn gốc và API nó truy cập."),
    },
    apis: {
      eyebrow: t("Workspace", "Không gian làm việc"), title: "APIs",
      description: t("Every API in the window, grouped by Service. Open one to see its users and unknown users.", "Mọi API trong khoảng, nhóm theo Service. Mở một API để xem user và user chưa xác định."),
    },
    services: {
      eyebrow: t("Workspace", "Không gian làm việc"), title: t("Service scopes", "Phạm vi Service"),
      description: t("Services group APIs and users. Open one to browse what it contains.", "Service nhóm API và user. Mở một Service để duyệt nội dung."),
    },
  }[kind];

  return (
    <Page eyebrow={copy.eyebrow} title={copy.title} description={copy.description}>
      <ProbeError error={rel.error} />
      {summary ? (
        <KpiStrip items={[
          [t("Users", "User"), n(summary.principals, 0)],
          ["APIs", n(summary.apis, 0)],
          ["Services", n(summary.services, 0)],
          [t("Unknown traffic", "Lưu lượng chưa xác định"), pct(summary.requests ? summary.unknown_requests / summary.requests : 0), `${n(summary.unknown_requests, 0)} ${t("requests", "request")}`],
          [t("Unknown-user IPs", "IP user chưa xác định"), n(summary.unknown_ips, 0)],
          [t("Requests", "Request"), n(summary.requests, 0)],
          [t("Error rate", "Tỷ lệ lỗi"), pct(summary.error_rate)],
        ]} />
      ) : rel.isLoading ? <Loading /> : null}

      <div className="mt-3">
        <ServiceFilterBar result={data?.facets.service} options={data?.service_meta_options} sel={sel} label="Service" showPicker={kind !== "services"} />
      </div>
      <SelectionBar sel={sel} />

      <div className="mt-4">
        {kind === "users" && <RelTable facet="principal" title={t("Users", "User")} result={data?.facets.principal} loading={rel.isLoading}
          link={rowLink("principal", search)} columns={["tps", "requests", "error", "p95", "services", "apis", "callers", "ips", "last"]}
          empty={t("No identified user in this window", "Không có user xác định trong khoảng này")} />}
        {kind === "apis" && <RelTable facet="api" title="APIs" result={data?.facets.api} loading={rel.isLoading}
          link={rowLink("api", search)} columns={["tps", "requests", "error", "p95", "users", "unknown", "callers", "ips", "last"]}
          empty={t("No API in this window", "Không có API trong khoảng này")} />}
        {kind === "services" && <RelTable facet="service" title="Services" result={data?.facets.service} loading={rel.isLoading}
          link={rowLink("service", search)} columns={["tps", "requests", "error", "apis", "users", "unknown", "callers", "last"]}
          empty={t("No Service in this window", "Không có Service trong khoảng này")} />}
      </div>
      {!rel.isLoading && !data && <ErrorState message={t("No data", "Không có dữ liệu")} />}
    </Page>
  );
}

export const UsersIndexPage = () => <IndexPage kind="users" />;
export const ApisIndexPage = () => <IndexPage kind="apis" />;
export const ServicesIndexPage = () => <IndexPage kind="services" />;
