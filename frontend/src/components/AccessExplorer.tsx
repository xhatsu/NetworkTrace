import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, ChevronDown, ChevronUp, RotateCcw, Search, X } from "lucide-react";
import { api } from "../api";
import { chartTooltip, ErrorState, Loading, n } from "../components";
import { useI18n } from "../i18n";
import { ENTITY_COLOR, STATE_STYLE, asState, ipRoleLabel, stateLabel, stateShortLabel, type AccessState } from "../accessEncoding";
import { EntityLink } from "./EntityLink";
import { relativeAge } from "./AccessFlow";

// Access for one Service, built for hundreds of credentials and APIs:
//   1. unusual access first (bot-like fan-out, surges, new and silenced paths),
//   2. three linked, searchable, server-paged lists (Caller | Credential | API),
//   3. one selected entity drawn with its direct neighbours using angled connectors.
// Nothing draws the full cross-product, so the card stays readable at any size.

export type ColumnKey = "caller" | "credential" | "service" | "api";
export type ExplorerFilters = { caller?: string; credential?: string; service?: string; api?: string };
type T = (en: string, vi?: string) => string;

type ListRow = {
  name: string; state: string; familiarity: string; width_tps: number; observed_tps: number; expected_tps: number | null;
  relationships: number; last_seen_ms: number; first_seen_ms: number; unusual: boolean;
};
type Column = { items: ListRow[]; total: number; offset: number; limit: number; max_tps: number };
type Unusual = {
  id: string; reason: "fanout" | "surge" | "flag" | "new" | "silent"; state: string;
  credential: string | null; caller: string | null; api: string | null; apis?: string[]; new_apis?: number; usual_apis?: number;
  observed_tps: number; expected_tps: number | null; first_seen_ms: number; last_seen_ms: number; flags: string[];
};
type Side = { column: ColumnKey; items: ListRow[]; total: number } | null;
type Selection = ListRow & {
  type: ColumnKey; left: Side; right: Side; detail_id: string; ip_total: number;
  ips: { ip: string; role: string; last_seen_ms: number; state: string; infrastructure: boolean }[];
};
type ListsResponse = {
  status: "active" | "learning"; as_of_ms?: number; relationships_total?: number;
  columns: Partial<Record<ColumnKey, Column>>; unusual: { items: Unusual[]; total: number }; selection: Selection | null;
};
type DetailResponse = { series: { timestamp_ms: number; tps: number; expected_tps: number | null }[] };

const COLUMNS: ColumnKey[] = ["caller", "credential", "api"];
const NO_SEARCH: Record<ColumnKey, string> = { caller: "", credential: "", service: "", api: "" };
const FIRST_PAGES: Record<ColumnKey, number> = { caller: 1, credential: 1, service: 1, api: 1 };
/** Learned API labels read "service → operation". */
const API_SEP = " → ";
export function splitApiLabel(label: string) {
  const i = label.indexOf(API_SEP);
  return i < 0 ? { service: "", operation: label } : { service: label.slice(0, i), operation: label.slice(i + API_SEP.length) };
}
const PAGE = 100;
const UNUSUAL_PREVIEW = 5;
const WINDOWS: [number, string][] = [[15, "15m"], [60, "1h"], [360, "6h"], [1440, "24h"]];
const ORANGE = "var(--warn)";

function useDebounced<V>(value: V, ms = 250) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => { const id = setTimeout(() => setDebounced(value), ms); return () => clearTimeout(id); }, [value, ms]);
  return debounced;
}

function Segmented<V extends string | number>({ label, value, options, onChange }: { label: string; value: V; options: [V, string][]; onChange: (value: V) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex h-7 overflow-hidden rounded-ctl border border-line">
      {options.map(([option, text], i) => (
        <button key={String(option)} type="button" aria-pressed={value === option} onClick={() => onChange(option)}
          className={`px-2.5 text-[11px] font-medium transition-colors ${i ? "border-l border-line" : ""} ${value === option ? "bg-surface-2 text-ink font-semibold" : "bg-surface text-muted hover:bg-hover hover:text-ink"}`}>
          {text}
        </button>
      ))}
    </div>
  );
}

function columnTitle(column: ColumnKey, t: T) {
  return column === "caller" ? "Caller Service" : column === "credential" ? t("User / credential", "User / credential") : column === "service" ? "Service" : "API";
}

