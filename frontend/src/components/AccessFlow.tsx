import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RotateCcw, Search, Table2, X } from "lucide-react";
import { api } from "../api";
import { chartTooltip, ErrorState, Loading, n } from "../components";
import { useI18n } from "../i18n";
import {
  ENTITY_COLOR, STATE_ORDER, STATE_STYLE, asState, ipRoleLabel, stateLabel, stateShortLabel,
  getStateStyle, getEntityColor,
  type AccessColumn, type AccessFlowResponse, type AccessNode, type AccessState,
} from "../accessEncoding";
import { BAR_W, HEADER_H, layoutFlow, type PlacedLink, type PlacedNode } from "../accessLayout";
import { EntityLink } from "./EntityLink";

export type FlowFilters = { service?: string; api?: string; credential?: string; caller?: string; ip?: string };
export type FocusType = "service" | "api" | "credential" | "caller" | "ip";
type T = (en: string, vi?: string) => string;

type DetailResponse = {
  series: { timestamp_ms: number; tps: number; expected_tps: number | null }[];
};

const WINDOWS: [number, string][] = [[15, "15m"], [60, "1h"], [360, "6h"], [1440, "24h"]];
const TOPS = [6, 12, 20, 30, 50];
const SURFACE = "var(--surface)";
const TEXT = "var(--text)";
const MUTED_TEXT = "var(--muted)";
const TIP_W = 260;
const SIMPLIFY_BAND_AT = 12;       // above this many ribbons between two columns, the band is simplified by default
const MUTED_RIBBON = "var(--border-strong)";
const TIP_GAP = 10;
const BODY_MAX_H = 560;            // taller flows scroll inside the card under sticky column titles
const NAME_CHAR_W = 6.9;           // monospace 11.5px
const METRIC_CHAR_W = 5.6;         // 10px

export function relativeAge(fromMs: number, toMs: number | undefined, t: T) {
  if (!fromMs) return "—";
  const minutes = Math.max(0, Math.round(((toMs ?? Date.now()) - fromMs) / 60000));
  if (minutes < 1) return t("in latest window", "trong cửa sổ mới nhất");
  if (minutes < 90) return t(`${minutes} min before latest window`, `${minutes} phút trước cửa sổ mới nhất`);
  if (minutes < 2880) return t(`${Math.round(minutes / 60)} h before latest window`, `${Math.round(minutes / 60)} giờ trước cửa sổ mới nhất`);
  return t(`${Math.round(minutes / 1440)} d before latest window`, `${Math.round(minutes / 1440)} ngày trước cửa sổ mới nhất`);
}

function Swatch({ state }: { state: AccessState }) {
  const s = getStateStyle(state);
  return (
    <svg width="22" height="10" aria-hidden="true" className="shrink-0">
      <rect x="1" y="1" width="20" height="8" rx="1" fill={s.color} fillOpacity={Math.max(s.fillOpacity, 0.05)}
        stroke={s.color} strokeOpacity={s.strokeOpacity} strokeDasharray={s.dash} />
    </svg>
  );
}

