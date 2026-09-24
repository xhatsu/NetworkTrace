import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Clock,
  GitBranch,
  Maximize2,
  Network,
  RefreshCw,
  Search,
  Server,
  UserRound,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, MetricCard, n, pct } from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import { layoutServiceGraph, type Position } from "../topologyLayout";

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
  anonymous_requests: number;
  api_count?: number;
  first_seen_ms?: number | null;
  last_seen_ms?: number | null;
  evidence_type: "direct" | "inferred";
  evidence_types: string[];
  confidence: number;
  timeout_count: number;
  tcp_reset_count: number;
  incomplete_count: number;
  change: {
    status?: string;
    baseline?: string;
    tps_change_pct?: number;
    latency_change_pct?: number;
    error_rate_delta?: number;
    bandwidth_change_pct?: number;
    anonymous_change_pct?: number;
  };
};

type TopologyNode = {
  id: string;
  name: string;
  type: "service" | "api" | "principal";
  service?: string;
  api?: string;
  principal?: string;
  edge_ids?: string[];
  service_count?: number;
  api_count?: number;
  metrics: Metrics;
};

type TopologyEdge = {
  id: string;
  source: string;
  target: string;
  source_name: string;
  target_name: string;
  metrics: Metrics;
  evidence_type: "direct" | "inferred";
  direct: boolean;
  inferred: boolean;
};

type TopologyResponse = {
  window: { start_ms: number; end_ms: number; duration_seconds: number; label: string; baseline: string };
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  changes: { new_edges?: TopologyEdge[]; disappeared_edges?: Array<{ dimensions: Record<string, string>; metrics: Metrics }>; baseline?: string };
  anonymous: {
    total_requests: number;
    identified_requests: number;
    anonymous_requests: number;
    identified_request_percentage: number;
    anonymous_request_percentage: number;
    anonymous_tps: number;
    top_services?: Array<{ name: string; requests: number }>;
    top_apis?: Array<{ name: string; requests: number }>;
  };
  backend: string;
  parent?: Record<string, string>;
  next_cursor?: string | null;
  page_size?: number;
};

type DetailResponse = {
  entity: TopologyNode & { groups?: Record<string, Record<string, number>> };
  metrics: Metrics;
  series: Array<Record<string, number>>;
  anonymous: TopologyResponse["anonymous"];
  changes: Record<string, string>;
  backend: string;
};

type SearchResponse = {
  query: string;
  items: TopologyNode[];
  backend: string;
};

type PrincipalDirectoryResponse = {
  items: TopologyNode[];
  next_cursor?: string | null;
  page_size: number;
  backend: string;
};

type IpPage = {
  principal: string;
  items: Array<{
    source_ip: string;
    service: string;
    api: string;
    caller_service: string;
    request_count: number;
    tps: number;
    error_rate: number;
    p95_latency_ms: number;
    first_seen_ms: number;
    last_seen_ms: number;
    is_load_balancer: boolean;
    source_ip_role: string;
    role_label: string;
    attribution_confidence: string;
    is_new_ip: boolean;
  }>;
  next_cursor?: string | null;
};

type Selection =
  | { kind: "node"; node: TopologyNode }
  | { kind: "edge"; edge: TopologyEdge }
  | null;

const FIVE_MINUTE_MS = 5 * 60 * 1000;
const SEVEN_DAY_SLICES = 7 * 24 * 12;

function emptyMetrics(): Metrics {
  return {
    tps: 0,
    request_count: 0,
    p50_latency_ms: 0,
    p95_latency_ms: 0,
    p99_latency_ms: 0,
    error_rate: 0,
    http_4xx_rate: 0,
    http_5xx_rate: 0,
    request_bytes: 0,
    response_bytes: 0,
    average_request_bytes: 0,
    average_response_bytes: 0,
    unique_principals: 0,
    unique_source_ips: 0,
    anonymous_requests: 0,
    evidence_type: "inferred",
    evidence_types: [],
    confidence: 0,
    timeout_count: 0,
    tcp_reset_count: 0,
    incomplete_count: 0,
    change: {},
  };
}

function childPosition(parent: Position, index: number, total: number, vertical = false): Position {
  const angle = -Math.PI / 2 + (Math.PI * (index + 1)) / (total + 1);
  const radius = vertical ? 170 : 150;
  return { x: parent.x + Math.cos(angle) * radius, y: parent.y + Math.sin(angle) * radius };
}

function edgePath(source: Position, target: Position): string {
  const dx = target.x - source.x;
  if (dx >= 0) {
    const bend = Math.max(60, Math.min(180, dx * 0.4));
    return [
      `M ${source.x} ${source.y}`,
      `C ${source.x + bend} ${source.y}`,
      `${target.x - bend} ${target.y}`,
      `${target.x} ${target.y}`,
    ].join(" ");
  }

  const topY = Math.min(source.y, target.y) - 120;
  return [
    `M ${source.x} ${source.y}`,
    `C ${source.x + 100} ${topY}`,
    `${target.x - 100} ${topY}`,
    `${target.x} ${target.y}`,
  ].join(" ");
}

function statusTone(status?: string) {
  if (status === "new") return "border-cyan-400/60 bg-cyan-400/10 text-cyan-300";
  if (status === "disappeared") return "border-rose-400/60 bg-rose-400/10 text-rose-300";
  if (status === "changed") return "border-amber-400/60 bg-amber-400/10 text-amber-300";
  return "border-[#303449] bg-[#1a1d2c] text-[#94a3b8]";
}

function entityTone(type: TopologyNode["type"]) {
  if (type === "principal") return { text: "text-[#d9b4ea]", border: "border-l-[#b877d9]", soft: "bg-[#b877d9]/10" };
  if (type === "api") return { text: "text-[#82d5c4]", border: "border-l-[#56b9a8]", soft: "bg-[#56b9a8]/10" };
  return { text: "text-[#8db7fa]", border: "border-l-[#5794f2]", soft: "bg-[#5794f2]/10" };
}

function formatTime(ms?: number | null) {
  return ms ? new Date(ms).toLocaleString() : "—";
}

function NodeIcon({ type }: { type: TopologyNode["type"] }) {
  if (type === "principal") return <UserRound size={14} />;
  if (type === "api") return <GitBranch size={14} />;
  return <Server size={14} />;
}