function StateGlyph({ state, t }: { state: string; t: T }) {
  const s = STATE_STYLE[asState(state)];
  return (
    <span aria-label={stateLabel(t, asState(state))} title={stateLabel(t, asState(state))}
      className="inline-grid h-4 w-4 shrink-0 place-items-center text-[11px] font-bold" style={{ color: s.color }}>
      {s.glyph || "·"}
    </span>
  );
}

const FLAG_TEXT: Record<string, [string, string]> = {
  access_expansion: ["new access", "truy cập mới"],
  contract_violation: ["contract violation", "vi phạm hợp đồng"],
  traffic_surge: ["traffic surge", "lưu lượng tăng vọt"],
  graph_tps_shift: ["TPS shift", "TPS thay đổi"],
};

function reasonText(item: Unusual, asOf: number | undefined, t: T) {
  switch (item.reason) {
    case "fanout":
      return t(`reached ${item.new_apis} new APIs (usually ${item.usual_apis})`, `gọi ${item.new_apis} API mới (thường ${item.usual_apis})`);
    case "surge":
      return item.expected_tps
        ? t(`TPS ${n(item.observed_tps / item.expected_tps, 1)}× expected`, `TPS gấp ${n(item.observed_tps / item.expected_tps, 1)} lần kỳ vọng`)
        : t("TPS above its learned level", "TPS cao hơn mức đã học");
    case "flag":
      return item.flags.map(f => (FLAG_TEXT[f] ? t(...FLAG_TEXT[f]) : f)).join(", ") || t("flagged by learning", "bị gắn cờ khi học");
    case "new":
      return `${t("first seen", "thấy lần đầu")} ${relativeAge(item.first_seen_ms, asOf, t)}`;
    case "silent":
      return `${t("learned path silent since", "đường đã học im lặng từ")} ${relativeAge(item.last_seen_ms, asOf, t)}`;
  }
}

