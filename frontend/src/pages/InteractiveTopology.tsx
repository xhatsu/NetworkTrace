import { useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
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

type Position = { x: number; y: number };

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

function rootPosition(index: number, total: number): Position {
  const columns = Math.max(2, Math.ceil(Math.sqrt(Math.max(total, 1))));
  const row = Math.floor(index / columns);
  const col = index % columns;
  return { x: 100 + col * (760 / Math.max(1, columns - 1)), y: 105 + row * 155 };
}

function childPosition(parent: Position, index: number, total: number, vertical = false): Position {
  const angle = -Math.PI / 2 + (Math.PI * (index + 1)) / (total + 1);
  const radius = vertical ? 170 : 150;
  return { x: parent.x + Math.cos(angle) * radius, y: parent.y + Math.sin(angle) * radius };
}

function statusTone(status?: string) {
  if (status === "new") return "border-cyan-400/60 bg-cyan-400/10 text-cyan-300";
  if (status === "disappeared") return "border-rose-400/60 bg-rose-400/10 text-rose-300";
  if (status === "changed") return "border-amber-400/60 bg-amber-400/10 text-amber-300";
  return "border-[#303449] bg-[#1a1d2c] text-[#94a3b8]";
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
  const metricClass = vertical ? "flex items-center justify-between gap-3 border-t border-[#292d3e] py-1 first:border-t-0" : "";
  return (
    <div className={vertical ? "flex flex-col" : "grid grid-cols-2 gap-2 sm:grid-cols-4"}>
      <div className={metricClass}><div className="label">TPS</div><div className="font-mono text-sm text-sky-300">{n(metrics.tps, 2)}</div></div>
      <div className={metricClass}><div className="label">p95</div><div className="font-mono text-sm text-violet-300">{n(metrics.p95_latency_ms, 1)} ms</div></div>
      <div className={metricClass}><div className="label">Errors</div><div className={`font-mono text-sm ${metrics.error_rate > 0.05 ? "text-rose-300" : "text-emerald-300"}`}>{pct(metrics.error_rate)}</div></div>
      <div className={metricClass}><div className="label">Change</div><div className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${statusTone(metrics.change?.status)}`}>{metrics.change?.status || "normal"}</div></div>
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
        {coordinates.length > 1 && <path d={smoothPath} fill="none" stroke="#38bdf8" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
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
  onSelect,
  onClearSelection,
  onMoveNode,
  onToggleExpand,
  expanded,
  focusRequest,
}: {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  positions: Record<string, Position>;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  onClearSelection: () => void;
  onMoveNode: (nodeId: string, position: Position) => void;
  onToggleExpand: (node: TopologyNode) => void;
  expanded: Set<string>;
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

  const orderedEdges = selection?.kind === "edge"
    ? [...edges].sort((left, right) => Number(left.id === selection.edge.id) - Number(right.id === selection.edge.id))
    : edges;

  return (
    <div
      ref={surfaceRef}
      className="absolute inset-0 touch-none overflow-hidden bg-[#0c0d14] cursor-grab active:cursor-grabbing"
      aria-label="Interactive service topology"
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
        </defs>
        {orderedEdges.map((edge) => {
          const source = positions[edge.source];
          const target = positions[edge.target];
          if (!source || !target) return null;
          const selected = selection?.kind === "edge" && selection.edge.id === edge.id;
          return (
            <g key={edge.id} data-topology-object="true" data-api-connection={edge.id.startsWith("api-service-edge:") ? "true" : undefined} onClick={(event) => { event.stopPropagation(); onSelect({ kind: "edge", edge }); }} className="cursor-pointer">
              <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="transparent" strokeWidth="16" />
              <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke={selected ? "#f8fafc" : edge.inferred ? "#818cf8" : "#38bdf8"} strokeWidth={selected ? 4 : Math.min(8, 1.5 + Math.sqrt(edge.metrics.request_count || 1) / 7)} strokeDasharray={edge.inferred ? "7 6" : undefined} markerEnd="url(#topology-arrow)" opacity={selected ? 1 : .78} />
              <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 8} fill={selected ? "#f8fafc" : "#94a3b8"} fontSize="11" textAnchor="middle">{n(edge.metrics.tps, 1)} tps</text>
            </g>
          );
        })}
      </svg>
      {nodes.map((node) => {
        const pos = positions[node.id];
        if (!pos) return null;
        const canExpand = node.type !== "principal";
        const expandedKey = node.type === "service" ? node.id : `${node.service}|${node.api}`;
        const isExpanded = expanded.has(expandedKey);
        const isSelected = selection?.kind === "node" && selection.node.id === node.id;
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
              onDoubleClick={() => canExpand && onToggleExpand(node)}
              className={`group w-full rounded-lg border bg-[#171a28] px-3 py-2 text-left transition hover:border-cyan-400/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${isSelected ? "border-white ring-1 ring-white/70" : node.metrics.change?.status === "new" ? "border-cyan-400/70" : node.metrics.change?.status === "changed" ? "border-amber-400/70" : "border-[#303449]"}`}
              aria-label={`Inspect ${node.type} ${node.name}${canExpand ? ". Double click to expand." : ""}`}
            >
              <span className="flex items-center gap-2 text-xs font-semibold text-white"><NodeIcon type={node.type} /><span className="truncate">{node.name}</span></span>
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
      <div className="absolute left-4 top-56 z-20 flex flex-col overflow-hidden rounded-lg border border-[#303449] bg-[#141622]" data-topology-object="true" aria-label={t("Canvas navigation controls")}>
        <button type="button" data-testid="topology-zoom-in" className="grid h-9 w-10 place-items-center text-[#cbd5e1] hover:bg-[#202333] hover:text-white" onClick={(event) => { event.stopPropagation(); changeZoom(0.1); }} aria-label={t("Zoom in")} title={t("Zoom in")}><ZoomIn size={16} /></button>
        <button type="button" data-testid="topology-reset-view" className="border-y border-[#303449] px-1 py-1.5 font-mono text-[10px] font-semibold text-cyan-300" onClick={(event) => { event.stopPropagation(); resetViewport(); }} aria-label={t("Reset canvas view")} title={t("Reset canvas view")}>{Math.round(zoom * 100)}%</button>
        <button type="button" data-testid="topology-zoom-out" className="grid h-9 w-10 place-items-center text-[#cbd5e1] hover:bg-[#202333] hover:text-white" onClick={(event) => { event.stopPropagation(); changeZoom(-0.1); }} aria-label={t("Zoom out")} title={t("Zoom out")}><ZoomOut size={16} /></button>
      </div>
    </div>
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
    <aside className="absolute bottom-4 right-4 top-20 z-30 w-[min(380px,calc(100%-2rem))] overflow-y-auto rounded-lg border border-[#34384c] bg-[#141622]" aria-label="Topology object details" data-testid="topology-inspector">
      <div className="sticky top-0 z-10 flex items-start justify-between border-b border-[#262838] bg-[#181a28] px-4 py-3">
        <div><div className="label">{entity.type}</div><h3 className="mt-1 max-w-[270px] break-words text-base font-semibold text-white">{entity.name}</h3></div>
        <button type="button" onClick={onClose} className="btn px-2" aria-label="Close topology detail panel"><X size={14} /></button>
      </div>
      {detailLoading ? <Loading /> : detailError ? <div className="p-4"><ErrorState message="The selected topology detail could not be loaded." /></div> : (
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
            <MetricCard label="Requests" value={n(metrics.request_count, 0)} detail="Observed in window" accent="sky" />
            <MetricCard label="p99 latency" value={`${n(metrics.p99_latency_ms, 1)} ms`} detail={`p50 ${n(metrics.p50_latency_ms, 1)} ms`} accent="violet" />
            <MetricCard label="Request bytes" value={n(metrics.request_bytes, 0)} detail={`${n(metrics.average_request_bytes, 0)} avg/request`} accent="cyan" />
            <MetricCard label="Response bytes" value={n(metrics.response_bytes, 0)} detail={`${n(metrics.average_response_bytes, 0)} avg/response`} accent="indigo" />
          </div>
          <section><h4 className="label mb-2">Reliability</h4><div className="grid grid-cols-2 gap-2 text-xs"><div className="rounded border border-[#303449] p-2"><span className="text-[#94a3b8]">4xx</span><strong className="ml-2 text-amber-300">{pct(metrics.http_4xx_rate)}</strong></div><div className="rounded border border-[#303449] p-2"><span className="text-[#94a3b8]">5xx</span><strong className="ml-2 text-rose-300">{pct(metrics.http_5xx_rate)}</strong></div><div className="rounded border border-[#303449] p-2"><span className="text-[#94a3b8]">Timeouts</span><strong className="ml-2 text-white">{n(metrics.timeout_count, 0)}</strong></div><div className="rounded border border-[#303449] p-2"><span className="text-[#94a3b8]">Anonymous</span><strong className="ml-2 text-cyan-300">{n(metrics.anonymous_requests, 0)}</strong></div></div></section>
          <section><h4 className="label mb-2">Evidence & change</h4><div className="space-y-2 text-xs text-[#cbd5e1]"><div className="flex items-center justify-between"><span>Observation</span><span className={`rounded border px-2 py-0.5 font-bold ${metrics.evidence_type === "direct" ? "border-emerald-400/50 text-emerald-300" : "border-violet-400/50 text-violet-300"}`}>{metrics.evidence_type} · {Math.round(metrics.confidence * 100)}%</span></div><div className="flex items-center justify-between"><span>Current vs previous</span><span className={`rounded border px-2 py-0.5 font-bold uppercase ${statusTone(metrics.change?.status)}`}>{metrics.change?.status || "normal"}</span></div><div className="text-[#94a3b8]">{metrics.evidence_types?.join(" · ") || "No evidence detail"}</div></div></section>
          <section><h4 className="label mb-2">Observed time</h4><div className="grid grid-cols-2 gap-2 text-[11px] text-[#cbd5e1]"><div><span className="block text-[#94a3b8]">First seen</span>{formatTime(metrics.first_seen_ms)}</div><div><span className="block text-[#94a3b8]">Last seen</span>{formatTime(metrics.last_seen_ms)}</div></div></section>
          {selection.kind === "node" && selection.node.type === "principal" && (
            <section><div className="mb-2 flex items-center justify-between"><h4 className="label">Source IP context</h4>{ipLoading && <RefreshCw size={13} className="animate-spin text-cyan-300" />}</div><div className="overflow-x-auto"><table className="w-full text-left text-[11px]"><thead><tr className="border-b border-[#303449] text-[#94a3b8]"><th className="px-1 py-2">IP</th><th className="px-1 py-2">TPS</th><th className="px-1 py-2">Role</th><th className="px-1 py-2">Status</th></tr></thead><tbody>{ips?.items.map((item) => <tr key={`${item.source_ip}-${item.service}-${item.api}`} className="border-b border-[#24283a]"><td className="px-1 py-2 font-mono text-white">{item.source_ip}</td><td className="px-1 py-2 text-sky-300">{n(item.tps, 2)}</td><td className="px-1 py-2"><span className={item.is_load_balancer ? "text-amber-300" : "text-emerald-300"}>{item.role_label}</span></td><td className="px-1 py-2">{item.is_new_ip ? <span className="text-cyan-300">NEW IP</span> : <span className="text-[#94a3b8]">Known</span>}</td></tr>)}</tbody></table></div>{!ips?.items.length && !ipLoading && <p className="py-3 text-xs text-[#94a3b8]">No source IP evidence in this window.</p>}{ips?.next_cursor && <button type="button" className="btn mt-3 w-full" onClick={onLoadMoreIps}>Load next IP page</button>}</section>
          )}
        </div>
      )}
    </aside>
  );
}

export function InteractiveTopologyPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const [expandedServices, setExpandedServices] = useState<Set<string>>(new Set());
  const [expandedApis, setExpandedApis] = useState<Set<string>>(new Set());
  const [selection, setSelection] = useState<Selection>(null);
  const [positions, setPositions] = useState<Record<string, Position>>({});
  const [ipCursor, setIpCursor] = useState<string | undefined>();
  const [ipItems, setIpItems] = useState<IpPage["items"]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [pendingTravel, setPendingTravel] = useState<TopologyNode | null>(null);
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
    ? `/api/v1/topology/search?q=${encodeURIComponent(debouncedSearch)}&limit=20&${queryString(filters, { window: "7d", start: String(sliderStartMs), end: String(sliderEndMs) })}`
    : "";
  const searchQuery = useQuery({
    queryKey: ["interactive-topology-search", searchPath],
    queryFn: () => api<SearchResponse>(searchPath),
    enabled: !!searchPath,
  });

  const graphQuery = useQuery({ queryKey: ["interactive-topology-services", qs], queryFn: () => api<TopologyResponse>(`/api/v1/topology/services?${qs}`) });
  const services = graphQuery.data?.nodes || [];
  const apiQueries = useQueries({ queries: Array.from(expandedServices).map((id) => {
    const service = id.replace(/^service:/, "");
    return { queryKey: ["interactive-topology-apis", service, qs], queryFn: () => api<TopologyResponse>(`/api/v1/topology/services/${encodeURIComponent(service)}/apis?${qs}`), enabled: !!service };
  }) });
  const apiNodes = apiQueries.flatMap((query) => query.data?.nodes || []);
  const principalQueries = useQueries({ queries: Array.from(expandedApis).map((key) => {
    const separator = key.indexOf("|");
    const service = key.slice(0, separator);
    const apiName = key.slice(separator + 1);
    return { queryKey: ["interactive-topology-principals", service, apiName, qs], queryFn: () => api<TopologyResponse>(`/api/v1/topology/services/${encodeURIComponent(service)}/apis/${encodeURIComponent(apiName)}/principals?${qs}`), enabled: !!service && !!apiName };
  }) });
  const principalNodes = principalQueries.flatMap((query) => query.data?.nodes || []);
  const selectedNode = selection?.kind === "node" ? selection.node : undefined;
  const selectedApi = selectedNode?.type === "api" ? selectedNode : undefined;
  const apiConnectionsPath = selectedApi
    ? `/api/v1/topology/services/${encodeURIComponent(selectedApi.service || "")}/api-connections?api=${encodeURIComponent(selectedApi.api || selectedApi.name)}&${qs}`
    : "";
  const apiConnectionsQuery = useQuery({
    queryKey: ["interactive-topology-api-connections", apiConnectionsPath],
    queryFn: () => api<TopologyResponse>(apiConnectionsPath),
    enabled: !!apiConnectionsPath,
  });
  const connectionNodes = selectedApi ? apiConnectionsQuery.data?.nodes || [] : [];
  const visibleNodes = Array.from(
    new Map([...services, ...apiNodes, ...principalNodes, ...connectionNodes].map((node) => [node.id, node])).values(),
  );
  const graphEdges = graphQuery.data?.edges || [];
  const visualEdges: TopologyEdge[] = [...graphEdges];
  apiNodes.forEach((node) => visualEdges.push({ id: `branch:${node.id}`, source: `service:${node.service}`, target: node.id, source_name: node.service || "service", target_name: node.name, metrics: node.metrics, evidence_type: "direct", direct: true, inferred: false }));
  principalNodes.forEach((node) => visualEdges.push({ id: `branch:${node.id}`, source: `api:${node.service}:${node.api}`, target: node.id, source_name: node.api || "api", target_name: node.name, metrics: node.metrics, evidence_type: "direct", direct: true, inferred: false }));
  if (selectedApi) visualEdges.push(...(apiConnectionsQuery.data?.edges || []));

  useEffect(() => {
    setPositions((current) => {
      const next = { ...current };
      services.forEach((node, index) => { if (!next[node.id]) next[node.id] = rootPosition(index, services.length); });
      apiNodes.forEach((node, index) => { if (!next[node.id]) { const parent = next[`service:${node.service}`] || rootPosition(index, Math.max(services.length, 1)); const siblings = apiNodes.filter((candidate) => candidate.service === node.service); next[node.id] = childPosition(parent, siblings.indexOf(node), siblings.length); } });
      principalNodes.forEach((node, index) => { if (!next[node.id]) { const parent = next[`api:${node.service}:${node.api}`] || rootPosition(index, Math.max(services.length, 1)); const siblings = principalNodes.filter((candidate) => candidate.service === node.service && candidate.api === node.api); next[node.id] = childPosition(parent, siblings.indexOf(node), siblings.length, true); } });
      connectionNodes.forEach((node, index) => { if (!next[node.id]) next[node.id] = rootPosition(index, Math.max(connectionNodes.length, 1)); });
      return next;
    });
  }, [services, apiNodes, principalNodes, connectionNodes]);

  useEffect(() => {
    if (!pendingTravel) return;
    const match = visibleNodes.find((node) => node.id === pendingTravel.id);
    if (!match || !positions[match.id]) return;
    select({ kind: "node", node: match });
    setFocusRequest({ nodeId: match.id, token: Date.now() });
    setPendingTravel(null);
  }, [pendingTravel, visibleNodes, positions]);

  const detailPath = selectedNode?.type === "service" ? `/api/v1/topology/services/${encodeURIComponent(selectedNode.name)}/metrics` : selectedNode?.type === "api" ? `/api/v1/topology/apis/${encodeURIComponent(selectedNode.api || selectedNode.name)}/metrics?service=${encodeURIComponent(selectedNode.service || "")}` : selectedNode?.type === "principal" ? `/api/v1/topology/principals/${encodeURIComponent(selectedNode.name)}/metrics` : "";
  const detailQuery = useQuery({ queryKey: ["interactive-topology-detail", detailPath, qs], queryFn: () => api<DetailResponse>(`${detailPath}${detailPath.includes("?") ? "&" : "?"}${qs}`), enabled: !!detailPath });
  const principalPath = selectedNode?.type === "principal" ? `/api/v1/topology/principals/${encodeURIComponent(selectedNode.name)}/ips?${qs}&page_size=50${ipCursor ? `&cursor=${encodeURIComponent(ipCursor)}` : ""}` : "";
  const ipQuery = useQuery({ queryKey: ["interactive-topology-ips", principalPath], queryFn: () => api<IpPage>(principalPath), enabled: !!principalPath });
  useEffect(() => {
    if (!selectedNode || selectedNode.type !== "principal") { setIpItems([]); setIpCursor(undefined); return; }
    if (ipQuery.data) setIpItems((current) => ipCursor ? [...current, ...ipQuery.data!.items] : ipQuery.data!.items);
  }, [ipQuery.data, ipCursor, selectedNode]);

  const anonymous = graphQuery.data?.anonymous;
  const expandedKeys = useMemo(() => new Set([...expandedServices, ...expandedApis]), [expandedServices, expandedApis]);

  function toggleExpand(node: TopologyNode) {
    if (node.type === "service") {
      setExpandedServices((current) => {
        const next = new Set(current);
        if (next.has(node.id)) {
          next.delete(node.id);
          setExpandedApis((apis) => new Set([...apis].filter((key) => !key.startsWith(`${node.name}|`))));
        } else {
          next.add(node.id);
        }
        return next;
      });
    } else if (node.type === "api") {
      const key = `${node.service}|${node.api}`;
      setExpandedApis((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; });
    }
  }

  function select(next: Selection) {
    setSelection(next);
    setIpCursor(undefined);
    setIpItems([]);
  }

  function relayout() {
    setPositions({});
  }

  function commitTimeSlice(index: number) {
    setTimeSliceIndex(index);
    setSelection(null);
    setIpCursor(undefined);
    setIpItems([]);
  }

  function travelTo(node: TopologyNode) {
    const lastSeen = node.metrics.last_seen_ms || selectedEndMs - 1;
    const index = Math.max(0, Math.min(SEVEN_DAY_SLICES - 1, Math.floor((lastSeen - sliderStartMs) / FIVE_MINUTE_MS)));
    setSliderPreviewIndex(index);
    commitTimeSlice(index);
    if (node.type === "api" || node.type === "principal") {
      setExpandedServices((current) => new Set(current).add(`service:${node.service}`));
    }
    if (node.type === "principal") {
      setExpandedApis((current) => new Set(current).add(`${node.service}|${node.api}`));
    }
    setPendingTravel(node);
    setSearchTerm(node.name);
    setSearchOpen(false);
  }

  return (
    <main className="isolate relative h-full min-h-[600px] overflow-hidden border-t border-[#262838] bg-[#0c0d14]">
      {!graphQuery.isLoading && !graphQuery.isError && (
        <GraphSurface
          nodes={visibleNodes}
          edges={visualEdges}
          positions={positions}
          selection={selection}
          onSelect={select}
          onClearSelection={() => select(null)}
          onMoveNode={(nodeId, position) => setPositions((current) => ({ ...current, [nodeId]: position }))}
          onToggleExpand={toggleExpand}
          expanded={expandedKeys}
          focusRequest={focusRequest}
        />
      )}

      <div className="pointer-events-none absolute left-4 right-4 top-4 z-20 flex items-start justify-between gap-4">
        <div className="pointer-events-auto max-w-md rounded-lg border border-[#303449] bg-[#141622] px-4 py-3">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-violet-300">
            <Network size={14} /> {t("Observability")}
          </div>
          <h1 className="mt-1 text-lg font-semibold tracking-tight text-white">{t("Interactive Service Topology")}</h1>
          <p className="mt-1 text-xs text-[#94a3b8]">{t("Drag cards to reposition them. Click to inspect; use the circular control or double click to expand branches.")}</p>
          <div className="relative mt-3" onFocus={() => setSearchOpen(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setSearchOpen(false); }}>
            <Search size={14} className="pointer-events-none absolute left-3 top-2.5 text-[#64748b]" />
            <input
              type="search"
              value={searchTerm}
              onChange={(event) => { setSearchTerm(event.target.value); setSearchOpen(true); }}
              placeholder={t("Find service, API, or user...")}
              aria-label={t("Find service, API, or user")}
              data-testid="topology-search"
              className="h-9 w-full rounded border border-[#303449] bg-[#0f111b] pl-9 pr-3 text-xs text-white outline-none placeholder:text-[#64748b] focus:border-cyan-400"
            />
            {searchOpen && debouncedSearch.length >= 2 && (
              <div className="absolute left-0 top-11 z-40 max-h-72 w-full overflow-y-auto rounded-lg border border-[#34384c] bg-[#141622] p-1" data-testid="topology-search-results">
                {searchQuery.isLoading && <div className="px-3 py-3 text-xs text-[#94a3b8]">{t("Searching...")}</div>}
                {!searchQuery.isLoading && !(searchQuery.data?.items.length) && <div className="px-3 py-3 text-xs text-[#94a3b8]">{t("No matching topology object in the last seven days.")}</div>}
                {searchQuery.data?.items.map((node) => (
                  <button key={`${node.id}-${node.service}-${node.api}`} type="button" data-topology-search-result="true" className="flex w-full items-center gap-3 rounded px-3 py-2 text-left hover:bg-[#202333] focus:bg-[#202333] focus:outline-none" onMouseDown={(event) => event.preventDefault()} onClick={() => travelTo(node)}>
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded border border-[#303449] text-cyan-300"><NodeIcon type={node.type} /></span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-xs font-semibold text-white">{node.name}</span><span className="block truncate text-[10px] uppercase tracking-wider text-[#64748b]">{node.type === "principal" ? t("User") : node.type}{node.service && node.type !== "service" ? ` · ${node.service}` : ""}</span></span>
                    <span className="font-mono text-[10px] text-sky-300">{n(node.metrics.tps, 2)} tps</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="pointer-events-auto flex flex-wrap items-start justify-end gap-2">
          <div className="w-[min(520px,46vw)] rounded-lg border border-[#303449] bg-[#141622] px-3 py-2" data-testid="topology-time-slider-panel">
            <div className="mb-1.5 flex items-center justify-between gap-3 text-[10px] uppercase tracking-wider text-[#94a3b8]">
              <span>{t("Seven-day timeline")}</span>
              <strong className="normal-case tracking-normal text-cyan-300" data-testid="topology-selected-window">{sliderTimeFormatter.format(previewStartMs)} – {sliderTimeFormatter.format(previewEndMs)}</strong>
            </div>
            <input
              type="range"
              min={0}
              max={SEVEN_DAY_SLICES - 1}
              step={1}
              value={sliderPreviewIndex}
              data-testid="topology-time-slider"
              aria-label={t("Select a five-minute topology window within the last seven days")}
              className="h-2 w-full cursor-ew-resize accent-cyan-400"
              onChange={(event) => setSliderPreviewIndex(Number(event.target.value))}
              onPointerUp={(event) => commitTimeSlice(Number(event.currentTarget.value))}
              onKeyUp={(event) => commitTimeSlice(Number(event.currentTarget.value))}
            />
            <div className="mt-1 flex items-center justify-between font-mono text-[9px] text-[#64748b]">
              <span>{sliderTimeFormatter.format(sliderStartMs)}</span>
              <span className="text-[#94a3b8]">{t("5-minute window")}</span>
              <span>{t("Now")}</span>
            </div>
          </div>
          <button type="button" className="btn bg-[#141622]" onClick={relayout}><Maximize2 size={13} /> {t("Re-layout")}</button>
          <button type="button" className="btn bg-[#141622]" onClick={() => { void graphQuery.refetch(); relayout(); }}><RefreshCw size={13} /> {t("Refresh")}</button>
        </div>
      </div>

      {graphQuery.isLoading && <div className="absolute inset-0 grid place-items-center"><Loading /></div>}
      {graphQuery.isError && <div className="absolute inset-0 grid place-items-center p-8"><ErrorState message={t("Topology data is unavailable. Check the configured trace backend and worker aggregation status.")} /></div>}

      <div className="pointer-events-none absolute bottom-4 left-4 z-20 flex max-w-[calc(100%-2rem)] flex-wrap items-stretch gap-2 text-xs">
        <div className="pointer-events-auto flex items-center gap-4 rounded-lg border border-[#303449] bg-[#141622] px-3 py-2 text-[#cbd5e1]">
          <span className="font-medium text-cyan-300">{t("Service → API → Principal")}</span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-[#64748b]">{graphQuery.data?.backend || "clickhouse"}</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-5 border-t-2 border-cyan-300" />{t("Direct")}</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed border-violet-300" />{t("Inferred")}</span>
        </div>
        <div className="pointer-events-auto flex items-center divide-x divide-[#303449] rounded-lg border border-[#303449] bg-[#141622] text-[#94a3b8]">
          <span className="px-3 py-2">{t("New relationships")} <strong className="ml-1 font-mono text-cyan-300">{n(graphQuery.data?.changes?.new_edges?.length, 0)}</strong></span>
          <span className="px-3 py-2">{t("Disappeared")} <strong className="ml-1 font-mono text-rose-300">{n(graphQuery.data?.changes?.disappeared_edges?.length, 0)}</strong></span>
          <span className="px-3 py-2">{t("Baseline")} <strong className="ml-1 font-normal text-[#cbd5e1]">{graphQuery.data?.changes?.baseline || "insufficient history"}</strong></span>
        </div>
        {anonymous && (
          <div className="pointer-events-auto flex items-center gap-3 rounded-lg border border-amber-500/30 bg-[#141622] px-3 py-2 text-[#94a3b8]">
            <span>{t("Identified")} <strong className="ml-1 text-cyan-300">{n(anonymous.identified_request_percentage, 1)}%</strong></span>
            <span>{t("Anonymous")} <strong className="ml-1 text-amber-300">{n(anonymous.anonymous_request_percentage, 1)}%</strong></span>
            <span>{t("Anonymous TPS")} <strong className="ml-1 text-sky-300">{n(anonymous.anonymous_tps, 2)}</strong></span>
          </div>
        )}
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