function MetricStrip({ metrics, vertical = false }: { metrics: Metrics; vertical?: boolean }) {
  const { t } = useI18n();
  if (vertical) {
    const status = metrics.error_rate > 0.05
      ? `${pct(metrics.error_rate)} ${t("errors")}`
      : metrics.change?.status || "normal";
    return (
      <div className="flex items-center justify-between gap-3 pt-1">
        <div>
          <div className="label">{t("TPS")}</div>
          <div className="font-mono text-sm text-sky-300">{n(metrics.tps, 2)}</div>
        </div>
        <span className={`rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase ${metrics.error_rate > 0.05 ? "border-rose-400/50 text-rose-300" : statusTone(metrics.change?.status)}`}>
          {status}
        </span>
      </div>
    );
  }
  const metricClass = "";
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <div className={metricClass}><div className="label">{t("TPS")}</div><div className="font-mono text-sm text-sky-300">{n(metrics.tps, 2)}</div></div>
      <div className={metricClass}><div className="label">p95</div><div className="font-mono text-sm text-violet-300">{n(metrics.p95_latency_ms, 1)} ms</div></div>
      <div className={metricClass}><div className="label">{t("Errors")}</div><div className={`font-mono text-sm ${metrics.error_rate > 0.05 ? "text-rose-300" : "text-emerald-300"}`}>{pct(metrics.error_rate)}</div></div>
      <div className={metricClass}><div className="label">{t("Change")}</div><div className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${statusTone(metrics.change?.status)}`}>{metrics.change?.status || "normal"}</div></div>
    </div>
  );
}

function TpsLineGraph({ data }: { data: Array<{ timestamp_ms: number; tps: number }> }) {
  const width = 320;
  const height = 128;
  const left = 34;
  const right = 8;
  const top = 8;
  const bottom = 22;
  const maxTps = Math.max(1, ...data.map((point) => point.tps));
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const coordinates = data.map((point, index) => {
    const x = left + (index / Math.max(1, data.length - 1)) * plotWidth;
    const y = top + plotHeight - (point.tps / maxTps) * plotHeight;
    return { x, y };
  });
  const smoothPath = coordinates.length < 2
    ? ""
    : coordinates.reduce((path, point, index) => {
        if (index === 0) return `M ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
        const previous = coordinates[index - 1];
        const beforePrevious = coordinates[Math.max(0, index - 2)];
        const next = coordinates[Math.min(coordinates.length - 1, index + 1)];
        const control1X = previous.x + (point.x - beforePrevious.x) / 6;
        const control1Y = previous.y + (point.y - beforePrevious.y) / 6;
        const control2X = point.x - (next.x - previous.x) / 6;
        const control2Y = point.y - (next.y - previous.y) / 6;
        return `${path} C ${control1X.toFixed(1)} ${control1Y.toFixed(1)}, ${control2X.toFixed(1)} ${control2Y.toFixed(1)}, ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
      }, "");
  const firstTime = data[0]?.timestamp_ms;
  const lastTime = data[data.length - 1]?.timestamp_ms;
  const shortTime = (value: number) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="h-44 rounded border border-[#303449] bg-[#10121c] px-2 pb-2 pt-3" data-testid="topology-tps-chart">
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="TPS time-series line graph" preserveAspectRatio="none">
        {[0, 0.5, 1].map((ratio) => {
          const y = top + plotHeight * ratio;
          const value = maxTps * (1 - ratio);
          return <g key={ratio}><line x1={left} y1={y} x2={width - right} y2={y} stroke="#25293a" strokeWidth="1" /><text x={left - 5} y={y + 3} fill="#64748b" fontSize="8" textAnchor="end">{n(value, 1)}</text></g>;
        })}
        {coordinates.length > 1 && <path className="time-series-curve" d={smoothPath} fill="none" stroke="#38bdf8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
        {data.map((point, index) => {
          const coordinate = coordinates[index];
          return <circle key={`${point.timestamp_ms}-${index}`} cx={coordinate.x} cy={coordinate.y} r="2" fill="#38bdf8"><title>{`${formatTime(point.timestamp_ms)} · ${n(point.tps, 2)} TPS · 5m bucket`}</title></circle>;
        })}
        <text x={left} y={height - 4} fill="#64748b" fontSize="8">{firstTime ? shortTime(firstTime) : ""}</text>
        <text x={width - right} y={height - 4} fill="#64748b" fontSize="8" textAnchor="end">{lastTime ? shortTime(lastTime) : ""}</text>
      </svg>
    </div>
  );
}

function GraphSurface({
  nodes,
  edges,
  positions,
  selection,
  highlightedEdgeIds,
  focusedEdgeMetrics,
  onSelect,
  onClearSelection,
  onMoveNode,
  onToggleExpand,
  expanded,
  expandEnabled,
  focusRequest,
}: {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  positions: Record<string, Position>;
  selection: Selection;
  highlightedEdgeIds: Set<string>;
  focusedEdgeMetrics: Map<string, Metrics>;
  onSelect: (selection: Selection) => void;
  onClearSelection: () => void;
  onMoveNode: (nodeId: string, position: Position) => void;
  onToggleExpand: (node: TopologyNode) => void;
  expanded: Set<string>;
  expandEnabled: boolean;
  focusRequest?: { nodeId: string; token: number };
}) {
  const { t } = useI18n();
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ startX: number; startY: number; panX: number; panY: number; moved: boolean } | null>(null);
  const nodeDrag = useRef<{ nodeId: string; startX: number; startY: number; origin: Position; moved: boolean } | null>(null);
  const suppressCanvasClick = useRef(false);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const lastFocusToken = useRef(0);

  useEffect(() => {
    if (!focusRequest || focusRequest.token === lastFocusToken.current) return;
    const position = positions[focusRequest.nodeId];
    const bounds = surfaceRef.current?.getBoundingClientRect();
    if (!position || !bounds) return;
    setPan({
      x: (500 - position.x) * (bounds.width / 1000),
      y: (310 - position.y) * (bounds.height / 620),
    });
    lastFocusToken.current = focusRequest.token;
  }, [focusRequest, positions]);

  function resetViewport() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }

  function changeZoom(delta: number) {
    setZoom((current) => Math.min(2.5, Math.max(0.5, Number((current + delta).toFixed(2)))));
  }

  const orderedEdges = highlightedEdgeIds.size
    ? [...edges].sort((left, right) => Number(highlightedEdgeIds.has(left.id)) - Number(highlightedEdgeIds.has(right.id)))
    : edges;

  return (
    <div
      ref={surfaceRef}
      className="absolute inset-0 touch-none overflow-hidden bg-[#0c0d14] cursor-grab active:cursor-grabbing"
      aria-label={t("Interactive service topology")}
      style={{
        backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'%3E%3Cpath d='M32 0H0V32' fill='none' stroke='%231d2030' stroke-width='1'/%3E%3C/svg%3E\")",
        backgroundPosition: `${pan.x}px ${pan.y}px`,
        backgroundSize: `${32 * zoom}px ${32 * zoom}px`,
      }}
      onWheel={(event) => { event.preventDefault(); changeZoom(event.deltaY < 0 ? 0.1 : -0.1); }}
      onPointerDown={(event) => {
        if (event.button !== 0 || (event.target as Element).closest("[data-topology-object='true']")) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { startX: event.clientX, startY: event.clientY, panX: pan.x, panY: pan.y, moved: false };
      }}
      onPointerMove={(event) => {
        if (!drag.current) return;
        const dx = event.clientX - drag.current.startX;
        const dy = event.clientY - drag.current.startY;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
        setPan({ x: drag.current.panX + dx, y: drag.current.panY + dy });
      }}
      onPointerUp={(event) => {
        if (!drag.current) return;
        suppressCanvasClick.current = drag.current.moved;
        if (drag.current.moved) window.setTimeout(() => { suppressCanvasClick.current = false; }, 0);
        drag.current = null;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={() => { drag.current = null; suppressCanvasClick.current = false; }}
      onLostPointerCapture={() => { drag.current = null; }}
      onClick={() => {
        if (suppressCanvasClick.current) { suppressCanvasClick.current = false; return; }
        onClearSelection();
      }}
      onDoubleClick={(event) => {
        if (!(event.target as Element).closest("[data-topology-object='true']")) resetViewport();
      }}
    >
      <div
        className="absolute inset-0"
        data-testid="topology-transform-layer"
        style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: "center center" }}
      >
      <svg className="absolute inset-0 h-full w-full overflow-visible" viewBox="0 0 1000 620" preserveAspectRatio="none" role="img" aria-label={`Topology graph with ${nodes.length} nodes and ${edges.length} relationships`}>
        <defs>
          <marker id="topology-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" /></marker>
          <marker id="topology-arrow-selected" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#facc15" /></marker>
        </defs>
        {orderedEdges.map((edge) => {
          const source = positions[edge.source];
          const target = positions[edge.target];
          if (!source || !target) return null;
          const selected = highlightedEdgeIds.has(edge.id) || (selection?.kind === "edge" && selection.edge.id === edge.id);
          const scoped = selection?.kind === "node" && (selection.node.type !== "service" || !!selection.node.principal);
          const labelMetrics = scoped ? focusedEdgeMetrics.get(edge.id) : edge.metrics;
          const path = edgePath(source, target);
          return (
            <g key={edge.id} data-topology-object="true" onClick={(event) => { event.stopPropagation(); onSelect({ kind: "edge", edge }); }} className="cursor-pointer">
              <path d={path} fill="none" stroke="transparent" strokeWidth="16" />
              <path d={path} fill="none" stroke={selected ? "#facc15" : "#5794c8"} strokeWidth={selected ? 4 : 1.5} strokeDasharray={edge.inferred ? "7 6" : undefined} markerEnd={selected ? "url(#topology-arrow-selected)" : "url(#topology-arrow)"} opacity={selected ? 1 : highlightedEdgeIds.size ? .16 : .22} />
              {selected && labelMetrics && <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 8} fill="#fde68a" fontSize="11" textAnchor="middle">{n(labelMetrics.tps, 1)} tps</text>}
            </g>
          );
        })}
      </svg>
      {nodes.map((node) => {
        const pos = positions[node.id];
        if (!pos) return null;
        const canExpand = node.type === "service" && expandEnabled;
        const expandedKey = node.id;
        const isExpanded = expanded.has(expandedKey);
        const isSelected = selection?.kind === "node" && selection.node.id === node.id;
        const tone = entityTone(node.type);
        return (
          <div
            key={node.id}
            data-topology-object="true"
            data-topology-node="true"
            data-topology-node-type={node.type}
            className="absolute w-44 -translate-x-1/2 -translate-y-1/2 cursor-move"
            style={{ left: `${pos.x / 10}%`, top: `${pos.y / 6.2}%`, zIndex: isSelected ? 30 : 10 }}
            onPointerDown={(event) => {
              if (event.button !== 0 || (event.target as Element).closest("[data-node-drag-ignore='true']")) return;
              nodeDrag.current = { nodeId: node.id, startX: event.clientX, startY: event.clientY, origin: pos, moved: false };
            }}
            onPointerMove={(event) => {
              if (!nodeDrag.current || nodeDrag.current.nodeId !== node.id) return;
              const bounds = event.currentTarget.parentElement?.parentElement?.getBoundingClientRect();
              if (!bounds) return;
              const dx = event.clientX - nodeDrag.current.startX;
              const dy = event.clientY - nodeDrag.current.startY;
              if (Math.abs(dx) + Math.abs(dy) > 3 && !nodeDrag.current.moved) {
                nodeDrag.current.moved = true;
                event.currentTarget.setPointerCapture(event.pointerId);
              }
              onMoveNode(node.id, {
                x: nodeDrag.current.origin.x + (dx / zoom) * (1000 / bounds.width),
                y: nodeDrag.current.origin.y + (dy / zoom) * (620 / bounds.height),
              });
            }}
            onPointerUp={(event) => {
              if (!nodeDrag.current || nodeDrag.current.nodeId !== node.id) return;
              const captured = event.currentTarget.hasPointerCapture(event.pointerId);
              nodeDrag.current = null;
              if (captured) event.currentTarget.releasePointerCapture(event.pointerId);
            }}
            onPointerCancel={() => { nodeDrag.current = null; }}
            onLostPointerCapture={() => { nodeDrag.current = null; }}
          >
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onSelect({ kind: "node", node });
              }}
              className={`group w-full rounded-lg border border-l-4 bg-[#171a28] px-3 py-2 text-left transition hover:border-white/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${tone.border} ${isSelected ? "border-white ring-1 ring-white/70" : node.metrics.change?.status === "new" ? "border-cyan-400/70" : node.metrics.change?.status === "changed" ? "border-amber-400/70" : "border-[#303449]"}`}
              aria-label={`Inspect ${node.type} ${node.name}`}
            >
              <span className={`flex items-center gap-2 text-xs font-semibold ${tone.text}`}><NodeIcon type={node.type} /><span className="truncate">{node.name}</span></span>
              <span className={`mt-0.5 block text-[9px] uppercase tracking-wider ${tone.text}`}>{node.type === "principal" ? t("User") : t(node.type === "api" ? "API" : "Service")}</span>
              <span className="mt-1 block"><MetricStrip metrics={node.metrics} vertical /></span>
            </button>
            {canExpand && (
              <button
                type="button"
                data-node-drag-ignore="true"
                className="absolute -right-2 -top-2 grid h-6 w-6 place-items-center rounded-full border border-cyan-400/60 bg-[#0e1621] text-cyan-300 shadow-sm hover:bg-cyan-400 hover:text-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
                onClick={(event) => { event.stopPropagation(); onToggleExpand(node); }}
                aria-label={`${isExpanded ? "Collapse" : "Expand"} ${node.type} ${node.name}`}
                title={`${isExpanded ? "Collapse" : "Expand"} ${node.type}`}
              >
                {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              </button>
            )}
          </div>
        );
      })}
      {!nodes.length && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-sm text-[#94a3b8]">
          <div>{t("No topology relationships in this window.")}</div>
          <div className="text-xs text-[#64748b]">
            {t("Switch to a wider time window (e.g. 24h or 7d) to explore historical estate relationships.")}
          </div>
          <div className="text-xs text-cyan-300">{t("Move the seven-day slider to another five-minute window.")}</div>
        </div>
      )}
      </div>
      <div className="absolute bottom-24 left-3 z-20 flex flex-col overflow-hidden rounded border border-[#303449] bg-[#141622] xl:bottom-14" data-topology-object="true" aria-label={t("Canvas navigation controls")}>
        <button type="button" data-testid="topology-zoom-in" className="grid h-7 w-8 place-items-center text-[#cbd5e1] hover:bg-[#202333] hover:text-white" onClick={(event) => { event.stopPropagation(); changeZoom(0.1); }} aria-label={t("Zoom in")} title={t("Zoom in")}><ZoomIn size={14} /></button>
        <button type="button" data-testid="topology-reset-view" className="border-y border-[#303449] px-1 py-1 font-mono text-[9px] font-semibold text-cyan-300" onClick={(event) => { event.stopPropagation(); resetViewport(); }} aria-label={t("Reset canvas view")} title={t("Reset canvas view")}>{Math.round(zoom * 100)}%</button>
        <button type="button" data-testid="topology-zoom-out" className="grid h-7 w-8 place-items-center text-[#cbd5e1] hover:bg-[#202333] hover:text-white" onClick={(event) => { event.stopPropagation(); changeZoom(-0.1); }} aria-label={t("Zoom out")} title={t("Zoom out")}><ZoomOut size={14} /></button>
      </div>
    </div>
  );
}

