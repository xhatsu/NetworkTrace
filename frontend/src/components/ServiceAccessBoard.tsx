import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, Fingerprint, Globe2, KeyRound, Server } from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, n, Panel, pct } from "../components";
import { useI18n } from "../i18n";
import type { Filters } from "../types";
import { AccessBoardColumn } from "./AccessBoardColumn";
import { EntityLink } from "./EntityLink";

type Relationship = {
  source_ip: string;
  service: string;
  api: string;
  caller_service?: string;
  request_count?: number;
  error_count?: number;
  error_rate?: number;
  tps?: number;
  p95_latency_ms?: number;
  role_label?: string;
  source_ip_role?: string;
  is_load_balancer?: boolean;
};
type RelationshipPage = { items: Relationship[]; next_cursor?: string | null };

function summarize(rows: Relationship[]) {
  const requests = rows.reduce((sum, row) => sum + (row.request_count || 0), 0);
  const errors = rows.reduce((sum, row) => sum + (row.error_count ?? (row.error_rate || 0) * (row.request_count || 0)), 0);
  return { requests, errorRate: requests ? errors / requests : 0, tps: rows.reduce((sum, row) => sum + (row.tps || 0), 0), p95: Math.max(0, ...rows.map(row => row.p95_latency_ms || 0)) };
}

function group(rows: Relationship[], key: "source_ip" | "api" | "caller_service") {
  const groups = new Map<string, Relationship[]>();
  rows.forEach(row => { const name = row[key] || ""; const list = groups.get(name) || []; list.push(row); groups.set(name, list); });
  return [...groups].map(([name, items]) => ({ name, items, ...summarize(items) })).sort((a, b) => b.requests - a.requests || a.name.localeCompare(b.name));
}