export function AccessExplorer({ service = "", filters: rawFilters, onFilters: rawOnFilters, environment = "", lockedApi, lockedCredential }: {
  /** The Service being explored; unused when `lockedCredential` explores one user across Services. */
  service?: string;
  filters: ExplorerFilters;
  onFilters: (next: ExplorerFilters) => void;
  environment?: string;
  /** Learned API label ("service → operation"): scopes every list to this one API and hides the API column. */
  lockedApi?: string;
  /** One user / credential across every Service: columns become Caller | Service | API. */
  lockedCredential?: string;
}) {
  const userScope = !!lockedCredential;
  const locked: Partial<Record<ColumnKey, string>> = lockedApi ? { api: lockedApi } : lockedCredential ? { credential: lockedCredential } : {};
  const filters: ExplorerFilters = { ...rawFilters, ...locked };
  const onFilters = (next: ExplorerFilters) => {
    const rest = { ...next };
    (Object.keys(locked) as ColumnKey[]).forEach(c => { delete rest[c]; });
    rawOnFilters(rest);
  };
  const isLocked = (column: ColumnKey) => column in locked;
  const columns: ColumnKey[] = lockedApi ? ["caller", "credential"] : userScope ? ["caller", "service", "api"] : COLUMNS;
  const lockedFocus = lockedApi ? { type: "api" as ColumnKey, name: lockedApi } : lockedCredential ? { type: "credential" as ColumnKey, name: lockedCredential } : null;
  const { lang } = useI18n();
  const t: T = (en, vi) => (lang === "vi" && vi ? vi : en);
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [basis, setBasis] = useState<"observed" | "baseline">("observed");
  const [sort, setSort] = useState<"tps" | "name">("tps");
  const [search, setSearch] = useState<Record<ColumnKey, string>>(NO_SEARCH);
  const [pages, setPages] = useState<Record<ColumnKey, number>>(FIRST_PAGES);
  const [selected, setSelected] = useState<{ type: ColumnKey; name: string } | null>(null);
  const [allUnusual, setAllUnusual] = useState(false);
  const q = useDebounced(search);
  // API labels drop their Service prefix when the Service is already known (Service page, or a chosen Service).
  const knownService = userScope ? filters.service || "" : service;
  const apiPrefix = knownService ? `${knownService}${API_SEP}` : "";
  const shortApi = (label: string | null | undefined) => (label ? (apiPrefix && label.startsWith(apiPrefix) ? label.slice(apiPrefix.length) : label) : "");
  const display = (column: ColumnKey, name: string) => (column === "api" ? shortApi(name) : name);

  // A changed scope invalidates extra pages.
  const scopeKey = JSON.stringify([service, filters.caller, filters.credential, filters.service, filters.api, q, sort, windowMinutes, basis, environment]);
  useEffect(() => { setPages(FIRST_PAGES); }, [scopeKey]);
  // The selection follows its filter: clearing a filter elsewhere clears a selection that depended on it.
  useEffect(() => {
    if (selected && filters[selected.type] !== selected.name) setSelected(null);
  }, [filters, selected]);

  const params = (extra: Record<string, string> = {}) => {
    const p = new URLSearchParams({ view: "lists", window_minutes: String(windowMinutes), basis, sort, limit: String(PAGE), ...extra });
    if (userScope) p.set("scope", "credential"); else p.set("service", service);
    if (environment) p.set("environment", environment);
    (["caller", "credential", "service", "api"] as ColumnKey[]).forEach(c => {
      if (c === "service" && !userScope) return;
      if (filters[c]) p.set(c, filters[c]!);
      if (q[c]) p.set(`q_${c}`, q[c]);
    });
    return p;
  };
  // On a locked API page the API itself is the default selection, so its callers and users are drawn at once.
  const focus = selected ?? lockedFocus;
  const main = params(focus ? { select_type: focus.type, select: focus.name } : {});
  const query = useQuery({
    queryKey: ["access-lists", main.toString()],
    queryFn: ({ signal }) => api<ListsResponse>(`/api/v1/behavior/access?${main}`, { signal }),
    enabled: !!service || userScope,
    placeholderData: previous => previous,
    refetchInterval: 60000,
  });
  const data = query.data;

  // Pages after the first are fetched per column on demand.
  const extra = columns.flatMap(c => Array.from({ length: pages[c] - 1 }, (_, i) => ({ c, offset: (i + 1) * PAGE })));
  const extraQueries = useQueries({
    queries: extra.map(({ c, offset }) => {
      const p = params({ [`${c}_offset`]: String(offset) });
      return { queryKey: ["access-lists", p.toString(), c], queryFn: ({ signal }: { signal: AbortSignal }) => api<ListsResponse>(`/api/v1/behavior/access?${p}`, { signal }) };
    }),
  });
  const rowsFor = (c: ColumnKey) => {
    const first = data?.columns[c]?.items || [];
    const more = extra.flatMap((e, i) => (e.c === c ? extraQueries[i]?.data?.columns[c]?.items || [] : []));
    return [...first, ...more];
  };
  const loadingMore = (c: ColumnKey) => extra.some((e, i) => e.c === c && extraQueries[i]?.isLoading);

  const toggleRow = (column: ColumnKey, name: string) => {
    if (isLocked(column)) { setSelected(null); return; }
    const next = { ...filters };
    if (next[column] === name) {
      delete next[column];
      if (selected?.type === column && selected.name === name) setSelected(null);
    } else {
      next[column] = name;
      setSelected({ type: column, name });
    }
    onFilters(next);
  };
  const openUnusual = (item: Unusual) => {
    const next: ExplorerFilters = {};
    if (item.credential) next.credential = item.credential;
    if (item.api) next.api = item.api;
    if (!item.credential && item.caller) next.caller = item.caller;
    onFilters(next);
    const type: ColumnKey = item.credential && !userScope ? "credential" : item.api ? "api" : item.caller ? "caller" : "credential";
    setSelected({ type, name: (next[type] as string) || "" });
  };
  const reset = () => { onFilters({}); setSelected(null); setSearch(NO_SEARCH); };
  const hasScope = columns.some(c => filters[c] || search[c]);
  const stale = query.isFetching && query.isPlaceholderData;

  if (query.isLoading) return <div className="py-10"><Loading /></div>;
  if (query.isError) return <div className="p-3"><ErrorState message={(query.error as Error).message} /><button className="btn mt-2" onClick={() => query.refetch()}>{t("Retry", "Thử lại")}</button></div>;
  if (!data || data.status !== "active") return <p className="py-10 text-center text-xs text-muted">{t("The learned graph is still building; no relationships to show yet.", "Đồ thị học đang được xây dựng; chưa có quan hệ để hiển thị.")}</p>;

  const unusual = data.unusual.items;
  const shownUnusual = allUnusual ? unusual : unusual.slice(0, UNUSUAL_PREVIEW);

  return (
    <div data-testid="access-explorer" className="text-muted" style={{ opacity: stale ? 0.7 : 1, transition: "opacity 120ms" }}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2">
        <Segmented label={t("Current window", "Cửa sổ hiện tại")} value={windowMinutes} onChange={setWindowMinutes} options={WINDOWS} />
        <Segmented label={t("Volume", "Lưu lượng")} value={basis} onChange={setBasis}
          options={[["observed", t("Observed TPS", "TPS quan sát")], ["baseline", t("Learned baseline", "Baseline đã học")]]} />
        <Segmented label={t("Sort", "Sắp xếp")} value={sort} onChange={setSort} options={[["tps", t("By TPS", "Theo TPS")], ["name", "A–Z"]]} />
        {hasScope && (
          <button type="button" onClick={reset} className="inline-flex h-7 items-center gap-1 rounded-ctl px-2 text-[11px] text-warn hover:bg-warn-bg">
            <RotateCcw size={12} aria-hidden="true" /> {t("Reset", "Đặt lại")}
          </button>
        )}
        <span className="ml-auto text-[11px] text-muted">
          <span className="font-mono text-ink">{data.relationships_total ?? 0}</span> {t("learned relationships", "quan hệ đã học")}
          {data.as_of_ms ? <> · {t("through", "đến")} {new Date(data.as_of_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</> : null}
        </span>
      </div>

      {/* 1. Unusual now */}
      <section data-testid="access-unusual" className="border-b border-line px-3 py-2">
        <div className="mb-1 flex items-center gap-2">
          <AlertTriangle size={13} className={unusual.length ? "text-warn" : "text-faint"} aria-hidden="true" />
          <h3 className="text-[11px] font-semibold uppercase tracking-[.08em] text-ink">{t("Unusual now", "Bất thường hiện tại")}</h3>
          <span className="font-mono text-[11px] text-muted">{data.unusual.total}</span>
          {unusual.length > UNUSUAL_PREVIEW && (
            <button type="button" onClick={() => setAllUnusual(v => !v)} className="ml-auto inline-flex items-center gap-1 text-[11px] text-accent hover:underline">
              {allUnusual ? <>{t("Show fewer", "Thu gọn")} <ChevronUp size={12} /></> : <>{t(`Show all ${unusual.length}`, `Xem tất cả ${unusual.length}`)} <ChevronDown size={12} /></>}
            </button>
          )}
        </div>
        {!unusual.length ? (
          <p className="text-[12px] text-muted">{t("No unusual access in this window. Usual traffic is in the lists below.", "Không có truy cập bất thường trong cửa sổ này. Traffic bình thường ở các danh sách bên dưới.")}</p>
        ) : (
          <ul className={`divide-y divide-line ${allUnusual ? "max-h-[260px] overflow-y-auto" : ""}`}>
            {shownUnusual.map(item => {
              const style = STATE_STYLE[asState(item.state)];
              const path = item.reason === "fanout"
                ? [item.credential, t(`${item.new_apis} new APIs`, `${item.new_apis} API mới`)]
                : [item.caller, item.credential, shortApi(item.api)];
              return (
                <li key={item.id}>
                  <button type="button" onClick={() => openUnusual(item)} title={item.apis?.map(shortApi).join("\n")}
                    className="grid w-full grid-cols-[18px_minmax(0,1.4fr)_minmax(0,1fr)_auto] items-center gap-2 px-1 py-1.5 text-left text-[12px] hover:bg-hover">
                    <span className="text-center font-bold" style={{ color: style.color }}>{item.reason === "silent" ? "○" : item.reason === "new" ? "+" : "!"}</span>
                    <span className="truncate font-mono text-ink">{path.filter(Boolean).join("  →  ")}</span>
                    <span className="truncate text-muted">{reasonText(item, data.as_of_ms, t)}</span>
                    <span className="whitespace-nowrap font-mono text-[11px] text-muted">
                      {n(item.observed_tps, 3)} TPS{item.expected_tps != null ? ` / ${t("exp", "kv")} ${n(item.expected_tps, 3)}` : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* 2. Linked lists */}
      <div className={`grid gap-2 p-2 ${columns.length === 3 ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
        {columns.map(column => {
          const col = data.columns[column] || { items: [], total: 0, offset: 0, limit: PAGE, max_tps: 0 };
          const rows = rowsFor(column);
          const max = col.max_tps || Math.max(0, ...rows.map(r => r.width_tps)) || 1;
          return (
            <section key={column} data-testid={`access-col-${column}`} className="flex min-w-0 flex-col border border-line bg-surface">
              <header className="flex items-center gap-2 border-b border-line px-2.5 py-2">
                <span className="h-2 w-2 rounded-[1px]" style={{ background: ENTITY_COLOR[column] }} aria-hidden="true" />
                <h3 className="text-[11px] font-semibold uppercase tracking-[.08em] text-ink">{columnTitle(column, t)}</h3>
                <span className="ml-auto font-mono text-[11px] text-muted">{col.total}</span>
              </header>
              <label className="relative block border-b border-line p-1.5">
                <Search size={12} aria-hidden="true" className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-faint" />
                <input value={search[column]} onChange={e => setSearch(s => ({ ...s, [column]: e.target.value }))}
                  placeholder={t(`Find ${column === "credential" ? "user" : column === "api" ? "API" : column === "service" ? "Service" : "caller"}…`, "Tìm…")}
                  aria-label={t(`Find in ${columnTitle(column, t)}`, `Tìm trong ${columnTitle(column, t)}`)}
                  className="h-7 w-full rounded-ctl border border-line bg-surface pl-6 pr-6 text-[11px] text-ink placeholder:text-faint" />
                {search[column] && <button type="button" aria-label={t("Clear", "Xoá")} onClick={() => setSearch(s => ({ ...s, [column]: "" }))} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-ink"><X size={12} /></button>}
              </label>
              <ul className="max-h-[340px] min-h-[120px] overflow-y-auto p-1" role="listbox" aria-label={columnTitle(column, t)}>
                {rows.map(row => {
                  const active = filters[column] === row.name;
                  const style = STATE_STYLE[asState(row.state)];
                  return (
                    <li key={row.name}>
                      <button type="button" role="option" aria-selected={active} onClick={() => toggleRow(column, row.name)} title={`${row.name} · ${stateLabel(t, asState(row.state))}`}
                        className={`grid w-full grid-cols-[16px_minmax(0,1fr)_56px_64px] items-center gap-1.5 rounded-ctl border px-1.5 py-1 text-left text-[12px] ${active ? "bg-accent-soft border-line" : "border-transparent hover:bg-hover"}`}
                        style={{ borderColor: active ? ENTITY_COLOR[column] : undefined, boxShadow: row.unusual && !active ? `inset 2px 0 0 ${ORANGE}` : undefined }}>
                        <StateGlyph state={row.state} t={t} />
                        <span className={`truncate font-mono ${row.state === "ghost" ? "text-faint" : "text-ink"}`}>{display(column, row.name)}</span>
                        <span className="h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
                          <span className="block h-full rounded-full" style={{ width: `${Math.max(3, (row.width_tps / max) * 100)}%`, background: row.unusual ? ORANGE : style.color, opacity: row.state === "ghost" ? 0.4 : 0.85 }} />
                        </span>
                        <span className="text-right font-mono text-[11px] tabular-nums text-muted">{n(row.width_tps, 3)}</span>
                      </button>
                    </li>
                  );
                })}
                {!rows.length && <li className="px-2 py-6 text-center text-[11px] text-muted">{t("Nothing matches", "Không có mục phù hợp")}</li>}
              </ul>
              {rows.length < col.total && (
                <button type="button" disabled={loadingMore(column)} onClick={() => setPages(p => ({ ...p, [column]: p[column] + 1 }))}
                  className="border-t border-line py-1.5 text-[11px] text-accent hover:bg-hover disabled:opacity-50">
                  {loadingMore(column) ? t("Loading…", "Đang tải…") : t(`Show ${Math.min(PAGE, col.total - rows.length)} more of ${col.total - rows.length}`, `Hiện thêm ${Math.min(PAGE, col.total - rows.length)} / ${col.total - rows.length}`)}
                </button>
              )}
            </section>
          );
        })}
      </div>
      <p className="px-3 pb-2 text-[11px] text-muted">
        {t("Click a row to filter the other lists and open it below; click again to clear. Bars and numbers are TPS. Orange marks rows that appear in Unusual now.",
          "Bấm một dòng để lọc các danh sách khác và mở chi tiết bên dưới; bấm lần nữa để bỏ. Thanh và số là TPS. Màu cam đánh dấu dòng có trong Bất thường hiện tại.")}
      </p>

      {/* 3. Selected entity */}
      {data.selection && <SelectionPanel selection={data.selection} environment={environment} asOf={data.as_of_ms} display={display}
        onPick={toggleRow} t={t} isPage={!!lockedFocus && data.selection.type === lockedFocus.type}
        onClose={() => { setSelected(null); const next = { ...filters }; delete next[data.selection!.type]; onFilters(next); }} />}
    </div>
  );
}

// What each fan means for the selected kind; sides are not always in chain order, so they are labelled.
function sideTitle(selected: ColumnKey, column: ColumnKey, t: T) {
  if (column === "service") return t("Services it reaches", "Service nó gọi tới");
  if (selected === "caller") return column === "credential" ? t("Users it sends", "User nó gửi") : t("APIs it reaches", "API nó gọi tới");
  if (selected === "credential") return column === "caller" ? t("Sent by", "Được gửi bởi") : t("APIs it reaches", "API nó gọi tới");
  if (selected === "service") return column === "caller" ? t("Called by", "Được gọi bởi") : t("APIs used", "API đã dùng");
  return column === "caller" ? t("Called by", "Được gọi bởi") : t("Users used", "User đã dùng");
}

const ROW_H = 30;
const BOX_H = 24;

/** Angled tree: left neighbours → selected entity → right neighbours, elbow connectors sized by TPS. */
function NeighbourDiagram({ selection, display, onPick, t }: {
  selection: Selection; display: (c: ColumnKey, name: string) => string; onPick: (c: ColumnKey, name: string) => void; t: T;
}) {
  const [width, setWidth] = useState(0);
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!node) return;
    const observer = new ResizeObserver(entries => setWidth(Math.floor(entries[0].contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  const left = selection.left?.items || [];
  const right = selection.right?.items || [];
  const moreL = (selection.left?.total || 0) - left.length;
  const moreR = (selection.right?.total || 0) - right.length;
  const rows = Math.max(left.length + (moreL > 0 ? 1 : 0), right.length + (moreR > 0 ? 1 : 0), 1);
  const height = rows * ROW_H + 8;
  const max = Math.max(selection.width_tps, ...left.map(r => r.width_tps), ...right.map(r => r.width_tps), 1e-9);
  const sideW = Math.max(120, Math.floor(width * 0.3));
  const centerW = Math.max(110, Math.floor(width * 0.22));
  const centerX = Math.floor((width - centerW) / 2);
  const cy = height / 2;
  const trunkL = Math.floor((sideW + centerX) / 2);
  const trunkR = Math.floor((centerX + centerW + (width - sideW)) / 2);
  const rowY = (i: number, count: number) => cy - ((count - 1) * ROW_H) / 2 + i * ROW_H;
  const stroke = (r: ListRow) => 1.5 + 4.5 * Math.sqrt(r.width_tps / max);
  const chars = (w: number) => Math.max(6, Math.floor((w - 70) / 6.6));
  const clip = (s: string, m: number) => (s.length > m ? `${s.slice(0, m - 1)}…` : s);
  const entityColor = ENTITY_COLOR[selection.type];

  const side = (items: ListRow[], more: number, column: ColumnKey | undefined, where: "left" | "right") => {
    if (!column) return null;
    const count = items.length + (more > 0 ? 1 : 0);
    const x = where === "left" ? 0 : width - sideW;
    const edgeX = where === "left" ? sideW : width - sideW;
    const trunk = where === "left" ? trunkL : trunkR;
    const joinX = where === "left" ? centerX : centerX + centerW;
    return (
      <g>
        {/* Silent lines first so solid ones stay on top where they share the trunk. */}
        {items.map((r, i) => ({ r, i })).sort((a, b) => Number(b.r.state === "ghost") - Number(a.r.state === "ghost")).map(({ r, i }) => {
          const y = rowY(i, count);
          const s = STATE_STYLE[asState(r.state)];
          return (
            <polyline key={`l-${r.name}`} points={`${edgeX},${y} ${trunk},${y} ${trunk},${cy}`} fill="none"
              stroke={s.color} strokeOpacity={r.state === "ghost" ? 0.5 : 0.8} strokeWidth={stroke(r)} strokeDasharray={r.state === "ghost" ? "2 4" : r.state === "new" ? "5 3" : undefined}
              strokeLinejoin="miter" />
          );
        })}
        {/* The join into the selected box is shared by every line on this side: draw it once. */}
        {items.length > 0 && (
          <line x1={trunk} x2={joinX} y1={cy} y2={cy} stroke={items.some(r => r.state === "new" || r.state === "deviating") ? ORANGE : items.every(r => r.state === "ghost") ? "var(--muted)" : "var(--info)"}
            strokeOpacity="0.85" strokeWidth={Math.max(...items.map(stroke)) + 1} strokeDasharray={items.every(r => r.state === "ghost") ? "2 4" : undefined} />
        )}
        {items.map((r, i) => {
          const y = rowY(i, count);
          const s = STATE_STYLE[asState(r.state)];
          return (
            <g key={`b-${r.name}`} role="button" tabIndex={0} className="cursor-pointer outline-none" onClick={() => onPick(column, r.name)}
              onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(column, r.name); } }}
              aria-label={`${display(column, r.name)}, ${stateLabel(t, asState(r.state))}, ${n(r.width_tps, 3)} TPS`}>
              <rect x={x} y={y - BOX_H / 2} width={sideW} height={BOX_H} rx="2" fill="var(--surface)" stroke="var(--border-strong)" />
              <rect x={where === "left" ? x : x + sideW - 3} y={y - BOX_H / 2} width="3" height={BOX_H} fill={ENTITY_COLOR[column]} />
              <text x={x + 9} y={y + 4} fontSize="11.5" fontFamily="ui-monospace, SFMono-Regular, monospace" fill={r.state === "ghost" ? "var(--faint)" : "var(--text)"}>
                {s.glyph && <tspan fill={s.color} fontWeight="700">{s.glyph} </tspan>}{clip(display(column, r.name), chars(sideW))}
              </text>
              <text x={x + sideW - 9} y={y + 4} textAnchor="end" fontSize="10" fill="var(--muted)">{n(r.width_tps, 3)}</text>
              <title>{`${r.name} — ${stateLabel(t, asState(r.state))}`}</title>
            </g>
          );
        })}
        {more > 0 && (
          <text x={x + 9} y={rowY(count - 1, count) + 4} fontSize="11" fill="var(--muted)">{t(`+${more} more (use the list above)`, `+${more} mục khác (xem danh sách trên)`)}</text>
        )}
      </g>
    );
  };

  return (
    <div ref={setNode} className="min-w-0" data-testid="access-neighbours">
      {width > 0 && (
        <div className="mb-1 flex text-[10px] font-semibold uppercase tracking-[.08em] text-muted" aria-hidden="true">
          {[selection.left, selection.right].map((side, i) => side ? (
            <span key={i} data-testid="access-side-title" className={i ? "ml-auto text-right" : ""} style={{ width: sideW }}>
              {sideTitle(selection.type, side.column, t)} <span className="font-mono font-normal">{side.total}</span>
            </span>
          ) : <span key={i} style={{ width: sideW }} />)}
        </div>
      )}
      {width > 0 && (
        <svg width={width} height={height} className="block" role="group" aria-label={t(`Direct relationships of ${selection.name}`, `Quan hệ trực tiếp của ${selection.name}`)}>
          {side(left, moreL, selection.left?.column, "left")}
          {side(right, moreR, selection.right?.column, "right")}
          <rect x={centerX} y={cy - 17} width={centerW} height={34} rx="2" fill="var(--surface)" stroke={entityColor} strokeWidth="1.5" />
          <text x={centerX + centerW / 2} y={cy - 2} textAnchor="middle" fontSize="12" fontWeight="600" fontFamily="ui-monospace, SFMono-Regular, monospace" fill="var(--text)">
            {clip(display(selection.type, selection.name), chars(centerW + 50))}
          </text>
          <text x={centerX + centerW / 2} y={cy + 12} textAnchor="middle" fontSize="10" fill="var(--muted)">{n(selection.width_tps, 3)} TPS</text>
        </svg>
      )}
    </div>
  );
}

function SelectionPanel({ selection, environment, asOf, display, onPick, onClose, t, isPage = false }: {
  selection: Selection; environment: string; asOf?: number; display: (c: ColumnKey, name: string) => string;
  onPick: (c: ColumnKey, name: string) => void; onClose: () => void; t: T;
  /** The selection is the page's own entity: no link to itself and nothing to close. */
  isPage?: boolean;
}) {
  const state = asState(selection.state) as AccessState;
  const style = STATE_STYLE[state];
  const detail = useQuery({
    queryKey: ["access-lists-detail", selection.detail_id, environment],
    queryFn: ({ signal }) => api<DetailResponse>(`/api/v1/behavior/topology/detail?object_id=${selection.detail_id}&environment=${encodeURIComponent(environment)}`, { signal }),
    enabled: !!selection.detail_id,
    retry: false,
  });
  const apiRef = selection.type === "api" ? splitApiLabel(selection.name) : null;
  return (
    <section data-testid="access-selection" className="mx-2 mb-2 border border-line bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted">{t("Selected", "Đang chọn")} · {columnTitle(selection.type, t)}</span>
        <span className="truncate font-mono text-[13px] text-ink" title={selection.name}>{display(selection.type, selection.name)}</span>
        <span className="inline-flex items-center gap-1 rounded-ctl border px-1.5 py-px text-[11px]" style={{ borderColor: `${style.color}66`, color: style.color }}>
          {style.glyph && <b aria-hidden="true">{style.glyph}</b>}{stateShortLabel(t, state)}
        </span>
        <span className="ml-auto flex items-center gap-3 text-[12px]">
          {selection.type === "credential" && !isPage && <EntityLink entity={{ kind: "user", principal: selection.name }}>{t("Open user", "Mở user")} →</EntityLink>}
          {apiRef && !isPage && <EntityLink entity={{ kind: "api", service: apiRef.service, operation: apiRef.operation }}>{t("Open API", "Mở API")} →</EntityLink>}
          {(selection.type === "caller" || selection.type === "service") && <EntityLink entity={{ kind: "service", name: selection.name }}>{t("Open Service", "Mở Service")} →</EntityLink>}
          {!isPage && <button type="button" onClick={onClose} aria-label={t("Clear selection", "Bỏ chọn")} className="text-muted hover:text-ink"><X size={14} /></button>}
        </span>
      </header>
      <div className="overflow-x-auto p-3"><div className="min-w-[560px]"><NeighbourDiagram selection={selection} display={display} onPick={onPick} t={t} /></div></div>
      <div className="grid gap-3 border-t border-line p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[.08em] text-muted">{t("TPS vs expected", "TPS so với kỳ vọng")}</div>
          <dl className="mb-2 grid grid-cols-3 gap-2 text-[12px]">
            <div><dt className="text-[10px] uppercase text-muted">{t("Observed", "Quan sát")}</dt><dd className="font-mono text-ink">{n(selection.observed_tps, 4)}</dd></div>
            <div><dt className="text-[10px] uppercase text-muted">{t("Expected", "Kỳ vọng")}</dt><dd className="font-mono text-ink">{selection.expected_tps != null ? n(selection.expected_tps, 4) : "—"}</dd></div>
            <div><dt className="text-[10px] uppercase text-muted">{t("Last seen", "Lần cuối")}</dt><dd className="text-ink">{relativeAge(selection.last_seen_ms, asOf, t)}</dd></div>
          </dl>
          {detail.isLoading ? <Loading /> : detail.data?.series.length ? (
            <div className="h-[90px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={detail.data.series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} hide />
                  <YAxis width={36} tick={{ fontSize: 10, fill: "var(--muted)" }} tickLine={false} axisLine={false} tickFormatter={v => n(Number(v), 2)} />
                  <Tooltip {...chartTooltip} labelFormatter={v => new Date(Number(v)).toLocaleString()} formatter={(value: unknown, name: unknown) => [`${n(Number(value), 4)} TPS`, String(name)]} />
                  <Line dataKey="expected_tps" name={t("Expected", "Kỳ vọng")} stroke="var(--series-2)" strokeDasharray="4 4" strokeWidth={1.25} dot={false} isAnimationActive={false} connectNulls />
                  <Line dataKey="tps" name={t("Observed", "Quan sát")} stroke="var(--series-1)" strokeWidth={1.25} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <p className="text-[12px] text-muted">{t("No retained series for this item.", "Không còn chuỗi dữ liệu cho mục này.")}</p>}
        </div>
        <div className="min-w-0">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[.08em] text-muted">{t("Peer IP evidence", "Bằng chứng IP peer")} <span className="font-mono">{selection.ip_total}</span></div>
          {selection.ips.length ? (
            <ul className="flex flex-wrap gap-1">
              {selection.ips.map(ip => (
                <li key={ip.ip} title={ip.infrastructure ? t("Infrastructure peer: not the origin", "Peer hạ tầng: không phải nguồn") : undefined}
                  className={`rounded-ctl border border-line-strong px-1.5 py-0.5 font-mono text-[11px] ${ip.state === "ghost" ? "text-faint" : "text-ink"}`}>
                  {ip.ip} <span className="font-sans text-muted">{ipRoleLabel(t, ip.role)}{ip.infrastructure ? " ⚑" : ""}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-[12px] text-muted">{t("No peer IP recorded.", "Không có IP peer.")}</p>}
        </div>
      </div>
    </section>
  );
}