function RelationshipListPanel({
  title,
  items,
  selectedId,
  loading,
  error,
  search,
  onSearch,
  onSelect,
  onClose,
  hasMore,
  onLoadMore,
}: {
  title: string;
  items: TopologyNode[];
  selectedId?: string;
  loading: boolean;
  error: boolean;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (node: TopologyNode) => void;
  onClose: () => void;
  hasMore: boolean;
  onLoadMore: () => void;
}) {
  const { t } = useI18n();
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const panelDrag = useRef<{ pointerId: number; startX: number; startY: number; originX: number; originY: number } | null>(null);

  function startPanelDrag(event: ReactPointerEvent<HTMLElement>) {
    if (event.button !== 0 || (event.target as Element).closest("button")) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    panelDrag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: dragOffset.x,
      originY: dragOffset.y,
    };
    setDragging(true);
  }

  function movePanel(event: ReactPointerEvent<HTMLElement>) {
    const drag = panelDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const panelBounds = event.currentTarget.parentElement?.getBoundingClientRect();
    const canvasBounds = event.currentTarget.closest("main")?.getBoundingClientRect();
    const baseLeft = panelBounds ? panelBounds.left - dragOffset.x : undefined;
    const baseTop = panelBounds ? panelBounds.top - dragOffset.y : undefined;
    const nextX = drag.originX + event.clientX - drag.startX;
    const nextY = drag.originY + event.clientY - drag.startY;
    setDragOffset({
      x: canvasBounds && panelBounds && baseLeft !== undefined
        ? Math.min(canvasBounds.right - panelBounds.width - baseLeft, Math.max(canvasBounds.left - baseLeft, nextX))
        : nextX,
      y: canvasBounds && panelBounds && baseTop !== undefined
        ? Math.min(canvasBounds.bottom - panelBounds.height - baseTop, Math.max(canvasBounds.top - baseTop, nextY))
        : nextY,
    });
  }

  function stopPanelDrag(event: ReactPointerEvent<HTMLElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    panelDrag.current = null;
    setDragging(false);
  }

  return (
    <section className="pointer-events-auto relative flex max-h-[min(32vh,220px)] w-[min(240px,calc(100vw-1.5rem))] shrink-0 flex-col overflow-hidden rounded border border-[#34384c] bg-[#141622]" aria-label={title} data-testid="topology-drilldown-panel" style={{ transform: `translate(${dragOffset.x}px, ${dragOffset.y}px)`, zIndex: dragging ? 50 : 0 }}>
      <header
        className="flex touch-none cursor-move select-none items-center justify-between border-b border-[#303449] px-2 py-1"
        onPointerDown={startPanelDrag}
        onPointerMove={movePanel}
        onPointerUp={stopPanelDrag}
        onPointerCancel={stopPanelDrag}
        onLostPointerCapture={() => { panelDrag.current = null; setDragging(false); }}
      >
        <h2 className="truncate text-[11px] font-semibold text-white">{title}</h2>
        <div className="ml-2 flex shrink-0 items-center gap-2">
          <span className="rounded bg-[#202333] px-1.5 py-0.5 font-mono text-[10px] text-[#94a3b8]">{items.length}</span>
          <button type="button" onClick={onClose} className="grid h-7 w-7 place-items-center rounded text-[#94a3b8] hover:bg-[#202333] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-yellow-400" aria-label={`${t("Close")} ${title}`}><X size={14} /></button>
        </div>
      </header>
      <div className="border-b border-[#303449] p-1.5">
        <input type="search" value={search} onChange={(event) => onSearch(event.target.value)} placeholder={t("Search...")} aria-label={`${title} ${t("Search")}`} className="h-7 w-full rounded border border-[#303449] bg-[#0f111b] px-2 text-[11px] text-white outline-none placeholder:text-[#64748b] focus:border-cyan-400" />
      </div>
      <div className="min-h-0 overflow-y-auto p-1">
        {loading && <p className="px-2 py-3 text-xs text-[#94a3b8]">{t("Loading...")}</p>}
        {error && <p className="px-2 py-3 text-xs text-rose-300">{t("This list could not be loaded.")}</p>}
        {!loading && !error && items.length === 0 && <p className="px-2 py-3 text-xs text-[#94a3b8]">{t("No matching items in this time window.")}</p>}
        {items.map((item) => (
          <button key={item.id} type="button" data-testid="topology-drilldown-item" onClick={() => onSelect(item)} className={`mb-0.5 flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left transition ${selectedId === item.id ? "bg-[#2a2a25] ring-1 ring-yellow-400/70" : "hover:bg-[#202333]"}`}>
            <span className={`grid h-6 w-6 shrink-0 place-items-center rounded border border-[#303449] ${entityTone(item.type).soft} ${entityTone(item.type).text}`}><NodeIcon type={item.type} /></span>
            <span className="min-w-0 flex-1"><span className={`block truncate text-[11px] font-medium ${entityTone(item.type).text}`}>{item.name}</span><span className="block truncate font-mono text-[9px] text-[#64748b]">{n(item.metrics.request_count, 0)} {t("requests")} · {n(item.metrics.tps, 2)} TPS</span></span>
            {item.type === "service" && item.metrics.api_count !== undefined && <span className="shrink-0 text-[10px] text-[#94a3b8]">{item.metrics.api_count} APIs</span>}
          </button>
        ))}
        {hasMore && <button type="button" className="btn mt-1 w-full justify-center" onClick={onLoadMore}>{t("Load more")}</button>}
      </div>
    </section>
  );
}

