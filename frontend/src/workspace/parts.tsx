import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowRight, ArrowUp, Search, X } from "lucide-react";
import { api } from "../api";
import { ErrorState, Loading, Panel, n, pct } from "../components";
import { EpisodeStatusBadge, type EpisodeResponse } from "../components/EpisodePrimitives";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import {
  UNKNOWN_PRINCIPALS, isSelected, shortTime, tpsDigits, windowParams, workspacePath,
  type Facet, type FacetResult, type RelRow, type Relationships, type Selection, type SelectionApi, type SharedRow,
} from "./model";

type T = (en: string, vi?: string) => string;

export function useFacetLabels() {
  const { t } = useI18n();
  return {
    caller: t("Caller service", "Caller service"),
    principal: t("User", "User"),
    service: t("Service", "Service"),
    api: "API",
    ip: t("Source IP", "IP nguồn"),
  } as Record<Facet, string>;
}

/** TPS with enough digits for sparse traffic; non-zero values never round to 0. */
export function formatTps(value: number) {
  if (value > 0 && value < 0.0001) return "<0.0001";
  return n(value, tpsDigits(value));
}

export function StateBadge({ state }: { state: RelRow["state"] }) {
  const { t } = useI18n();
  if (state === "new") return <span className="rounded-[2px] border border-warn px-1 text-[10px] font-semibold uppercase text-warn">{t("New", "Mới")}</span>;
  if (state === "silent") return <span className="rounded-[2px] border border-dashed border-line-strong px-1 text-[10px] uppercase text-muted">{t("Silent", "Im lặng")}</span>;
  return null;
}

// ---------------------------------------------------------------------------
// Relationship table: one list of a facet, selectable, searchable, sortable.
// ---------------------------------------------------------------------------

export type ColumnKey = "tps" | "requests" | "error" | "p95" | "users" | "unknown" | "callers" | "apis" | "services" | "ips" | "role" | "last";

type Column = { label: string; sort: (row: RelRow) => number | string; render: (row: RelRow) => ReactNode; title?: string };

function columnsFor(t: T): Record<ColumnKey, Column> {
  return {
    tps: { label: "TPS", sort: (r) => r.tps, render: (r) => <span className="text-ink">{formatTps(r.tps)}</span> },
    requests: { label: t("Requests", "Request"), sort: (r) => r.requests, render: (r) => n(r.requests, 0) },
    error: { label: t("Errors", "Lỗi"), sort: (r) => r.error_rate, render: (r) => <span className={r.error_rate > 0 ? "text-bad" : "text-muted"}>{pct(r.error_rate)}</span> },
    p95: { label: "P95", sort: (r) => r.p95_ms, render: (r) => r.p95_ms ? `${n(r.p95_ms, 0)} ms` : "—", title: t("Highest five-minute P95", "P95 năm phút cao nhất") },
    users: { label: t("Users", "User"), sort: (r) => r.principals, render: (r) => n(r.principals, 0) },
    unknown: {
      label: t("Unknown", "Chưa xác định"),
      sort: (r) => r.unknown_requests,
      title: t("Requests without an identified user", "Request không có user xác định"),
      render: (r) => r.unknown_requests ? <span className="text-warn">{pct(r.requests ? r.unknown_requests / r.requests : 0)}</span> : <span className="text-muted">—</span>,
    },
    callers: { label: t("Callers", "Caller"), sort: (r) => r.callers, render: (r) => n(r.callers, 0) },
    apis: { label: "APIs", sort: (r) => r.apis, render: (r) => n(r.apis, 0) },
    services: { label: "Services", sort: (r) => r.services, render: (r) => n(r.services, 0) },
    ips: { label: "IPs", sort: (r) => r.ips, render: (r) => n(r.ips, 0) },
    role: {
      label: t("Role", "Vai trò"),
      sort: (r) => r.role_label || "",
      render: (r) => <span className={r.is_load_balancer ? "text-warn" : "text-muted"}>{r.role_label || r.role || "—"}</span>,
    },
    last: { label: t("Last seen", "Lần cuối"), sort: (r) => r.last_seen_ms || 0, render: (r) => <span className="text-muted">{shortTime(r.last_seen_ms)}</span> },
  };
}