export function ServiceAccessBoard({ service, accounts, filters }: {
  service: string;
  accounts: { username: string; requests: number }[];
  filters: Filters;
}) {
  const { t } = useI18n();
  const [principal, setPrincipal] = useState("");
  const [ip, setIp] = useState<string | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [ipSearch, setIpSearch] = useState("");
  const scoped = { ...filters, service, account: undefined, operation: undefined };
  const relationships = useInfiniteQuery({
    queryKey: ["service-access", service, principal, filters.start, filters.end],
    initialPageParam: "",
    queryFn: ({ pageParam }) => api<RelationshipPage>(`/api/v1/topology/principals/${encodeURIComponent(principal)}/ips?${queryString(scoped, { page_size: "500", cursor: pageParam || undefined })}`),
    getNextPageParam: page => page.next_cursor || undefined,
    enabled: !!principal,
  });
  const rows = (relationships.data?.pages.flatMap(page => page.items) || []).filter(row => row.service === service);
  const sources = group(rows, "source_ip");
  const ipRows = ip === null ? [] : rows.filter(row => (row.source_ip || "") === ip);
  const operations = group(ipRows, "api");
  const selected = operation === null ? ipRows : ipRows.filter(row => (row.api || "") === operation);
  const callers = group(selected, "caller_service");
  const metrics = summarize(selected);
  const credentials = [...new Map(accounts.filter(account => account.username && !["unknown", "-anonymous-", "anonymous"].includes(account.username)).map(account => [account.username, account])).values()].sort((a, b) => b.requests - a.requests);
  const control = (active: boolean, color: string) => `w-full border p-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#5794f2] ${active ? color : "border-[#2a2d30] bg-[#111217] hover:border-[#7b7d80]"}`;
  const empty = (text: string) => <div className="px-3 py-8 text-center text-xs text-[#c2c6cc]">{text}</div>;
  return <Panel title={`${t("Access for", "Quyền truy cập của")} ${service}`}
    subtitle={t("Select observed credential → IP → API for this Service", "Chọn credential quan sát được → IP → API của Service này")}
    titleClassName="text-sm font-semibold uppercase tracking-[0.06em] text-[#f1f3f5]"
    subtitleClassName="text-xs text-[#c2c6cc]"
    action={<span className="text-xs text-[#c2c6cc]">{rows.length} {t("loaded relationships", "quan hệ đã tải")}</span>}>
    <div data-testid="service-access-board" className="grid gap-2 p-2 md:grid-cols-[minmax(0,25fr)_minmax(0,35fr)_minmax(0,40fr)]">
      <AccessBoardColumn step={1} title={t("Observed credential", "Credential quan sát được")} subtitle={t("Identity evidence on service requests", "Bằng chứng định danh trên request tới Service")}>
        <input aria-label={t("Find credential", "Tìm credential")} placeholder={t("Find credential", "Tìm credential")} value={search} onChange={e => setSearch(e.target.value)} className="toolbar-control mb-2 h-9 w-full px-2 text-sm" />
        <div className="space-y-1">{credentials.filter(account => account.username.toLowerCase().includes(search.toLowerCase())).map(account => <button key={account.username} aria-pressed={principal === account.username} onClick={() => { setPrincipal(principal === account.username ? "" : account.username); setIp(null); setOperation(null); setIpSearch(""); }} className={control(principal === account.username, "border-[#b877d9] bg-[#b877d9]/10")}>
          <span className="flex items-center gap-2 text-[#e3c4f1]"><KeyRound size={14} aria-hidden="true" /><span className="truncate font-mono text-sm">{account.username}</span></span>
          <span className="mt-1 block text-xs text-[#c2c6cc]">{n(account.requests, 0)} {t("requests")}</span>
        </button>)}</div>
        {!credentials.some(account => account.username.toLowerCase().includes(search.toLowerCase())) && empty(t("No matching credential evidence", "Không có bằng chứng credential phù hợp"))}
      </AccessBoardColumn>
      <AccessBoardColumn step={2} title={t("Selected IP", "IP đã chọn")} subtitle={t("Supporting network evidence", "Bằng chứng mạng hỗ trợ")}>
        {!principal ? empty(t("Select a credential to reveal IPs", "Chọn credential để xem IP")) : relationships.isLoading ? <Loading /> : relationships.isError ? <><ErrorState message={relationships.error.message} /><button className="btn" onClick={() => relationships.refetch()}>{t("Retry", "Thử lại")}</button></> : <>
          <input aria-label={t("Find IP…", "Tìm IP…")} placeholder={t("Find IP…", "Tìm IP…")} value={ipSearch} onChange={e => setIpSearch(e.target.value)} className="toolbar-control mb-2 h-9 w-full px-2 text-sm" />
          <div className="space-y-1">{sources.filter(source => source.name.includes(ipSearch)).map(source => <button key={source.name} aria-pressed={ip === source.name} onClick={() => { setIp(ip === source.name ? null : source.name); setOperation(null); }} className={control(ip === source.name, "border-[#c2c6cc] bg-[#a7a9ab]/10")}>
            <span className="flex items-center gap-2 text-[#f1f3f5]"><Globe2 size={14} aria-hidden="true" /><span className="break-all font-mono text-sm">{source.name || t("IP unavailable", "IP không khả dụng")}</span></span>
            <span className="mt-1 block text-xs text-[#c2c6cc]">{source.items[0]?.role_label || source.items[0]?.source_ip_role || t("Unknown")} · {n(source.requests, 0)} {t("requests")}</span>
          </button>)}</div>
          {!sources.some(source => source.name.includes(ipSearch)) && empty(t("No matching IP evidence", "Không có bằng chứng IP phù hợp"))}
        </>}
      </AccessBoardColumn>
      <AccessBoardColumn step={3} title="API" subtitle={t("Operations on the selected Service", "API của Service đã chọn")}>
        {ip === null ? empty(t("Select an IP to reveal APIs", "Chọn IP để xem API")) : <div className="space-y-1">{operations.map(item => <button key={item.name} aria-pressed={operation === item.name} onClick={() => setOperation(operation === item.name ? null : item.name)} className={control(operation === item.name, "border-[#56b9a8] bg-[#56b9a8]/10")}>
          <span className="flex items-center gap-2 text-[#9be7d8]"><Fingerprint size={14} aria-hidden="true" /><span className="truncate font-mono text-sm">{item.name || t("Unknown operation", "Operation chưa xác định")}</span></span>
          <span className="mt-1 block text-xs text-[#c2c6cc]">{n(item.tps, 2)} TPS · {n(item.requests, 0)} {t("requests")} · {pct(item.errorRate)} {t("error")}</span>
        </button>)}</div>}
      </AccessBoardColumn>
    </div>
    {relationships.hasNextPage && <div className="border-t border-[#2a2d30] p-2 text-center"><button className="btn disabled:opacity-40" disabled={relationships.isFetchingNextPage} onClick={() => relationships.fetchNextPage()}>{relationships.isFetchingNextPage ? t("Loading…") : t("Load more relationships", "Tải thêm quan hệ")}</button></div>}
    {ip !== null && <div className="border-t border-[#2a2d30] p-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2 text-xs text-[#a9ccff]"><Server size={14} aria-hidden="true" /><span className="break-all font-mono">{service}</span>{operation && <><ArrowRight size={14} aria-hidden="true" /><EntityLink entity={{ kind: "api", service, operation }} search={`?${queryString(scoped)}`} className="break-all text-[#9be7d8] hover:underline">{operation}</EntityLink></>}</div>
      <p className="my-2 text-xs text-[#c2c6cc]">{t("Observed credential and IP are supporting evidence. Open a Trace to confirm the caller chain.", "Credential và IP quan sát được là bằng chứng hỗ trợ. Mở Trace để xác nhận chuỗi caller.")}</p>
      <div className="mb-3 flex flex-wrap gap-4 font-mono text-xs text-[#c2c6cc]"><span>{n(metrics.requests, 0)} {t("requests")}</span><span>{n(metrics.tps, 2)} TPS</span><span>{pct(metrics.errorRate)} {t("error")}</span><span>{n(metrics.p95, 1)} ms {t("Max bucket P95", "P95 bucket lớn nhất")}</span></div>
      <div className="divide-y divide-[#2a2d30]">{callers.map(caller => <div key={caller.name} className="flex flex-wrap justify-between gap-2 py-2 text-xs"><span className="text-[#a9ccff]">{t("Caller Service")}: {caller.name ? <EntityLink entity={{ kind: "service", name: caller.name }} search={`?${queryString({ ...scoped, service: undefined })}`} className="break-all hover:underline">{caller.name}</EntityLink> : t("Caller unavailable", "Caller không khả dụng")}</span><span className="font-mono text-[#c2c6cc]">{n(caller.requests, 0)} {t("requests")}</span></div>)}</div>
      <Link className="btn mt-3 inline-flex" to={`/traces?${queryString(scoped, { account: principal, principal, operation: operation || undefined })}`}>{t("View related Traces")} <ArrowRight size={13} aria-hidden="true" /></Link>
      <span className="ml-2 text-[11px] text-[#a7a9ab]">{t("Trace search scoped to credential, Service and API", "Tìm Trace theo credential, Service và API")}</span>
    </div>}
  </Panel>;
}