function DetailPanel({
  selection,
  detail,
  detailLoading,
  detailError,
  ips,
  ipLoading,
  onLoadMoreIps,
  onClose,
}: {
  selection: Selection;
  detail?: DetailResponse;
  detailLoading: boolean;
  detailError: boolean;
  ips?: IpPage;
  ipLoading: boolean;
  onLoadMoreIps: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  if (!selection) return null;
  const metrics = selection.kind === "edge" ? selection.edge.metrics : detail?.metrics || selection.node.metrics || emptyMetrics();
  const entity = selection.kind === "edge" ? { name: `${selection.edge.source_name} → ${selection.edge.target_name}`, type: "relationship" } : detail?.entity || selection.node;
  const tpsSeries = (detail?.series || []).map((point) => ({
    timestamp_ms: Number(point.timestamp_ms || Number(point.bucket_start || 0) * 1000),
    tps: Number(point.tps || 0),
  }));
  return (
    <aside className="absolute bottom-4 right-4 top-20 z-30 w-[min(380px,calc(100%-2rem))] overflow-y-auto rounded-lg border border-[#34384c] bg-[#141622]" aria-label={t("Topology object details")} data-testid="topology-inspector">
      <div className="sticky top-0 z-10 flex items-start justify-between border-b border-[#262838] bg-[#181a28] px-4 py-3">
        <div><div className="label">{entity.type}</div><h3 className="mt-1 max-w-[270px] break-words text-base font-semibold text-white">{entity.name}</h3></div>
        <button type="button" onClick={onClose} className="btn px-2" aria-label={t("Close topology detail panel")}><X size={14} /></button>
      </div>
      {detailLoading ? <Loading /> : detailError ? <div className="p-4"><ErrorState message={t("The selected topology detail could not be loaded.")} /></div> : (
        <div className="space-y-4 p-4">
          <MetricStrip metrics={metrics} />
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h4 className="label">{t("TPS over time")} · {t("5-minute buckets")}</h4>
              <span className="font-mono text-[10px] text-sky-300">{tpsSeries.length} {t("points")}</span>
            </div>
            {tpsSeries.length ? (
              <TpsLineGraph data={tpsSeries} />
            ) : (
              <div className="grid h-24 place-items-center rounded border border-dashed border-[#303449] bg-[#10121c] px-4 text-center text-xs text-[#64748b]" data-testid="topology-tps-empty">{t("No TPS samples are available for this object and time window.")}</div>
            )}
          </section>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MetricCard label={t("Requests")} value={n(metrics.request_count, 0)} detail={t("Observed in window")} accent="sky" />
            <MetricCard label={t("p99 latency")} value={`${n(metrics.p99_latency_ms, 1)} ms`} detail={`p50 ${n(metrics.p50_latency_ms, 1)} ms`} accent="violet" />
            <MetricCard label={t("Request bytes")} value={n(metrics.request_bytes, 0)} detail={`${n(metrics.average_request_bytes, 0)} ${t("avg/request")}`} accent="cyan" />
            <MetricCard label={t("Response bytes")} value={n(metrics.response_bytes, 0)} detail={`${n(metrics.average_response_bytes, 0)} ${t("avg/response")}`} accent="indigo" />
          </div>
          <section><h4 className="label mb-2">{t("Reliability")}</h4><div className="grid grid-cols-2 gap-2 text-xs"><div className="rounded border border-[#303449] p-2"><span className="text-[#94a3b8]">4xx</span><strong className="ml-2 text-amber-300">{pct(metrics.http_4xx_rate)}</strong></div><div className="rounded border border-[#303449] p-2"><span className="text-[#94a3b8]">5xx</span><strong className="ml-2 text-rose-300">{pct(metrics.http_5xx_rate)}</strong></div><div className="rounded border border-[#303449] p-2"><span className="text-[#94a3b8]">{t("Timeouts")}</span><strong className="ml-2 text-white">{n(metrics.timeout_count, 0)}</strong></div><div className="rounded border border-[#303449] p-2"><span className="text-[#94a3b8]">{t("Anonymous")}</span><strong className="ml-2 text-cyan-300">{n(metrics.anonymous_requests, 0)}</strong></div></div></section>
          <section><h4 className="label mb-2">{t("Evidence & change")}</h4><div className="space-y-2 text-xs text-[#cbd5e1]"><div className="flex items-center justify-between"><span>{t("Observation")}</span><span className={`rounded border px-2 py-0.5 font-bold ${metrics.evidence_type === "direct" ? "border-emerald-400/50 text-emerald-300" : "border-violet-400/50 text-violet-300"}`}>{metrics.evidence_type} · {Math.round(metrics.confidence * 100)}%</span></div><div className="flex items-center justify-between"><span>{t("Current vs previous")}</span><span className={`rounded border px-2 py-0.5 font-bold uppercase ${statusTone(metrics.change?.status)}`}>{metrics.change?.status || "normal"}</span></div><div className="text-[#94a3b8]">{metrics.evidence_types?.join(" · ") || t("No evidence detail")}</div></div></section>
          <section><h4 className="label mb-2">{t("Observed time")}</h4><div className="grid grid-cols-2 gap-2 text-[11px] text-[#cbd5e1]"><div><span className="block text-[#94a3b8]">{t("First seen")}</span>{formatTime(metrics.first_seen_ms)}</div><div><span className="block text-[#94a3b8]">{t("Last seen")}</span>{formatTime(metrics.last_seen_ms)}</div></div></section>
          {selection.kind === "node" && selection.node.type === "principal" && (
            <section><div className="mb-2 flex items-center justify-between"><h4 className="label">{t("Source IP context")}</h4>{ipLoading && <RefreshCw size={13} className="animate-spin text-cyan-300" />}</div><div className="overflow-x-auto"><table className="w-full text-left text-[11px]"><thead><tr className="border-b border-[#303449] text-[#94a3b8]"><th className="px-1 py-2">IP</th><th className="px-1 py-2">TPS</th><th className="px-1 py-2">{t("Role")}</th><th className="px-1 py-2">{t("Status")}</th></tr></thead><tbody>{ips?.items.map((item) => <tr key={`${item.source_ip}-${item.service}-${item.api}`} className="border-b border-[#24283a]"><td className="px-1 py-2 font-mono text-white">{item.source_ip}</td><td className="px-1 py-2 text-sky-300">{n(item.tps, 2)}</td><td className="px-1 py-2"><span className={item.is_load_balancer ? "text-amber-300" : "text-emerald-300"}>{item.role_label}</span></td><td className="px-1 py-2">{item.is_new_ip ? <span className="text-cyan-300">{t("NEW IP")}</span> : <span className="text-[#94a3b8]">{t("Known")}</span>}</td></tr>)}</tbody></table></div>{!ips?.items.length && !ipLoading && <p className="py-3 text-xs text-[#94a3b8]">{t("No source IP evidence in this window.")}</p>}{ips?.next_cursor && <button type="button" className="btn mt-3 w-full" onClick={onLoadMoreIps}>{t("Load next IP page")}</button>}</section>
          )}
        </div>
      )}
    </aside>
  );
}

export function InteractiveTopologyPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const [mode, setMode] = useState<"service-first" | "user-first">("service-first");
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [expandedServiceId, setExpandedServiceId] = useState<string>();
  const [pathSelection, setPathSelection] = useState<{ service?: TopologyNode; api?: TopologyNode; principal?: TopologyNode }>({});
  const [selection, setSelection] = useState<Selection>(null);
  const [positions, setPositions] = useState<Record<string, Position>>({});
  const serviceLayoutSignatureRef = useRef<string | null>(null);
  const [ipCursor, setIpCursor] = useState<string | undefined>();
  const [ipItems, setIpItems] = useState<IpPage["items"]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [apiSearch, setApiSearch] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [serviceSearch, setServiceSearch] = useState("");
  const [reverseApiSearch, setReverseApiSearch] = useState("");
  const [focusRequest, setFocusRequest] = useState<{ nodeId: string; token: number }>();
  const sliderEndMs = useMemo(() => Math.floor(Date.now() / FIVE_MINUTE_MS) * FIVE_MINUTE_MS, []);
  const sliderStartMs = sliderEndMs - SEVEN_DAY_SLICES * FIVE_MINUTE_MS;
  const [timeSliceIndex, setTimeSliceIndex] = useState(SEVEN_DAY_SLICES - 1);
  const [sliderPreviewIndex, setSliderPreviewIndex] = useState(SEVEN_DAY_SLICES - 1);
  const selectedStartMs = sliderStartMs + timeSliceIndex * FIVE_MINUTE_MS;
  const selectedEndMs = selectedStartMs + FIVE_MINUTE_MS;
  const previewStartMs = sliderStartMs + sliderPreviewIndex * FIVE_MINUTE_MS;
  const previewEndMs = previewStartMs + FIVE_MINUTE_MS;
  const qs = queryString(filters, { window: "5m", start: String(selectedStartMs), end: String(selectedEndMs) });
  const sliderTimeFormatter = useMemo(() => new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: filters.timezone === "local" ? undefined : filters.timezone,
  }), [filters.timezone]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchTerm.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [searchTerm]);

  const searchPath = debouncedSearch.length >= 2
    ? "/api/v1/topology/search?q=" + encodeURIComponent(debouncedSearch) + "&limit=20&" + queryString(filters, { window: "7d", start: String(sliderStartMs), end: String(sliderEndMs) })
    : "";
  const searchQuery = useQuery({
    queryKey: ["interactive-topology-search", searchPath],
    queryFn: ({ signal }) => api<SearchResponse>(searchPath, { signal }),
    enabled: !!searchPath,
  });
  const graphQuery = useQuery({
    queryKey: ["interactive-topology-services", qs],
    queryFn: ({ signal }) => api<TopologyResponse>("/api/v1/topology/services?" + qs, { signal }),
  });
  const services = useMemo(() => (graphQuery.data?.nodes || []).filter((node) => node.type === "service"), [graphQuery.data?.nodes]);
  const graphEdges = graphQuery.data?.edges || [];
  const serviceLayoutSignature = useMemo(() => {
    const nodePart = services.map((node) => node.id).sort().join("|");
    const edgePart = graphEdges.map((edge) => `${edge.source}>${edge.target}`).sort().join("|");
    return `${nodePart}::${edgePart}`;
  }, [services, graphEdges]);

  useEffect(() => {
    if (serviceLayoutSignatureRef.current === serviceLayoutSignature) return;
    serviceLayoutSignatureRef.current = serviceLayoutSignature;
    const calculated = layoutServiceGraph(services, graphEdges);
    const activeServiceIds = new Set(services.map((service) => service.id));
    setPositions((current) => {
      const next = { ...current };
      let changed = false;
      for (const nodeId of Object.keys(next)) {
        if (nodeId.startsWith("service:") && !activeServiceIds.has(nodeId)) {
          delete next[nodeId];
          changed = true;
        }
      }
      for (const service of services) {
        if (!Object.prototype.hasOwnProperty.call(next, service.id) && calculated[service.id]) {
          next[service.id] = calculated[service.id];
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [serviceLayoutSignature]);

  function pageUrl(base: string, search: string, cursor?: string) {
    const params = new URLSearchParams(qs);
    params.set("limit", "100");
    if (search.trim().length >= 2) params.set("search", search.trim());
    if (cursor) params.set("cursor", cursor);
    return base + "?" + params.toString();
  }

  const apiListBase = mode === "service-first"
    ? (expandedServiceId ? "/api/v1/topology/services/" + encodeURIComponent(pathSelection.service?.name || expandedServiceId.replace(/^service:/, "")) + "/apis" : "")
    : (pathSelection.principal && pathSelection.service
      ? "/api/v1/topology/users/" + encodeURIComponent(pathSelection.principal.name) + "/services/" + encodeURIComponent(pathSelection.service.name) + "/apis"
      : "");
  const apiListSearch = mode === "service-first" ? apiSearch : reverseApiSearch;
  const apiListQuery = useInfiniteQuery({
    queryKey: ["interactive-topology-api-list", mode, apiListBase, apiListSearch, qs],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => api<TopologyResponse>(pageUrl(apiListBase, apiListSearch, pageParam), { signal }),
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
    enabled: !!apiListBase,
  });
  const apiItems = apiListQuery.data?.pages.flatMap((page) => page.nodes || []) || [];

  const principalListBase = mode === "service-first" && pathSelection.service && pathSelection.api
    ? "/api/v1/topology/services/" + encodeURIComponent(pathSelection.service.name) + "/apis/" + encodeURIComponent(pathSelection.api.api || pathSelection.api.name) + "/principals"
    : "";
  const principalListQuery = useInfiniteQuery({
    queryKey: ["interactive-topology-api-users", principalListBase, userSearch, qs],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => api<TopologyResponse>(pageUrl(principalListBase, userSearch, pageParam), { signal }),
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
    enabled: !!principalListBase,
  });
  const principalItems = principalListQuery.data?.pages.flatMap((page) => page.nodes || []) || [];

  const userDirectoryQuery = useInfiniteQuery({
    queryKey: ["interactive-topology-user-directory", serviceSearch, qs],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => api<PrincipalDirectoryResponse>(pageUrl("/api/v1/topology/users", serviceSearch, pageParam), { signal }),
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
    enabled: mode === "user-first",
  });
  const directoryItems = userDirectoryQuery.data?.pages.flatMap((page) => page.items || []) || [];

  const userServicesBase = mode === "user-first" && pathSelection.principal
    ? "/api/v1/topology/users/" + encodeURIComponent(pathSelection.principal.name) + "/services"
    : "";
  const userServicesQuery = useInfiniteQuery({
    queryKey: ["interactive-topology-user-services", userServicesBase, serviceSearch, qs],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => api<TopologyResponse>(pageUrl(userServicesBase, serviceSearch, pageParam), { signal }),
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
    enabled: !!userServicesBase,
  });
  const userServiceItems = userServicesQuery.data?.pages.flatMap((page) => page.nodes || []) || [];

  const selectedNode = selection?.kind === "node" ? selection.node : undefined;
  const scopedPrincipal = selectedNode?.type === "principal" ? selectedNode.name : selectedNode?.principal;
  const scopedService = selectedNode?.type === "service" ? selectedNode.name : selectedNode?.service;
  const scopedApi = selectedNode?.type === "api" ? selectedNode.api || selectedNode.name : selectedNode?.api;
  const focusedPath = scopedPrincipal
    ? "/api/v1/topology/principals/" + encodeURIComponent(scopedPrincipal) + "/connections?" + queryString(filters, {
        window: "5m", start: String(selectedStartMs), end: String(selectedEndMs),
        ...(scopedService ? { service: scopedService } : {}),
        ...(scopedApi ? { api: scopedApi } : {}),
      })
    : selectedNode?.type === "api" && scopedService && scopedApi
      ? "/api/v1/topology/services/" + encodeURIComponent(scopedService) + "/api-connections?" + queryString(filters, {
          window: "5m", start: String(selectedStartMs), end: String(selectedEndMs), api: scopedApi,
        })
      : "";
  const focusedQuery = useQuery({
    queryKey: ["interactive-topology-focused-connections", focusedPath],
    queryFn: ({ signal }) => api<TopologyResponse>(focusedPath, { signal }),
    enabled: !!focusedPath,
  });
  const focusedEdges = focusedQuery.data?.edges || [];
  const focusedEdgeMetrics = new Map(focusedEdges.map((edge) => [edge.id, edge.metrics]));
  const detailPath = selectedNode?.type === "service"
    ? "/api/v1/topology/services/" + encodeURIComponent(selectedNode.name) + "/metrics"
    : selectedNode?.type === "api"
      ? "/api/v1/topology/apis/" + encodeURIComponent(selectedNode.api || selectedNode.name) + "/metrics?service=" + encodeURIComponent(selectedNode.service || "")
      : selectedNode?.type === "principal"
        ? "/api/v1/topology/principals/" + encodeURIComponent(selectedNode.name) + "/metrics"
        : "";
  const detailQuery = useQuery({
    queryKey: ["interactive-topology-detail", detailPath, qs],
    queryFn: ({ signal }) => api<DetailResponse>(detailPath + (detailPath.includes("?") ? "&" : "?") + qs, { signal }),
    enabled: !!detailPath,
  });
  const principalPath = selectedNode?.type === "principal"
    ? "/api/v1/topology/principals/" + encodeURIComponent(selectedNode.name) + "/ips?" + qs + "&page_size=50" + (ipCursor ? "&cursor=" + encodeURIComponent(ipCursor) : "")
    : "";
  const ipQuery = useQuery({
    queryKey: ["interactive-topology-ips", principalPath],
    queryFn: ({ signal }) => api<IpPage>(principalPath, { signal }),
    enabled: !!principalPath,
  });
  useEffect(() => {
    if (!selectedNode || selectedNode.type !== "principal") {
      setIpItems([]);
      setIpCursor(undefined);
      return;
    }
    if (ipQuery.data) setIpItems((current) => ipCursor ? [...current, ...ipQuery.data!.items] : ipQuery.data!.items);
  }, [ipQuery.data, ipCursor, selectedNode]);

  const highlightedEdgeIds = useMemo(() => {
    if (selection?.kind === "edge") return new Set([selection.edge.id]);
    if (selection?.kind !== "node") return new Set<string>();
    if (focusedPath && focusedQuery.data) return new Set(focusedEdges.map((edge) => edge.id));
    const node = selection.node;
    if (node.edge_ids) return new Set(node.edge_ids);
    if (node.type === "service") {
      return new Set(graphEdges.filter((edge) => edge.source === node.id || edge.target === node.id).map((edge) => edge.id));
    }
    if (node.type === "principal" && mode === "user-first") {
      return new Set(userServiceItems.flatMap((item) => item.edge_ids || []));
    }
    return new Set<string>();
  }, [selection, focusedPath, focusedQuery.data, focusedEdges, graphEdges, mode, userServiceItems]);

  function select(next: Selection) {
    setSelection(next);
    setIpCursor(undefined);
    setIpItems([]);
  }

  function dismissPanels() {
    setDirectoryOpen(false);
    setExpandedServiceId(undefined);
    setPathSelection({});
    setApiSearch("");
    setUserSearch("");
    setServiceSearch("");
    setReverseApiSearch("");
  }

  function clearNavigation() {
    dismissPanels();
    select(null);
  }

  function changeMode(nextMode: "service-first" | "user-first") {
    if (mode === nextMode) {
      if (nextMode === "user-first") setDirectoryOpen(true);
      return;
    }
    setMode(nextMode);
    clearNavigation();
    setDirectoryOpen(nextMode === "user-first");
  }

  function toggleExpand(node: TopologyNode) {
    if (expandedServiceId === node.id) {
      setExpandedServiceId(undefined);
      setPathSelection({});
      select(null);
      return;
    }
    setExpandedServiceId(node.id);
    setPathSelection({ service: node });
    setApiSearch("");
    setUserSearch("");
    select({ kind: "node", node });
  }

  function chooseApi(node: TopologyNode) {
    const service = pathSelection.service || services.find((item) => item.name === node.service);
    if (!service) return;
    setPathSelection({ service, api: node });
    select({ kind: "node", node });
  }

  function chooseApiPrincipal(node: TopologyNode) {
    setPathSelection((current) => ({ ...current, principal: node }));
    select({ kind: "node", node });
  }

  function chooseDirectoryPrincipal(node: TopologyNode) {
    setPathSelection({ principal: node });
    setServiceSearch("");
    select({ kind: "node", node });
  }

  function chooseUserService(node: TopologyNode) {
    setPathSelection((current) => ({ principal: current.principal, service: node }));
    setReverseApiSearch("");
    select({ kind: "node", node });
  }

  function chooseReverseApi(node: TopologyNode) {
    setPathSelection((current) => ({ ...current, api: node }));
    select({ kind: "node", node });
  }

  function relayout() {
    const calculated = layoutServiceGraph(services, graphEdges);
    const activeServiceIds = new Set(services.map((service) => service.id));
    setPositions((current) => {
      const next = { ...current };
      for (const nodeId of Object.keys(next)) {
        if (nodeId.startsWith("service:") && !activeServiceIds.has(nodeId)) delete next[nodeId];
      }
      for (const service of services) {
        if (calculated[service.id]) next[service.id] = calculated[service.id];
      }
      return next;
    });
  }

  function commitTimeSlice(index: number) {
    setTimeSliceIndex(index);
    setExpandedServiceId(undefined);
    setPathSelection({});
    select(null);
  }

  function travelTo(node: TopologyNode) {
    const lastSeen = node.metrics.last_seen_ms || selectedEndMs - 1;
    const index = Math.max(0, Math.min(SEVEN_DAY_SLICES - 1, Math.floor((lastSeen - sliderStartMs) / FIVE_MINUTE_MS)));
    setSliderPreviewIndex(index);
    commitTimeSlice(index);
    if (node.type === "service") {
      setPathSelection({ service: node });
      select({ kind: "node", node });
      setFocusRequest({ nodeId: node.id, token: Date.now() });
    } else {
      const service = services.find((item) => item.name === node.service) || {
        id: "service:" + (node.service || "unknown"), name: node.service || "unknown",
        type: "service" as const, service: node.service, metrics: emptyMetrics(),
      };
      const apiNode = node.type === "api" ? node : {
        id: "api:" + service.name + ":" + (node.api || "unknown"),
        name: node.api || "unknown", type: "api" as const, service: service.name,
        api: node.api || "unknown", edge_ids: node.edge_ids || [], metrics: node.metrics,
      };
      setMode("service-first");
      setExpandedServiceId(service.id);
      setPathSelection({ service, api: apiNode, principal: node.type === "principal" ? node : undefined });
      select({ kind: "node", node });
      setFocusRequest({ nodeId: service.id, token: Date.now() });
    }
    setSearchTerm(node.name);
    setSearchOpen(false);
  }

  const anonymous = graphQuery.data?.anonymous;
  const apiSelectedId = pathSelection.api?.id;
  const principalSelectedId = pathSelection.principal?.id;
  const serviceSelectedId = pathSelection.service?.id;
  const panelsOpen = directoryOpen || !!expandedServiceId || !!pathSelection.principal;

  return (
    <main className="isolate relative h-full min-h-[600px] overflow-hidden border-t border-[#262838] bg-[#0c0d14]" onClickCapture={(event) => {
      if (panelsOpen && !(event.target as Element).closest("[data-testid='topology-drilldown-panel']")) dismissPanels();
    }}>
      {!graphQuery.isLoading && !graphQuery.isError && (
        <GraphSurface
          nodes={services}
          edges={graphEdges}
          positions={positions}
          selection={selection}
          highlightedEdgeIds={highlightedEdgeIds}
          focusedEdgeMetrics={focusedEdgeMetrics}
          onSelect={select}
          onClearSelection={clearNavigation}
          onMoveNode={(nodeId, position) => setPositions((current) => ({ ...current, [nodeId]: position }))}
          onToggleExpand={toggleExpand}
          expanded={new Set(expandedServiceId ? [expandedServiceId] : [])}
          expandEnabled={mode === "service-first"}
          focusRequest={focusRequest}
        />
      )}

      <div className="pointer-events-none absolute left-3 right-3 top-3 z-30 flex flex-col items-start gap-2 sm:flex-row sm:justify-between">
        <div className="pointer-events-auto w-[min(300px,calc(100vw-1.5rem))] rounded border border-[#303449] bg-[#141622] px-2.5 py-2">
          <h1 className="flex items-center gap-1.5 text-[13px] font-semibold tracking-tight text-white"><Network size={14} className="shrink-0 text-violet-300" />{t("Interactive Service Topology")}</h1>
          <p className="sr-only">{t("The graph shows services and their connections. Expand a service to browse APIs and users.")}</p>
          <div className="relative mt-1.5" onFocus={() => setSearchOpen(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setSearchOpen(false); }}>
            <Search size={13} className="pointer-events-none absolute left-2.5 top-2 text-[#64748b]" />
            <input type="search" value={searchTerm} onChange={(event) => { setSearchTerm(event.target.value); setSearchOpen(true); }} placeholder={t("Find service, API, or user...")} aria-label={t("Find service, API, or user")} data-testid="topology-search" className="h-7 w-full rounded border border-[#303449] bg-[#0f111b] pl-8 pr-2 text-[11px] text-white outline-none placeholder:text-[#64748b] focus:border-cyan-400" />
            {searchOpen && debouncedSearch.length >= 2 && (
              <div className="absolute left-0 top-8 z-40 max-h-56 w-full overflow-y-auto rounded border border-[#34384c] bg-[#141622] p-1" data-testid="topology-search-results">
                {searchQuery.isLoading && <div className="px-3 py-3 text-xs text-[#94a3b8]">{t("Searching...")}</div>}
                {!searchQuery.isLoading && !(searchQuery.data?.items.length) && <div className="px-3 py-3 text-xs text-[#94a3b8]">{t("No matching topology object in the last seven days.")}</div>}
                {searchQuery.data?.items.map((node) => (
                  <button key={node.id + "-" + node.service + "-" + node.api} type="button" data-topology-search-result="true" className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-[#202333] focus:bg-[#202333] focus:outline-none" onMouseDown={(event) => event.preventDefault()} onClick={() => travelTo(node)}>
                    <span className={"grid h-6 w-6 shrink-0 place-items-center rounded border border-[#303449] " + entityTone(node.type).soft + " " + entityTone(node.type).text}><NodeIcon type={node.type} /></span>
                    <span className="min-w-0 flex-1"><span className={"block truncate text-[11px] font-semibold " + entityTone(node.type).text}>{node.name}</span><span className="block truncate text-[9px] uppercase tracking-wider text-[#64748b]">{node.type === "principal" ? t("User") : t(node.type)}{node.service && node.type !== "service" ? " · " + node.service : ""}</span></span>
                    <span className="font-mono text-[9px] text-sky-300">{n(node.metrics.tps, 2)} tps</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="mt-1.5 flex rounded border border-[#303449] bg-[#10121c] p-0.5" role="group" aria-label={t("Topology navigation mode")}>
            <button type="button" data-testid="topology-mode-service-first" onClick={() => changeMode("service-first")} className={"min-w-0 flex-1 rounded px-1 py-1 text-[9px] font-medium " + (mode === "service-first" ? "bg-[#263043] text-cyan-200" : "text-[#94a3b8] hover:text-white")}>{t("Service → API → User")}</button>
            <button type="button" data-testid="topology-mode-user-first" onClick={() => changeMode("user-first")} className={"min-w-0 flex-1 rounded px-1 py-1 text-[9px] font-medium " + (mode === "user-first" ? "bg-[#263043] text-cyan-200" : "text-[#94a3b8] hover:text-white")}>{t("User → Service → API")}</button>
          </div>
        </div>

        <div className="pointer-events-auto flex flex-wrap items-start justify-end gap-1.5">
          <div className="relative">
            <button type="button" className="btn bg-[#141622]" onClick={() => setTimelineOpen((open) => !open)} aria-expanded={timelineOpen}><Clock size={13} /> {timelineOpen ? t("Hide history") : t("History")}</button>
            {timelineOpen && <div className="absolute right-0 top-8 w-[min(360px,calc(100vw-1.5rem))] rounded border border-[#303449] bg-[#141622] px-2.5 py-2" data-testid="topology-time-slider-panel">
              <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px] uppercase tracking-wider text-[#94a3b8]"><span>{t("Seven-day timeline")}</span><strong className="normal-case tracking-normal text-cyan-300" data-testid="topology-selected-window">{sliderTimeFormatter.format(previewStartMs)} – {sliderTimeFormatter.format(previewEndMs)}</strong></div>
              <input type="range" min={0} max={SEVEN_DAY_SLICES - 1} step={1} value={sliderPreviewIndex} data-testid="topology-time-slider" aria-label={t("Select a five-minute topology window within the last seven days")} className="h-2 w-full cursor-ew-resize accent-cyan-400" onChange={(event) => setSliderPreviewIndex(Number(event.target.value))} onPointerUp={(event) => commitTimeSlice(Number(event.currentTarget.value))} onKeyUp={(event) => commitTimeSlice(Number(event.currentTarget.value))} />
              <div className="mt-1 flex items-center justify-between font-mono text-[9px] text-[#64748b]"><span>{sliderTimeFormatter.format(sliderStartMs)}</span><span className="text-[#94a3b8]">{t("5-minute window")}</span><span>{t("Now")}</span></div>
            </div>}
          </div>
          <button type="button" className="btn bg-[#141622]" onClick={relayout}><Maximize2 size={13} /> {t("Re-layout")}</button>
          <button type="button" className="btn bg-[#141622]" onClick={() => { void graphQuery.refetch(); }}><RefreshCw size={13} /> {t("Refresh")}</button>
        </div>
      </div>

      {graphQuery.isLoading && <div className="absolute inset-0 grid place-items-center"><Loading /></div>}
      {graphQuery.isError && <div className="absolute inset-0 grid place-items-center p-8"><ErrorState message={t("Topology data is unavailable. Check the configured trace backend and worker aggregation status.")} /></div>}

      <div className="pointer-events-none absolute left-3 top-44 z-20 flex max-w-[calc(100vw-1.5rem)] flex-col items-start gap-1.5 pb-1 sm:top-28">
        {mode === "user-first" && !directoryOpen && <button type="button" className="btn pointer-events-auto bg-[#141622]" onClick={() => setDirectoryOpen(true)}><UserRound size={13} /> {t("Users")}</button>}
        {mode === "user-first" && directoryOpen && <RelationshipListPanel key="user-directory" title={t("Users")} items={directoryItems} selectedId={principalSelectedId} loading={userDirectoryQuery.isLoading} error={userDirectoryQuery.isError} search={serviceSearch} onSearch={setServiceSearch} onSelect={chooseDirectoryPrincipal} onClose={dismissPanels} hasMore={!!userDirectoryQuery.hasNextPage} onLoadMore={() => { void userDirectoryQuery.fetchNextPage(); }} />}
        {mode === "user-first" && pathSelection.principal && <RelationshipListPanel key="user-services" title={pathSelection.principal.name + " · " + t("Services")} items={userServiceItems} selectedId={serviceSelectedId} loading={userServicesQuery.isLoading} error={userServicesQuery.isError} search={serviceSearch} onSearch={setServiceSearch} onSelect={chooseUserService} onClose={dismissPanels} hasMore={!!userServicesQuery.hasNextPage} onLoadMore={() => { void userServicesQuery.fetchNextPage(); }} />}
        {apiListBase && <RelationshipListPanel key="api-list" title={(mode === "service-first" ? pathSelection.service?.name : pathSelection.service?.name) + " · " + t("APIs")} items={apiItems} selectedId={apiSelectedId} loading={apiListQuery.isLoading} error={apiListQuery.isError} search={mode === "service-first" ? apiSearch : reverseApiSearch} onSearch={mode === "service-first" ? setApiSearch : setReverseApiSearch} onSelect={mode === "service-first" ? chooseApi : chooseReverseApi} onClose={dismissPanels} hasMore={!!apiListQuery.hasNextPage} onLoadMore={() => { void apiListQuery.fetchNextPage(); }} />}
        {principalListBase && <RelationshipListPanel key="api-users" title={pathSelection.api?.name + " · " + t("Users")} items={principalItems} selectedId={principalSelectedId} loading={principalListQuery.isLoading} error={principalListQuery.isError} search={userSearch} onSearch={setUserSearch} onSelect={chooseApiPrincipal} onClose={dismissPanels} hasMore={!!principalListQuery.hasNextPage} onLoadMore={() => { void principalListQuery.fetchNextPage(); }} />}
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 z-20 flex max-w-[calc(100%-1.5rem)] flex-wrap items-stretch gap-1 text-[10px]">
        <div className="pointer-events-auto flex items-center gap-2 rounded border border-[#303449] bg-[#141622] px-2 py-1 text-[#cbd5e1]">
          <span className="font-medium text-cyan-300">{mode === "service-first" ? t("Service → API → User") : t("User → Service → API")}</span>
          <span className="font-mono text-[9px] uppercase tracking-wider text-[#64748b]">{graphQuery.data?.backend || "clickhouse"}</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-5 border-t-2 border-[#5794c8] opacity-60" />{t("Service connection")}</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-5 border-t-[3px] border-yellow-400" />{t("Selected path")}</span>
        </div>
        <div className="pointer-events-auto flex items-center divide-x divide-[#303449] rounded border border-[#303449] bg-[#141622] text-[#94a3b8]">
          <span className="px-2 py-1">{t("New relationships")} <strong className="ml-1 font-mono text-cyan-300">{n(graphQuery.data?.changes?.new_edges?.length, 0)}</strong></span>
          <span className="px-2 py-1">{t("Disappeared")} <strong className="ml-1 font-mono text-rose-300">{n(graphQuery.data?.changes?.disappeared_edges?.length, 0)}</strong></span>
          <span className="px-2 py-1">{t("Baseline")} <strong className="ml-1 font-normal text-[#cbd5e1]">{graphQuery.data?.changes?.baseline || "insufficient history"}</strong></span>
        </div>
        {anonymous && <div className="pointer-events-auto flex items-center gap-2 rounded border border-amber-500/30 bg-[#141622] px-2 py-1 text-[#94a3b8]"><span>{t("Identified")} <strong className="ml-1 text-cyan-300">{n(anonymous.identified_request_percentage, 1)}%</strong></span><span>{t("Anonymous")} <strong className="ml-1 text-amber-300">{n(anonymous.anonymous_request_percentage, 1)}%</strong></span><span>{t("Anonymous TPS")} <strong className="ml-1 text-sky-300">{n(anonymous.anonymous_tps, 2)}</strong></span></div>}
      </div>

      <DetailPanel
        selection={selection}
        detail={detailQuery.data}
        detailLoading={detailQuery.isLoading}
        detailError={detailQuery.isError}
        ips={selectedNode?.type === "principal" ? { principal: selectedNode.name, items: ipItems, next_cursor: ipQuery.data?.next_cursor } : undefined}
        ipLoading={ipQuery.isLoading}
        onLoadMoreIps={() => { if (ipQuery.data?.next_cursor) setIpCursor(ipQuery.data.next_cursor); }}
        onClose={() => select(null)}
      />
    </main>
  );
}