export function RelTable({
  facet, title, subtitle, result, loading, error, selection, onSelect, link, columns, empty, onShowAll, footer, className = "", compact = false,
}: {
  facet: Facet;
  title: string;
  subtitle?: string;
  result?: FacetResult;
  loading?: boolean;
  error?: Error | null;
  selection?: Selection;
  onSelect?: (row: RelRow | null) => void;
  link?: (row: RelRow) => string | null;
  columns: ColumnKey[];
  empty: string;
  onShowAll?: () => void;
  footer?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: ColumnKey | "name"; desc: boolean }>({ key: "tps", desc: true });
  const defs = columnsFor(t);
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = (result?.items || []).filter((row) => !needle || `${row.name} ${row.service || ""}`.toLowerCase().includes(needle));
    const value = (row: RelRow) => sort.key === "name" ? row.name : defs[sort.key].sort(row);
    return [...filtered].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
      return (sort.desc ? -cmp : cmp) || a.name.localeCompare(b.name);
    });
  }, [result, query, sort]); // eslint-disable-line react-hooks/exhaustive-deps
  const header = (key: ColumnKey | "name", label: string, right: boolean, hint?: string) => (
    <th scope="col" className={`table-head sticky top-0 z-[1] bg-surface px-2.5 py-2 ${right ? "text-right" : ""}`} title={hint}>
      <button type="button" className="inline-flex items-center gap-1 hover:text-ink" onClick={() => setSort((prev) => ({ key, desc: prev.key === key ? !prev.desc : key !== "name" }))}>
        {label}{sort.key === key && (sort.desc ? <ArrowDown size={10} /> : <ArrowUp size={10} />)}
      </button>
    </th>
  );
  return (
    <Panel
      title={title}
      subtitle={subtitle}
      className={className}
      action={<span className="font-mono text-[10px] text-muted">{result ? `${rows.length} / ${n(result.total, 0)}` : ""}</span>}
    >
      {!compact && (
        <div className="flex items-center gap-2 border-b border-line px-2.5 py-1.5">
          <Search size={12} className="text-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("Filter this list…", "Lọc danh sách…")}
            aria-label={`${t("Filter", "Lọc")} ${title}`}
            className="min-w-0 flex-1 bg-transparent py-1 text-xs text-ink outline-none placeholder:text-faint"
          />
        </div>
      )}
      {loading && !result ? <Loading /> : error ? <ErrorState message={error.message} /> : (
        <div className={`overflow-auto ${compact ? "max-h-[260px]" : "max-h-[420px]"}`}>
          <table className="w-full text-left text-xs">
            <thead><tr className="border-b border-line">
              {header("name", facetLabel(facet, t), false)}
              {columns.map((key) => header(key, defs[key].label, true, defs[key].title))}
            </tr></thead>
            <tbody className="divide-y divide-line">
              {rows.map((row) => {
                const active = selection ? isSelected(selection, facet, row) : false;
                const to = link?.(row);
                return (
                  <tr
                    key={`${row.service || ""}|${row.name}`}
                    aria-selected={active}
                    onClick={() => onSelect?.(row)}
                    className={`${onSelect ? "cursor-pointer" : ""} transition ${active ? "bg-accent-soft" : "hover:bg-hover"} ${row.state === "silent" ? "text-muted" : ""}`}
                  >
                    <td className={`max-w-[320px] px-2.5 py-1.5 ${active ? "font-semibold" : ""}`}>
                      <div className="flex min-w-0 items-center gap-1.5">
                        {to
                          ? <Link to={to} onClick={(event) => event.stopPropagation()} className={`truncate font-mono hover:underline ${entityTone(facet)}`} title={row.name}>{row.name}</Link>
                          : <span className={`truncate font-mono ${entityTone(facet)}`} title={row.name}>{row.name}</span>}
                        <StateBadge state={row.state} />
                      </div>
                      {facet === "api" && row.service && <div className="truncate text-[10px] text-muted">{row.service}</div>}
                    </td>
                    {columns.map((key) => <td key={key} className="whitespace-nowrap px-2.5 text-right font-mono tabular-nums">{defs[key].render(row)}</td>)}
                  </tr>
                );
              })}
              {!rows.length && <tr><td colSpan={columns.length + 1} className="px-3 py-6 text-center text-muted">{empty}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {footer}
      {result?.truncated && onShowAll && (
        <button type="button" onClick={onShowAll} className="w-full border-t border-line px-3 py-1.5 text-left text-[11px] text-muted hover:text-ink">
          {t(`Showing the busiest ${result.items.length} of ${result.total}. Load all`, `Hiển thị ${result.items.length} / ${result.total} nhiều nhất. Tải tất cả`)} <ArrowRight size={11} className="inline" />
        </button>
      )}
    </Panel>
  );
}

function facetLabel(facet: Facet, t: T) {
  return { caller: t("Caller service", "Caller service"), principal: "User", service: "Service", api: "API", ip: t("Source IP", "IP nguồn") }[facet];
}

export function entityTone(facet: Facet) {
  return { caller: "text-entity-service", principal: "text-entity-user", service: "text-entity-service", api: "text-entity-api", ip: "text-entity-ip" }[facet];
}

/** Workspace page of a row, or null when the row has no page (IPs, unknown users). */
export function rowLink(facet: Facet, search: string) {
  return (row: RelRow) => {
    if (facet === "principal") return UNKNOWN_PRINCIPALS.has(row.name) ? null : `${workspacePath.user(row.name)}${search}`;
    if (facet === "api") return row.service ? `${workspacePath.api(row.service, row.name)}${search}` : null;
    if (facet === "service" || facet === "caller") return `${workspacePath.service(row.name)}${search}`;
    return null;
  };
}

// ---------------------------------------------------------------------------
// Selection bar: the active row filters, each removable.
// ---------------------------------------------------------------------------

export function SelectionBar({ sel }: { sel: SelectionApi }) {
  const { t, lang } = useI18n();
  const labels = useFacetLabels();
  const { selection } = sel;
  const chips: Array<{ key: keyof Selection; facet?: Facet; label: string; value: string; text: string }> = [];
  (["environment", "group", "module"] as const).forEach((key) => {
    const value = selection[key];
    if (value) chips.push({ key, label: { environment: t("Environment", "Môi trường"), group: lang === "vi" ? "Nhóm" : "Group", module: "Module" }[key], value, text: value });
  });
  (Object.keys(labels) as Facet[]).forEach((facet) => {
    const value = selection[facet];
    const values = Array.isArray(value) ? value : value ? [value] : [];
    values.forEach((item) => chips.push({
      key: facet, facet, label: labels[facet], value: item,
      text: facet === "api" && selection.api_service ? `${selection.api_service} · ${item}` : item,
    }));
  });
  if (!chips.length) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 rounded-card border border-line-strong bg-accent-soft px-3 py-2 text-xs">
      <span className="font-semibold text-ink">{t("Narrowed to", "Đang lọc theo")}</span>
      {chips.map((chip) => (
        <span key={`${chip.key}|${chip.value}`} className="inline-flex max-w-full items-center gap-1 rounded-ctl border border-line-strong bg-surface px-2 py-0.5">
          <span className="text-muted">{chip.label}</span>
          <span className={`truncate font-mono ${chip.facet ? entityTone(chip.facet) : "text-ink"}`}>{chip.text}</span>
          <button type="button" aria-label={`${t("Remove", "Bỏ")} ${chip.text}`} onClick={() => sel.remove(chip.key, chip.value)} className="text-muted hover:text-ink"><X size={11} /></button>
        </span>
      ))}
      <button type="button" onClick={sel.clear} className="ml-auto text-[11px] text-muted hover:text-ink hover:underline">{t("Clear all", "Bỏ tất cả")}</button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// What's different: relationship changes vs the previous window + episodes.
// ---------------------------------------------------------------------------

export function WhatChangedPanel({ data, episodes, viewAllHref, search }: {
  data?: Relationships;
  episodes: { isLoading: boolean; data?: EpisodeResponse };
  viewAllHref: string;
  search: string;
}) {
  const { t } = useI18n();
  const labels = useFacetLabels();
  const changes = useMemo(() => {
    const out: Array<{ facet: Facet; row: RelRow }> = [];
    (Object.keys(labels) as Facet[]).forEach((facet) => {
      (data?.facets[facet]?.items || []).forEach((row) => row.state !== "active" && out.push({ facet, row }));
    });
    return out.sort((a, b) => Number(b.row.state === "new") - Number(a.row.state === "new") || (b.row.requests + b.row.prev_requests) - (a.row.requests + a.row.prev_requests));
  }, [data, labels]);
  const items = episodes.data?.items || [];
  return (
    <Panel
      title={t("What's different", "Điều gì khác")}
      subtitle={t("Relationships vs the previous window, then change episodes", "Quan hệ so với khoảng trước, sau đó là episode thay đổi")}
      className="flex h-full min-w-0 flex-col"
      action={<Link to={viewAllHref} className="shrink-0 text-[11px] font-semibold text-ink hover:underline">{t("All changes", "Mọi thay đổi")} <ArrowRight size={12} className="inline" /></Link>}
    >
      <div className="max-h-[330px] flex-1 divide-y divide-line overflow-y-auto">
        {changes.slice(0, 8).map(({ facet, row }) => (
          <div key={`${facet}|${row.service || ""}|${row.name}`} className="flex items-center gap-2 px-3 py-1.5 text-xs">
            <StateBadge state={row.state} />
            <span className="shrink-0 text-muted">{labels[facet]}</span>
            <span className={`min-w-0 flex-1 truncate font-mono ${entityTone(facet)}`} title={row.name}>{row.service ? `${row.service} · ` : ""}{row.name}</span>
            <span className="shrink-0 font-mono text-[10px] text-muted">{row.state === "silent" ? `${t("was", "trước")} ${n(row.prev_requests, 0)}` : n(row.requests, 0)}</span>
          </div>
        ))}
        {data && !changes.length && (
          <p className="px-3 py-2 text-[11px] text-muted">
            {data.window.history_available
              ? t("No relationship started or stopped compared with the previous window.", "Không có quan hệ mới hoặc dừng so với khoảng trước.")
              : t("No relationship stopped. New relationships need a full previous window of history to detect.", "Không có quan hệ dừng. Cần đủ lịch sử của khoảng trước để phát hiện quan hệ mới.")}
          </p>
        )}
        {episodes.isLoading ? <Loading /> : items.slice(0, 4).map((episode) => (
          <div key={episode.id} className="flex items-start gap-2 px-3 py-1.5 text-xs">
            <EpisodeStatusBadge episode={episode} />
            <Link to={`/changes/${encodeURIComponent(episode.id)}${search}`} className="min-w-0 flex-1 truncate font-semibold text-ink hover:underline" title={episode.summary}>{episode.summary}</Link>
            <span className="shrink-0 font-mono text-[10px] text-muted">{shortTime(episode.last_seen_at || null)}</span>
          </div>
        ))}
        {!episodes.isLoading && !items.length && <p className="px-3 py-2 text-[11px] text-muted">{t("No change episodes in this window.", "Không có episode thay đổi trong khoảng này.")}</p>}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Compact KPI strip for scope and index pages.
// ---------------------------------------------------------------------------

export function KpiStrip({ items }: { items: Array<[string, ReactNode, string?]> }) {
  return (
    <dl className="grid grid-cols-2 overflow-hidden rounded-card border border-line bg-surface sm:grid-cols-4 xl:grid-cols-7">
      {items.map(([label, value, note]) => (
        <div key={label} className="min-w-0 border-b border-l border-line px-3 py-2 -ml-px -mb-px">
          <dt className="truncate text-[11px] text-muted">{label}</dt>
          <dd className="mt-0.5 truncate font-mono text-lg tabular-nums text-ink">{value}</dd>
          {note && <dd className="truncate text-[10px] text-faint">{note}</dd>}
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------------------
// Evidence: unknown users by IP, shared IPs, traces.
// ---------------------------------------------------------------------------

export function UnknownUsersPanel({ data, loading, onShowAll, title }: { data?: Relationships; loading: boolean; onShowAll?: () => void; title?: string }) {
  const { t } = useI18n();
  const facet = data?.facets.unknown_ip;
  const summary = data?.summary;
  const lb = (facet?.items || []).filter((row) => row.is_load_balancer).length;
  return (
    <div className="mt-3 space-y-3">
      {summary && (
        <KpiStrip items={[
          [t("Unknown requests", "Request chưa xác định"), n(summary.unknown_requests, 0)],
          [t("Share of traffic", "Tỷ lệ lưu lượng"), pct(summary.requests ? summary.unknown_requests / summary.requests : 0)],
          [t("Source IPs", "IP nguồn"), n(summary.unknown_ips, 0)],
          [t("Infrastructure IPs", "IP hạ tầng"), n(lb, 0), t("Load balancer / proxy", "Load balancer / proxy")],
        ]} />
      )}
      <RelTable
        facet="ip"
        title={title || t("Unknown users by source IP", "User chưa xác định theo IP nguồn")}
        subtitle={t("Requests that carried no identified credential", "Request không mang credential xác định")}
        result={facet}
        loading={loading}
        columns={["role", "tps", "requests", "error", "p95", "callers", "apis", "last"]}
        empty={t("No unauthenticated requests in this window", "Không có request chưa xác thực trong khoảng này")}
        onShowAll={onShowAll}
        footer={lb > 0 || (facet?.items || []).some((row) => row.name === "unknown") ? (
          <p className="border-t border-line px-3 py-2 text-[11px] text-muted">{t(
            "Load balancer, proxy and NAT addresses hide the real client. \"unknown\" means the request carried no source IP.",
            "Địa chỉ load balancer, proxy và NAT che IP client thật. \"unknown\" nghĩa là request không mang IP nguồn.",
          )}</p>
        ) : null}
      />
    </div>
  );
}

export function SharedIpsPanel({ data, loading, search }: { data?: Relationships; loading: boolean; search: string }) {
  const { t } = useI18n();
  const shared = data?.facets.shared;
  return (
    <Panel
      className="mt-3"
      title={t("Other identities on the same IPs", "Danh tính khác trên cùng IP")}
      subtitle={t("Users and unknown traffic seen from this user's source IPs (load balancers excluded)", "User và lưu lượng chưa xác định từ IP nguồn của user này (bỏ qua load balancer)")}
      action={<span className="font-mono text-[10px] text-muted">{shared ? n(shared.total, 0) : ""}</span>}
    >
      {loading && !shared ? <Loading /> : (
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full text-left text-xs">
            <thead><tr className="border-b border-line">
              {[t("Identity", "Danh tính"), t("Shared IPs", "IP chung"), t("Requests", "Request"), t("Sample IPs", "IP mẫu"), t("Last seen", "Lần cuối")].map((label, i) => <th key={label} className={`table-head sticky top-0 bg-surface px-2.5 py-2 ${i && i !== 3 ? "text-right" : ""}`}>{label}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-line">
              {(shared?.items || []).map((row: SharedRow) => (
                <tr key={row.name} className="hover:bg-hover">
                  <td className="px-2.5 py-1.5 font-mono">
                    {row.unknown ? <span className="text-warn">{t("Unknown users", "User chưa xác định")}</span>
                      : <Link to={`${workspacePath.user(row.name)}${search}`} className="text-entity-user hover:underline">{row.name}</Link>}
                  </td>
                  <td className="px-2.5 text-right font-mono tabular-nums text-ink">{n(row.shared_ips, 0)}</td>
                  <td className="px-2.5 text-right font-mono tabular-nums">{n(row.requests, 0)}</td>
                  <td className="max-w-[320px] truncate px-2.5 font-mono text-entity-ip" title={row.sample_ips.join(", ")}>{row.sample_ips.join(", ")}</td>
                  <td className="px-2.5 text-right text-muted">{shortTime(row.last_seen_ms)}</td>
                </tr>
              ))}
              {!shared?.items.length && <tr><td colSpan={5} className="px-3 py-6 text-center text-muted">{t("No other identity shares these IPs", "Không có danh tính khác dùng chung các IP này")}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <p className="border-t border-line px-3 py-2 text-[11px] text-muted">{t(
        "Pod and NAT addresses are shared by design; a shared IP is a lead to check in Traces, not proof of credential sharing.",
        "Địa chỉ pod và NAT vốn dùng chung; IP chung là manh mối để kiểm tra trong Trace, chưa phải bằng chứng chia sẻ credential.",
      )}</p>
    </Panel>
  );
}

export function TracesPanel({ params, openHref }: { params: Record<string, string>; openHref: string }) {
  const { t } = useI18n();
  const { filters } = useFilters();
  const qs = windowParams(filters);
  Object.entries(params).forEach(([key, value]) => qs.set(key, value));
  qs.set("limit", "15");
  const query = useQuery({ queryKey: ["ws-traces", qs.toString()], queryFn: () => api<{ items: any[] }>(`/api/v1/traces?${qs.toString()}`) });
  const traces = query.data?.items || [];
  return (
    <Panel
      className="mt-3"
      title={t("Recent traces", "Trace gần đây")}
      subtitle={t("Open a trace to confirm the exact request chain", "Mở Trace để xác nhận chuỗi request chính xác")}
      action={<Link to={openHref} className="text-[11px] font-semibold text-ink hover:underline">{t("Open in Traces", "Mở trong Traces")} <ArrowRight size={12} className="inline" /></Link>}
    >
      {query.isLoading ? <Loading /> : query.isError ? <ErrorState message={query.error.message} /> : (
        <div className="overflow-auto">
          <table className="w-full text-left text-xs">
            <thead><tr className="border-b border-line">
              {[t("Trace", "Trace"), "Service", "API", t("User", "User"), t("Duration", "Thời lượng"), t("Status", "Trạng thái")].map((label, i) => <th key={label} className={`table-head px-2.5 py-2 ${i > 3 ? "text-right" : ""}`}>{label}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-line">
              {traces.map((tr) => {
                const id = tr.trace_id || tr.id || "";
                const status = String(tr.status_code || tr.http_status || tr.status || "");
                return (
                  <tr key={id} className="hover:bg-hover">
                    <td className="px-2.5 py-1.5 font-mono"><Link to={`/traces/${encodeURIComponent(id)}`} className="text-ink hover:underline">{id.slice(0, 16)}…</Link></td>
                    <td className="px-2.5 font-mono text-entity-service">{tr.target_service || tr.service_name || tr.service || "—"}</td>
                    <td className="max-w-[260px] truncate px-2.5 font-mono text-entity-api">{tr.operation || tr.transaction_name || "—"}</td>
                    <td className="px-2.5 font-mono text-entity-user">{tr.principal_name || tr.user || "—"}</td>
                    <td className="px-2.5 text-right font-mono tabular-nums">{tr.duration_ms != null ? `${Number(tr.duration_ms).toFixed(1)} ms` : "—"}</td>
                    <td className={`px-2.5 text-right font-mono ${status.startsWith("5") ? "text-bad" : status.startsWith("4") ? "text-warn" : "text-good"}`}>{status || "—"}</td>
                  </tr>
                );
              })}
              {!traces.length && <tr><td colSpan={6} className="px-3 py-6 text-center text-muted">{t("No traces in this window", "Không có Trace trong khoảng này")}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: Array<[string, string, number | string | undefined]>; value: string; onChange: (value: string) => void }) {
  return (
    <div className="mt-5 flex flex-wrap gap-2 border-b border-line pb-2" role="tablist">
      {tabs.map(([id, label, count]) => (
        <button key={id} type="button" role="tab" aria-selected={value === id} onClick={() => onChange(id)}
          className={`rounded-ctl border px-3 py-1.5 text-xs ${value === id ? "border-accent bg-accent-soft font-semibold text-ink" : "border-line-strong text-muted hover:text-ink"}`}>
          {label}{count !== undefined && <span className="ml-2 font-mono">{count}</span>}
        </button>
      ))}
    </div>
  );
}