/** Legend chips. With `onToggle`, a chip emphasises ribbons in that state. */
export function StateLegend({ active, onToggle }: { active?: AccessState | null; onToggle?: (state: AccessState) => void }) {
  const { lang } = useI18n();
  const t = (en: string, vi?: string) => (lang === "vi" && vi ? vi : en);
  return (
    <ul className="flex flex-wrap items-center gap-1" aria-label={t("Legend", "Chú giải")}>
      {STATE_ORDER.map(state => {
        const s = getStateStyle(state);
        const content = (
          <>
            <Swatch state={state} />
            <span>{s.glyph && <b aria-hidden="true" className="mr-0.5">{s.glyph}</b>}{stateShortLabel(t, state)}</span>
          </>
        );
        const base = "inline-flex h-6 items-center gap-1.5 rounded-ctl border px-1.5 text-[11px]";
        return (
          <li key={state}>
            {onToggle ? (
              <button type="button" aria-pressed={active === state} title={stateLabel(t, state)} onClick={() => onToggle(state)}
                className={`${base} ${active === state ? "border-accent bg-accent-soft text-ink font-semibold" : "border-transparent text-muted hover:border-line hover:text-ink"}`}>
                {content}
              </button>
            ) : <span className={`${base} border-transparent text-muted`} title={stateLabel(t, state)}>{content}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function Segmented<V extends string | number>({ label, value, options, onChange }: { label: string; value: V; options: [V, string][]; onChange: (value: V) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex h-7 overflow-hidden rounded-ctl border border-line bg-surface">
      {options.map(([option, text], i) => (
        <button key={String(option)} type="button" aria-pressed={value === option} onClick={() => onChange(option)}
          className={`px-2.5 text-[11px] font-medium transition-colors ${i ? "border-l border-line" : ""} ${value === option ? "bg-surface-2 text-accent font-semibold" : "bg-surface text-muted hover:bg-hover hover:text-ink"}`}>
          {text}
        </button>
      ))}
    </div>
  );
}

function ToolLabel({ children }: { children: ReactNode }) {
  return <span className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted">{children}</span>;
}

function columnTitle(kind: AccessColumn, t: T) {
  switch (kind) {
    case "caller": return "Caller Service";
    case "credential": return t("Credential", "Credential");
    case "service": return "Service";
    case "api": return "API";
    case "ip": return t("Peer IP", "IP peer");
  }
}

function clip(text: string, max: number) {
  return text.length > max ? `${text.slice(0, Math.max(1, max - 1))}…` : text;
}

function splitApi(label: string): [string, string] {
  const at = label.indexOf(" → ");
  return at < 0 ? ["", label] : [label.slice(0, at), label.slice(at + 3)];
}

function useWidth<E extends HTMLElement>() {
  const ref = useRef<E>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(entries => setWidth(Math.floor(entries[0].contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function AccessFlow({
  focusType, focus, filters = {}, onFilters, environment = "", defaultTop = 12,
}: {
  focusType: FocusType;
  focus: string;
  filters?: FlowFilters;
  onFilters?: (next: FlowFilters) => void;
  environment?: string;
  defaultTop?: number;
}) {
  const { lang } = useI18n();
  const t = (en: string, vi?: string) => (lang === "vi" && vi ? vi : en);
  const [basis, setBasis] = useState<"observed" | "baseline">("observed");
  const [top, setTop] = useState(defaultTop);
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [ipRole, setIpRole] = useState("");
  const [ipOffset, setIpOffset] = useState(0);
  // Hovered item plus its on-screen anchor, so the info box can float beside it outside the chart.
  const [hovered, setHoveredState] = useState<{ id: string; barLeft: number; itemRight: number; midY: number } | null>(null);
  const setHovered = (value: null) => setHoveredState(value);
  const [selected, setSelected] = useState<(PlacedLink & { title?: string }) | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [emphasis, setEmphasis] = useState<AccessState | null>(null);
  const [find, setFind] = useState("");
  const [linkMode, setLinkMode] = useState<"auto" | "simple" | "all">("auto");
  const keyboardFocus = useRef(false);
  const [localFilters, setLocalFilters] = useState<FlowFilters>({});
  const [chartRef, chartWidth] = useWidth<HTMLDivElement>();
  const active = onFilters ? filters : localFilters;
  const setActive = (next: FlowFilters) => (onFilters ? onFilters(next) : setLocalFilters(next));

  const params = new URLSearchParams({
    view: "flow", focus_type: focusType, focus, top: String(top), basis, window_minutes: String(windowMinutes),
  });
  if (environment) params.set("environment", environment);
  (Object.entries(active) as [string, string | undefined][]).forEach(([key, value]) => {
    if (value && key !== focusType) params.set(key, value);
  });
  if (ipRole) { params.set("ip_role", ipRole); params.set("ip_offset", String(ipOffset)); params.set("ip_limit", "12"); }

  const query = useQuery({
    queryKey: ["access-flow", params.toString()],
    queryFn: ({ signal }) => api<AccessFlowResponse>(`/api/v1/behavior/access?${params}`, { signal }),
    enabled: !!focus,
    placeholderData: previous => previous,
    refetchInterval: 60000,
  });
  const data = query.data;
  const layout = useMemo(() => (data && chartWidth ? layoutFlow(data.nodes, data.links, chartWidth) : null), [data, chartWidth]);
  const nodeById = useMemo(() => new Map((layout?.nodes || []).map(node => [node.id, node])), [layout]);
  const linkById = useMemo(() => new Map((layout?.links || []).map(link => [link.id, link])), [layout]);
  const apiServices = useMemo(() => new Set((data?.nodes || []).filter(node => node.kind === "api" && !node.other).map(node => splitApi(node.label)[0])), [data]);

  const nodeName = (node: AccessNode) => {
    if (node.other) return `${t("Other", "Khác")} (${node.other_count})`;
    if (node.group) return `${ipRoleLabel(t, node.role || node.label)} · ${node.ip_count}`;
    if (node.kind === "api" && apiServices.size <= 1) return splitApi(node.label)[1];
    return node.label;
  };
  const nodeMetric = (node: AccessNode) => {
    if (node.width_tps == null) {
      if (node.group) return node.infrastructure ? t("infrastructure · not an origin", "hạ tầng · không phải nguồn") : t("unverified peers", "peer chưa xác minh");
      return t("volume unknown", "chưa rõ lưu lượng");
    }
    return `${n(node.observed_tps, 3)} TPS${node.expected_tps != null ? ` · ${t("exp", "kỳ vọng")} ${n(node.expected_tps, 3)}` : ""}`;
  };

  const linkTitle = (link: PlacedLink) => {
    const source = nodeById.get(link.source);
    const target = nodeById.get(link.target);
    return `${source ? nodeName(source) : "?"} → ${target ? nodeName(target) : "?"}`;
  };
  const toggle = (key: keyof FlowFilters, value: string) => {
    const next = { ...active };
    if (next[key] === value) delete next[key]; else next[key] = value;
    setActive(next);
  };
  const filterFor = (node: AccessNode): [keyof FlowFilters, string] | null => {
    if (node.other || node.group) return null;
    return [node.kind === "ip" ? "ip" : node.kind, node.label] as [keyof FlowFilters, string];
  };
  const isFocus = (node: AccessNode) => node.kind === focusType && node.label === focus;
  // Clicking an item shows its relationships in place; the layout does not change.
  const onNode = (node: AccessNode) => {
    setSelected(null);
    if (node.other) { setTop(value => TOPS.find(v => v > value) ?? 50); return; }
    if (node.group) { setIpOffset(0); setIpRole(current => (current === (node.role || node.label) ? "" : node.role || node.label)); return; }
    setSelectedNodeId(current => (current === node.id ? null : node.id));
  };
  // Ribbons are selected from the table view (for the TPS-vs-expected chart).
  const onLink = (link: PlacedLink) => {
    setSelectedNodeId(null);
    setSelected(selected?.id === link.id ? null : { ...link, title: linkTitle(link) });
  };
  const reset = () => { setActive({}); setIpRole(""); setIpOffset(0); setSelected(null); setSelectedNodeId(null); setHovered(null); setEmphasis(null); setFind(""); };
  const hasSelection = Object.keys(active).length > 0 || !!ipRole || !!selected || !!selectedNodeId || !!emphasis || !!find;

  const detail = useQuery({
    queryKey: ["access-flow-detail", selected?.detail_id, data?.environment],
    queryFn: ({ signal }) => api<DetailResponse>(`/api/v1/behavior/topology/detail?object_id=${selected!.detail_id}&environment=${encodeURIComponent(data?.environment || "")}`, { signal }),
    enabled: !!selected?.detail_id,
    retry: false,
  });

  // Ids can outlive their element (refetch, filter change); ignore them once they are gone.
  const hoverId = hovered && nodeById.has(hovered.id) ? hovered.id : null;
  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) : undefined;
  const activeId = selectedNode?.id || (selected && linkById.has(selected.id) ? selected.id : null);
  const needle = find.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!needle || !layout) return null;
    return new Set(layout.nodes.filter(node => node.label.toLowerCase().includes(needle)).map(node => node.id));
  }, [needle, layout]);
  const faded = (link: PlacedLink) =>
    (emphasis && asState(link.state) !== emphasis)
    || (!!activeId && activeId !== link.id && activeId !== link.source && activeId !== link.target)
    || (!activeId && !!matches && !matches.has(link.source) && !matches.has(link.target));
  const nodeFaded = (node: PlacedNode) => {
    if (activeId) {
      if (activeId === node.id) return false;
      const link = linkById.get(activeId);
      if (link) return link.source !== node.id && link.target !== node.id;
      return !layout?.links.some(l => (l.source === activeId && l.target === node.id) || (l.target === activeId && l.source === node.id));
    }
    return !!matches && !matches.has(node.id);
  };
  // One delegated handler: only items carry data-hid, ribbons ignore the pointer.
  const hoverFrom = (target: EventTarget | null) => {
    const item = (target as Element | null)?.closest?.("[data-hid]");
    const id = item?.getAttribute("data-hid");
    if (!item || !id) { setHoveredState(null); return; }
    setHoveredState(current => {
      if (current?.id === id) return current;
      const bar = (item.querySelector("[data-bar]") || item).getBoundingClientRect();
      const whole = item.getBoundingClientRect();
      return { id, barLeft: bar.left, itemRight: whole.right, midY: bar.top + Math.min(bar.height, 28) / 2 };
    });
  };

  // The floating box is anchored in viewport coordinates; any scroll would detach it, so hide it.
  useEffect(() => {
    if (!hovered) return;
    const hide = () => setHoveredState(null);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => { window.removeEventListener("scroll", hide, true); window.removeEventListener("resize", hide); };
  }, [hovered]);

  // Clicking anywhere outside an item (except the inspector and table, which act on the selection) clears it.
  useEffect(() => {
    if (!selectedNodeId && !selected) return;
    const onDown = (event: PointerEvent) => {
      const el = event.target as Element | null;
      if (el?.closest?.("[data-hid], [data-keep-selection]")) return;
      setSelectedNodeId(null);
      setSelected(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [selectedNodeId, selected]);
  const isNodeSelected = (node: PlacedNode) =>
    node.id === selectedNodeId || (node.group ? ipRole === (node.role || node.label) : isFocus(node) || (() => { const f = filterFor(node); return !!f && active[f[0]] === f[1]; })());

  // The inspector always has a subject: the selected ribbon, the clicked item, then the focus entity.
  const focusNode = layout?.nodes.find(isFocus);
  const subjectLink = selected ? linkById.get(selected.id) ?? selected : undefined;
  const subjectNode = subjectLink ? undefined : selectedNode || focusNode;
  const subject = subjectLink || subjectNode;
  const hoverNode = hoverId ? nodeById.get(hoverId) : undefined;
  const subjectTitle = subjectNode ? nodeName(subjectNode)
    : subjectLink ? (subjectLink.id === selected?.id && selected.title ? selected.title : linkTitle(subjectLink)) : "";

  const caps = data ? (Object.entries(data.caps) as [AccessColumn, { shown: number; total: number }][]) : [];
  const capFor = (kind: AccessColumn) => caps.find(([k]) => k === kind)?.[1];
  const capped = caps.some(([, cap]) => cap.total > cap.shown);
  const sortedLinks = useMemo(() => [...(layout?.links || [])].sort((a, b) => (b.width_tps ?? -1) - (a.width_tps ?? -1)), [layout]);
  const stale = query.isFetching && query.isPlaceholderData;
  // Many x many columns (callers x credentials, credentials x APIs) become a mesh. A crowded band is
  // drawn as grey ribbons without outlines; new and deviating ribbons keep their orange so they still
  // stand out, and a clicked item's ribbons are redrawn in full above the band.
  const bandSize = useMemo(() => {
    const counts = new Map<string, number>();
    layout?.links.forEach(link => counts.set(link.from_column, (counts.get(link.from_column) || 0) + 1));
    return counts;
  }, [layout]);
  const crowded = [...bandSize.values()].some(count => count > SIMPLIFY_BAND_AT);
  const simplifyBand = (column: string) =>
    linkMode === "simple" ? true : linkMode === "all" ? false : (bandSize.get(column) || 0) > SIMPLIFY_BAND_AT;
  const simplifying = linkMode === "simple" || (linkMode === "auto" && crowded);

  return (
    <div data-testid="access-flow" className="text-ink">
      {/* Toolbar: one row of filters that scope the whole chart. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface-2 px-3 py-2">
        <div className="flex items-center gap-2">
          <ToolLabel>{t("Width", "Độ rộng")}</ToolLabel>
          <Segmented label={t("Width basis", "Cơ sở độ rộng")} value={basis} onChange={setBasis}
            options={[["observed", t("Observed TPS", "TPS quan sát")], ["baseline", t("Learned baseline", "Baseline đã học")]]} />
        </div>
        <div className="flex items-center gap-2">
          <ToolLabel>{t("Current", "Hiện tại")}</ToolLabel>
          <Segmented label={t("Current window", "Cửa sổ hiện tại")} value={windowMinutes} onChange={setWindowMinutes} options={WINDOWS} />
        </div>
        {(crowded || linkMode !== "auto") && (
          <div className="flex items-center gap-2">
            <ToolLabel>{t("Links", "Liên kết")}</ToolLabel>
            <Segmented label={t("Links", "Liên kết")} value={simplifying ? "simple" : "all"} onChange={setLinkMode}
              options={[["simple", t("Simplified", "Rút gọn")], ["all", t("All", "Tất cả")]]} />
          </div>
        )}
        <label className="flex items-center gap-2">
          <ToolLabel>Top</ToolLabel>
          <select className="h-7 rounded-ctl border border-line bg-surface px-1.5 text-[11px] text-ink shadow-xs" value={top}
            onChange={e => setTop(Number(e.target.value))} aria-label={t("Items per column", "Số mục mỗi cột")}>
            {TOPS.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className="relative flex items-center">
          <Search size={12} aria-hidden="true" className="pointer-events-none absolute left-2 text-muted" />
          <input value={find} onChange={e => setFind(e.target.value)} placeholder={t("Find credential, API…", "Tìm credential, API…")}
            aria-label={t("Highlight matching entities", "Làm nổi bật thực thể khớp")}
            className="h-7 w-[200px] rounded-ctl border border-line bg-surface pl-6 pr-6 text-[11px] text-ink placeholder:text-muted shadow-xs focus:border-line-strong" />
          {find && <button type="button" onClick={() => setFind("")} aria-label={t("Clear", "Xoá")} className="absolute right-1.5 text-muted hover:text-ink"><X size={12} /></button>}
          {matches && <span className="ml-2 font-mono text-[11px] text-muted">{matches.size} {t("match", "khớp")}</span>}
        </label>
        {hasSelection && (
          <button type="button" onClick={reset} className="inline-flex h-7 items-center gap-1 rounded-ctl px-2 text-[11px] text-warn hover:bg-warn-bg">
            <RotateCcw size={12} aria-hidden="true" /> {t("Reset", "Đặt lại")}
          </button>
        )}
        <span className="ml-auto text-[11px] text-muted" aria-live="polite">
          {data?.status === "active" && <>
            <span className="font-mono text-ink">{data.relationships_total ?? 0}</span> {t("learned relationships", "quan hệ đã học")}
            {data.as_of_ms ? <> · {t("through", "đến")} {new Date(data.as_of_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</> : null}
          </>}
        </span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 px-3 pt-2">
        <StateLegend active={emphasis} onToggle={state => setEmphasis(current => (current === state ? null : state))} />
        {data && data.ip.roles.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5" data-testid="ip-controls">
            <ToolLabel>{t("Peer IP", "IP peer")}</ToolLabel>
            {data.ip.roles.map(role => (
              <button key={role.role} type="button" aria-pressed={ipRole === role.role}
                title={role.infrastructure ? t("Infrastructure peer: never shown as the origin", "Peer hạ tầng: không bao giờ hiển thị là nguồn") : undefined}
                onClick={() => { setIpOffset(0); setIpRole(current => (current === role.role ? "" : role.role)); }}
                className={`inline-flex h-6 items-center gap-1 rounded-ctl border px-1.5 text-[11px] ${ipRole === role.role ? "border-accent bg-accent-soft text-ink font-semibold" : "border-line text-muted hover:border-line-strong hover:text-ink"}`}>
                {ipRoleLabel(t, role.role)} <span className="font-mono text-muted">{role.count}</span>{role.infrastructure && <span aria-hidden="true">⚑</span>}
              </button>
            ))}
            {ipRole && data.ip.role_total != null && data.ip.role_total > data.ip.limit && (
              <span className="inline-flex items-center gap-1 text-[11px]">
                <button type="button" className="h-6 rounded-ctl border border-line px-1.5 disabled:opacity-40" disabled={ipOffset === 0}
                  onClick={() => setIpOffset(Math.max(0, ipOffset - data.ip.limit))} aria-label={t("Previous IPs", "IP trước")}>‹</button>
                <span className="font-mono">{ipOffset + 1}–{Math.min(ipOffset + data.ip.limit, data.ip.role_total)}/{data.ip.role_total}</span>
                <button type="button" className="h-6 rounded-ctl border border-line px-1.5 disabled:opacity-40" disabled={ipOffset + data.ip.limit >= data.ip.role_total}
                  onClick={() => setIpOffset(ipOffset + data.ip.limit)} aria-label={t("Next IPs", "IP sau")}>›</button>
              </span>
            )}
          </div>
        )}
      </div>

      <div ref={chartRef} className="px-3 pt-2">
        {query.isLoading ? <div className="py-10"><Loading /></div> : query.isError ? (
          <div className="py-4"><ErrorState message={(query.error as Error).message} /><button className="btn mt-2" onClick={() => query.refetch()}>{t("Retry", "Thử lại")}</button></div>
        ) : !data || data.status === "learning" ? (
          <p className="py-10 text-center text-xs">{t("The learned graph is still building; no relationships to show yet.", "Đồ thị học đang được xây dựng; chưa có quan hệ để hiển thị.")}</p>
        ) : !layout ? null : !layout.nodes.length ? (
          <p className="py-10 text-center text-xs">{t("No learned relationships match this selection.", "Không có quan hệ đã học nào khớp lựa chọn này.")}</p>
        ) : (
          <div className="overflow-x-auto" data-testid="access-flow-scroll" style={{ opacity: stale ? 0.55 : 1, transition: "opacity 120ms" }}>
            <div style={{ width: layout.width }}>
              {/* Column titles stay visible while a dense flow scrolls vertically. */}
              <svg width={layout.width} height={HEADER_H} aria-hidden="true" className="block">
                {layout.columns.map((kind, i) => {
                  const cap = capFor(kind);
                  return (
                    <g key={kind}>
                      <rect x={layout.columnX[i]} y={6} width={6} height={6} rx={1} fill={getEntityColor(kind)} />
                      <text x={layout.columnX[i] + 11} y={12} fontSize="10" fontWeight="600" letterSpacing=".08em" fill={kind === focusType ? TEXT : MUTED_TEXT}>
                        {columnTitle(kind, t).toUpperCase()}
                        {cap && cap.total > cap.shown && <tspan fill={MUTED_TEXT} fontWeight="400"> · {cap.shown}/{cap.total}</tspan>}
                      </text>
                      {kind === focusType && <line x1={layout.columnX[i]} x2={layout.columnX[i] + 60} y1={HEADER_H - 7} y2={HEADER_H - 7} stroke={TEXT} strokeOpacity=".5" />}
                    </g>
                  );
                })}
              </svg>
              <div className="relative overflow-y-auto overscroll-contain" style={{ maxHeight: BODY_MAX_H }} data-testid="access-flow-body">
                <svg role="group" aria-label={t(`Access flow for ${focus}`, `Luồng truy cập của ${focus}`)} width={layout.width} height={layout.height - HEADER_H}
                  viewBox={`0 ${HEADER_H} ${layout.width} ${layout.height - HEADER_H}`} className="block max-w-none"
                  onPointerOver={event => hoverFrom(event.target)} onPointerLeave={() => setHovered(null)}
                  onFocus={event => { if ((event.target as Element).matches?.(":focus-visible")) { keyboardFocus.current = true; hoverFrom(event.target); } }}
                  onBlur={() => { if (keyboardFocus.current) { keyboardFocus.current = false; setHovered(null); } }}>
                  {layout.links.map(link => {
                    const state = asState(link.state);
                    const style = getStateStyle(state);
                    const muted = simplifyBand(link.from_column) && state !== "new" && state !== "deviating";
                    return (
                      <g key={link.id} data-testid="access-ribbon" data-state={link.state} data-muted={muted || undefined} aria-hidden="true" pointerEvents="none"
                        opacity={faded(link) ? 0.12 : 1} style={{ transition: "opacity 120ms" }}>
                        <path d={link.path} fill={muted ? MUTED_RIBBON : style.color} fillOpacity={muted ? (state === "ghost" || state === "dormant" ? 0.05 : 0.13) : style.fillOpacity} />
                        {!muted && style.strokeOpacity > 0 && <>
                          <path d={link.top} fill="none" stroke={style.color} strokeOpacity={style.strokeOpacity} strokeDasharray={style.dash} strokeWidth="1" />
                          <path d={link.bottom} fill="none" stroke={style.color} strokeOpacity={style.strokeOpacity} strokeDasharray={style.dash} strokeWidth="1" />
                        </>}
                        {!muted && (state === "new" || state === "deviating") && link.volume_known && link.thickness >= 5 && (
                          <g aria-hidden="true">
                            <rect x={link.mx - 7} y={link.my - 7} width="14" height="14" rx="7" fill={SURFACE} stroke={style.color} />
                            <text x={link.mx} y={link.my + 3.5} textAnchor="middle" fontSize="10" fontWeight="700" fill={style.color}>{style.glyph}</text>
                          </g>
                        )}
                      </g>
                    );
                  })}

                  {/* Highlight drawn above all ribbons without reordering them, and transparent to the pointer. */}
                  <g pointerEvents="none" aria-hidden="true">
                    {(layout.links.filter(l => l.id === activeId || l.source === activeId || l.target === activeId)).map(link => {
                      const id = link.id;
                      const style = getStateStyle(asState(link.state));
                      return <path key={id} d={link.path} fill={style.color} fillOpacity={Math.min(0.6, style.fillOpacity + 0.18)} stroke={TEXT} strokeOpacity=".7" strokeWidth="1" />;
                    })}
                  </g>

                  {layout.nodes.map(node => {
                    const state = asState(node.state);
                    const style = getStateStyle(state);
                    const chosen = isNodeSelected(node);
                    const name = nodeName(node);
                    const metric = nodeMetric(node);
                    const maxChars = Math.floor(node.labelWidth / NAME_CHAR_W);
                    const shownName = clip(name, maxChars - (style.glyph ? 2 : 0));
                    const shownMetric = clip(metric, Math.floor(node.labelWidth / METRIC_CHAR_W));
                    const lx = node.x + BAR_W + 6;
                    // Hit area hugs the bar and the drawn text so ribbons passing beside a label stay hoverable.
                    const textW = Math.min(node.labelWidth, Math.max(shownName.length * NAME_CHAR_W + (style.glyph ? 12 : 0), layout.compact ? 0 : shownMetric.length * METRIC_CHAR_W));
                    const hitH = Math.max(node.h, layout.compact ? 14 : 28);
                    return (
                      <g key={node.id} data-hid={node.id} role="button" tabIndex={0} data-testid="access-node" data-kind={node.kind} data-state={node.state} aria-pressed={chosen}
                        aria-label={`${columnTitle(node.kind, t)} ${name}, ${stateLabel(t, state)}, ${metric}`}
                        className="cursor-pointer outline-none" opacity={nodeFaded(node) ? 0.35 : 1} style={{ transition: "opacity 120ms" }}
                        onClick={() => onNode(node)}
                        onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onNode(node); } }}>
                        <rect x={node.x - 2} y={node.y - 2} width={BAR_W + 10 + textW} height={hitH + 4} fill="transparent" />
                        <rect data-bar x={node.x} y={node.y} width={BAR_W} height={node.h} rx="1.5" fill={getEntityColor(node.kind)}
                          fillOpacity={state === "ghost" ? 0.3 : node.other || node.group ? 0.55 : 1}
                          stroke={chosen || hoverId === node.id || matches?.has(node.id) ? TEXT : state === "new" || state === "deviating" ? style.color : "none"} strokeWidth={chosen ? 1.5 : 1}
                          strokeDasharray={!chosen && state === "new" ? style.dash : undefined} />
                        <text x={lx} y={node.y + 11} fontSize="11.5" fontFamily="ui-monospace, SFMono-Regular, monospace" fill={state === "ghost" ? MUTED_TEXT : TEXT}
                          fontWeight={chosen || hoverId === node.id ? 600 : 400} stroke={SURFACE} strokeWidth="3" paintOrder="stroke" strokeLinejoin="round">
                          {shownName}
                          {style.glyph && <tspan fill={style.color} fontWeight="700" dx="5">{style.glyph}</tspan>}
                        </text>
                        {!layout.compact && (
                          <text x={lx} y={node.y + 24} fontSize="10" fill={MUTED_TEXT} stroke={SURFACE} strokeWidth="3" paintOrder="stroke" strokeLinejoin="round">
                            {shownMetric}
                          </text>
                        )}
                      </g>
                    );
                  })}
                </svg>
                {hoverNode && hovered && createPortal((() => {
                  const state = asState(hoverNode.state);
                  const style = getStateStyle(state);
                  // Float to the left of the bar; if the viewport has no room there, use the right of the label.
                  const roomLeft = hovered.barLeft - TIP_GAP - TIP_W >= 8;
                  const left = roomLeft ? hovered.barLeft - TIP_GAP - TIP_W : Math.min(hovered.itemRight + TIP_GAP, window.innerWidth - TIP_W - 8);
                  const top = Math.max(70, Math.min(hovered.midY, window.innerHeight - 70));
                  return (
                    <div data-testid="access-tooltip" role="tooltip"
                      className="pointer-events-none fixed z-[1000] rounded-card border border-line-strong bg-surface px-2.5 py-2 text-[11px] text-ink shadow-pop"
                      style={{ left, top, width: TIP_W, transform: "translateY(-50%)" }}>
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted">{columnTitle(hoverNode.kind, t)}</span>
                        <span className="ml-auto rounded-ctl border px-1 text-[10px]" style={{ borderColor: `${style.color}66`, color: style.color }}>{stateShortLabel(t, state)}</span>
                      </div>
                      <div className="mt-1 break-all font-mono text-[12px] text-ink">{hoverNode.other || hoverNode.group ? nodeName(hoverNode) : hoverNode.label}</div>
                      <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
                        <dt className="text-muted">{t("Observed", "Quan sát")}</dt><dd className="text-right font-mono text-ink">{hoverNode.observed_tps != null ? `${n(hoverNode.observed_tps, 4)} TPS` : "—"}</dd>
                        <dt className="text-muted">{t("Expected", "Kỳ vọng")}</dt><dd className="text-right font-mono text-ink">{hoverNode.expected_tps != null ? `${n(hoverNode.expected_tps, 4)} TPS` : "—"}</dd>
                        <dt className="text-muted">{t("Last seen", "Lần cuối")}</dt><dd className="text-right text-ink">{relativeAge(hoverNode.last_seen_ms, data.as_of_ms, t)}</dd>
                      </dl>
                      <div className="mt-1.5 border-t border-line pt-1 text-[10px] text-muted">
                        {hoverNode.other ? t("Click to show more items", "Bấm để hiện thêm mục")
                          : hoverNode.group ? t("Click to expand this IP group", "Bấm để mở rộng nhóm IP")
                          : hoverNode.id === selectedNodeId ? t("Click to clear", "Bấm để bỏ chọn") : t("Click to show its relationships", "Bấm để xem các quan hệ")}
                      </div>
                    </div>
                  );
                })(), document.body)}
              </div>
            </div>
          </div>
        )}
      </div>

      {data?.status === "active" && layout && layout.nodes.length > 0 && (
        <>
          <p className="px-3 pb-2 pt-1 text-[11px] text-muted" data-testid="access-caps">
            {capped ? `${t("Showing top", "Hiển thị top")} ${data.top} ${t("per column; the rest is grouped as Other.", "mỗi cột; phần còn lại gộp vào Khác.")} ` : ""}
            {t("Hover an item for details; click it to show its relationships. ", "Rê chuột lên mục để xem chi tiết; bấm để xem các quan hệ. ")}
            {t("Width is TPS (small flows are drawn at a minimum width). Peer IP links carry no measured volume. A missing caller or credential adds no ribbon, so an API bar taller than its ribbons includes traffic without a credential.", "Độ rộng là TPS (luồng nhỏ được vẽ với độ rộng tối thiểu). Liên kết IP peer không có lưu lượng đo được. Thiếu caller hoặc credential thì không có ribbon, nên bar API cao hơn các ribbon của nó gồm cả traffic không có credential.")}
          </p>

          {/* Inspector: shows the selected ribbon, the clicked item, or the focus entity. It never follows hover. */}
          <div data-keep-selection className="mx-3 mb-3 grid min-h-[152px] rounded-card border border-line bg-surface p-3 shadow-card" aria-live="polite">
            <div className="min-w-0" data-testid="access-readout">
              {!subject && (
                <p className="text-[12px] text-muted">{t("Hover an item for a quick look; click it to show its relationships and details here.", "Rê chuột lên một mục để xem nhanh; bấm vào để xem quan hệ và chi tiết tại đây.")}</p>
              )}
              {subject && (() => {
                const state = asState(subject.state);
                const style = getStateStyle(state);
                const entity = subjectNode && !subjectNode.other && !subjectNode.group ? subjectNode : undefined;
                return (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted">
                        {subjectNode ? columnTitle(subjectNode.kind, t) : t("Relationship", "Quan hệ")}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-ctl border px-1.5 py-px text-[11px]" style={{ borderColor: `${style.color}66`, color: style.color }}>
                        {style.glyph && <b aria-hidden="true">{style.glyph}</b>}{stateLabel(t, state)}
                      </span>
                    </div>
                    <div className="mt-1 truncate font-mono text-[13px] text-ink font-semibold" title={subjectTitle}>{subjectTitle}</div>
                    <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 xl:grid-cols-4">
                      {([
                        [t("Observed TPS", "TPS quan sát"), subject.observed_tps != null ? n(subject.observed_tps, 4) : "—", true],
                        [t("Expected TPS", "TPS kỳ vọng"), subject.expected_tps != null ? n(subject.expected_tps, 4) : "—", true],
                        [t("Familiarity", "Độ quen thuộc"), subject.familiarity, false],
                        [t("Last seen", "Lần cuối"), relativeAge(subject.last_seen_ms, data.as_of_ms, t), false],
                      ] as [string, string, boolean][]).map(([label, value, mono]) => (
                        <div key={label} className="min-w-0">
                          <dt className="text-[10px] uppercase tracking-[.06em] text-muted">{label}</dt>
                          <dd className={`mt-0.5 break-words text-[13px] text-ink ${mono ? "font-mono" : ""}`}>{value}</dd>
                        </div>
                      ))}
                    </dl>
                    {/* The link row is always reserved so hovering never changes the card height. */}
                    <div className="mt-3 h-[18px] text-[12px]">
                      {entity && entity.kind !== "ip" && (<>
                        {entity.kind === "api" ? (() => { const [svc, op] = splitApi(entity.label); return <EntityLink entity={{ kind: "api", service: svc, operation: op }}>{t("Open API", "Mở API")} →</EntityLink>; })()
                          : entity.kind === "credential" ? <EntityLink entity={{ kind: "user", principal: entity.label }}>{t("Open credential activity", "Mở hoạt động credential")} →</EntityLink>
                          : <EntityLink entity={{ kind: "service", name: entity.label }}>{t("Open Service", "Mở Service")} →</EntityLink>}
                        {(() => {
                          const f = filterFor(entity);
                          if (!f || isFocus(entity)) return null;
                          const on = active[f[0]] === f[1];
                          return (
                            <button type="button" className="ml-4 text-accent hover:underline font-medium" onClick={() => toggle(f[0], f[1])}>
                              {on ? t("Clear flow filter", "Bỏ lọc luồng") : t("Filter flow to this", "Lọc luồng theo mục này")}
                            </button>
                          );
                        })()}
                      </>)}
                    </div>
                  </>
                );
              })()}
            </div>
            <div className="min-w-0 border-t border-line p-3 md:border-l md:border-t-0" data-testid="access-sparkline">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-[.08em] text-muted">{t("TPS vs expected", "TPS so với kỳ vọng")}</div>
              {!selected ? (
                <p className="text-[12px] text-muted">{t("Pick a relationship row in the table view to plot its last observed day against the learned expectation.", "Chọn một dòng quan hệ trong dạng bảng để vẽ ngày quan sát gần nhất so với kỳ vọng đã học.")}</p>
              ) : !selected.detail_id ? (
                <p className="text-[12px] text-muted">{t("The learned graph keeps no series at this level.", "Đồ thị học không lưu chuỗi ở cấp này.")}</p>
              ) : detail.isLoading ? <Loading /> : detail.data?.series.length ? (
                <div className="h-[92px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={detail.data.series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="var(--grid)" vertical={false} />
                      <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} hide />
                      <YAxis width={36} tick={{ fontSize: 10, fill: "var(--muted)" }} tickLine={false} axisLine={false} tickFormatter={v => n(Number(v), 2)} />
                      <Tooltip {...chartTooltip} labelFormatter={v => new Date(Number(v)).toLocaleString()} formatter={(value: unknown, name: unknown) => [`${n(Number(value), 4)} TPS`, String(name)]} />
                      <Line dataKey="expected_tps" name={t("Expected", "Kỳ vọng")} stroke="var(--series-2)" strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
                      <Line dataKey="tps" name={t("Observed", "Quan sát")} stroke="var(--series-1)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <p className="text-[12px] text-muted">{t("No retained samples for this ribbon.", "Không còn mẫu cho ribbon này.")}</p>}
            </div>
          </div>

          {/* Table view: the same ribbons as rows, for screen readers and exact values. */}
          <details className="border-t border-line" data-testid="access-table" data-keep-selection>
            <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-2 text-[11px] text-muted hover:text-ink">
              <Table2 size={13} aria-hidden="true" /> {t("Table view", "Dạng bảng")} <span className="text-muted">({sortedLinks.length})</span>
            </summary>
            <div className="max-h-[280px] overflow-auto px-3 pb-3">
              <table className="w-full min-w-[560px] text-left text-[11px]">
                <thead className="sticky top-0 bg-surface-2 text-[10px] uppercase tracking-[.06em] text-muted">
                  <tr><th className="py-1.5 pr-2 font-medium">{t("From", "Từ")}</th><th className="pr-2 font-medium">{t("To", "Đến")}</th><th className="pr-2 font-medium">{t("State", "Trạng thái")}</th>
                    <th className="pr-2 text-right font-medium">{t("Observed", "Quan sát")}</th><th className="pr-2 text-right font-medium">{t("Expected", "Kỳ vọng")}</th><th className="font-medium">{t("Last seen", "Lần cuối")}</th></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {sortedLinks.map(link => {
                    const state = asState(link.state);
                    const source = nodeById.get(link.source);
                    const target = nodeById.get(link.target);
                    return (
                      <tr key={link.id} className={`cursor-pointer hover:bg-hover ${selected?.id === link.id ? "bg-accent-soft" : ""}`} onClick={() => onLink(link)}>
                        <td className="max-w-[180px] truncate py-1.5 pr-2 font-mono text-ink">{source ? nodeName(source) : ""}</td>
                        <td className="max-w-[180px] truncate pr-2 font-mono text-ink">{target ? nodeName(target) : ""}</td>
                        <td className="whitespace-nowrap pr-2"><span className="inline-flex items-center gap-1"><Swatch state={state} />{stateShortLabel(t, state)}</span></td>
                        <td className="pr-2 text-right font-mono tabular-nums text-ink">{link.observed_tps != null ? n(link.observed_tps, 4) : "—"}</td>
                        <td className="pr-2 text-right font-mono tabular-nums text-muted">{link.expected_tps != null ? n(link.expected_tps, 4) : "—"}</td>
                        <td className="whitespace-nowrap text-muted">{relativeAge(link.last_seen_ms, data.as_of_ms, t)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </div>
  );
}

export type { AccessState };
