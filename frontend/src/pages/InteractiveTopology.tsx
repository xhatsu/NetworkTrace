import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { api } from "../api";
import { ErrorState, Loading, n } from "../components";
import { useI18n } from "../i18n";
import { EntityLink } from "../components/EntityLink";
import type { EntityRef } from "../entityRoutes";
import {
  layoutServiceGraph,
  SERVICE_NODE_HEIGHT,
  SERVICE_NODE_WIDTH,
  type Position,
} from "../topologyLayout";

type Learning = { strength:number; observed_windows:number; effective_windows:number; expected_tps:number|null; previous_expected_tps:number|null; surprise:number|null; ready:boolean; rate_samples:number; withheld_windows:number; surge_streak:number };
type Metrics = { tps:number; request_count:number; api_count?:number; first_seen_ms?:number|null; last_seen_ms?:number|null; learning:Learning; change:{status?:string} };
type TopologyNode = { id:string; name:string; type:"service"|"api"|"principal"; service?:string; api?:string; principal?:string; edge_ids?:string[]; metrics:Metrics; active_in_window?:boolean };
type TopologyEdge = { id:string; source:string; target:string; source_name:string; target_name:string; metrics:Metrics; direct:boolean; inferred:boolean; active_in_window?:boolean };
type Relation = {id:string; caller_id:string|null; target_id:string; api_id:string|null; principal_id:string|null; edge_id:string|null};
type IpEvidence = { relationship_id:string; source_ip:string; role:string; first_seen_ms:number; last_seen_ms:number; observed_windows:number; strength:number };
type TopologyResponse = {status:string; source:string; environment:string; environments:string[]; version:string|null; through_ms:number|null; nodes:TopologyNode[]; edges:TopologyEdge[]; entities:TopologyNode[]; relations:Relation[]; ip_associations:IpEvidence[]; backend:string; truncated:boolean; total_services:number; total_edges:number; total_relations:number};
type DetailResponse = {entity:TopologyNode|null; metrics:Metrics; series:Array<{timestamp_ms:number;tps:number}>; version:string};

type Selection =
  | { kind: "node"; node: TopologyNode }
  | { kind: "edge"; edge: TopologyEdge }
  | null;

const FIVE_MINUTE_MS = 5 * 60 * 1000;
function emptyMetrics(): Metrics {
  return {tps:0,request_count:0,learning:{strength:0,observed_windows:0,effective_windows:0,expected_tps:null,previous_expected_tps:null,surprise:null,ready:false,rate_samples:0,withheld_windows:0,surge_streak:0},change:{}};
}

function childPosition(parent: Position, index: number, total: number, vertical = false): Position {
  const angle = -Math.PI / 2 + (Math.PI * (index + 1)) / (total + 1);
  const radius = vertical ? 170 : 150;
  return { x: parent.x + Math.cos(angle) * radius, y: parent.y + Math.sin(angle) * radius };
}

function formatCompactTps(value: number): string {
  if(value>=1000)return `${(value/1000).toFixed(1)}k`;
  return n(value,value<1?4:2);
}

function LearningState({metrics}:{metrics:Metrics}) {
  const {t}=useI18n();
  const stale=!metrics.last_seen_ms||Date.now()-metrics.last_seen_ms>30*60_000;
  const elevated=!stale&&metrics.learning.surge_streak>=3;
  return <span className={elevated?'text-[#ff9830]':'text-[#a7a9ab]'}>{stale?t('No recent observation','Chưa có quan sát gần đây'):elevated?t('TPS above expected','TPS cao hơn dự kiến'):metrics.learning.ready?t('Pattern learned','Đã học mẫu hành vi'):t('Learning traffic','Đang học lưu lượng')}</span>;
}

function ObservationAge({at}:{at?:number|null}) {
  const {t}=useI18n();
  const minutes=Math.max(0,Math.floor((Date.now()-(at||0))/60000));
  const label=!at?t('Not available','Chưa có'):minutes<1?t('Just now','Vừa xong'):minutes<60?`${minutes} ${t('min ago','phút trước')}`:minutes<1440?`${Math.floor(minutes/60)} ${t('h ago','giờ trước')}`:`${Math.floor(minutes/1440)} ${t('days ago','ngày trước')}`;
  return <span title={formatTime(at)}>{label}</span>;
}

function edgePath(source: Position, target: Position): string {
  return `M ${source.x} ${source.y} L ${target.x} ${target.y}`;
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

function MetricStrip({ metrics }: { metrics: Metrics; vertical?: boolean }) {
  const {t}=useI18n();
  return <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[10px]"><span className="text-sky-300">{formatCompactTps(metrics.tps)} TPS</span><span className="text-[#a7a9ab]"><LearningState metrics={metrics}/></span></div>;
}

function ServiceNodeCard({
  node,
  selected,
  expanded,
  canExpand,
  onSelect,
  onToggleExpand,
}: {
  node: TopologyNode;
  selected: boolean;
  expanded: boolean;
  canExpand: boolean;
  onSelect: () => void;
  onToggleExpand: () => void;
}) {
  const { t } = useI18n();
  const metrics = node.metrics;
  const historical = node.active_in_window === false;
  const surprise = metrics.learning.surge_streak >= 3;

  return (
    <div
      className={`overflow-hidden rounded-md border bg-[#11131b]/95 shadow-sm transition-colors ${historical ? "border-[#34384c] opacity-60" : surprise ? "border-amber-400/40" : "border-[#34384c]"} ${selected ? "border-sky-200 bg-[#1a2b40] ring-2 ring-sky-300 ring-offset-2 ring-offset-[#0c0d14]" : ""}`}
      style={{ width: SERVICE_NODE_WIDTH, height: SERVICE_NODE_HEIGHT }}
      data-testid="topology-service-card"
    >
      <div className="flex h-full flex-col px-2 py-1.5">
        <div className="flex min-w-0 items-center gap-1.5 leading-4">
          <button
            type="button"
            onClick={(event) => { event.stopPropagation(); onSelect(); }}
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left focus-visible:ring-1 focus-visible:ring-sky-300"
            title={node.name}
            aria-label={`Inspect service ${node.name}`}
          >
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${historical ? "bg-slate-500" : surprise ? "bg-amber-400" : "bg-sky-400"}`} title={historical ? t("Previously observed") : t("Learned observation", "Quan sát đã học")} />
            <span className="min-w-0 flex-1 truncate text-[11px] font-semibold leading-4 text-slate-100">{node.name}</span>
          </button>
          {canExpand && (
            <button
              type="button"
              data-node-drag-ignore="true"
              className="-mr-1 flex h-4 w-4 shrink-0 items-center justify-center rounded text-[11px] text-slate-500 hover:bg-white/5 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sky-300"
              title={expanded ? t("Collapse") : t("Expand")}
              aria-label={`${expanded ? t("Collapse") : t("Expand")} service ${node.name}`}
              onClick={(event) => {
                event.stopPropagation();
                onToggleExpand();
              }}
            >
              {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            </button>
          )}
        </div>

        <button type="button" onClick={(event) => { event.stopPropagation(); onSelect(); }} className="mt-0.5 flex w-full min-w-0 flex-col text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sky-300">
          <span className="flex w-full min-w-0 items-center whitespace-nowrap text-[10px] leading-4">
            <span className="text-sky-300" title={t('Last observed TPS','TPS quan sát cuối')}>{formatCompactTps(metrics.tps)} TPS</span><span className="mx-1 text-slate-700">·</span><span className="text-[#a7a9ab]"><ObservationAge at={metrics.last_seen_ms}/></span>
          </span>
          <span className="mt-0.5 h-3 w-full truncate text-[10px] leading-3 text-[#a7a9ab]"><LearningState metrics={metrics}/>
          </span>
        </button>
      </div>
    </div>
  );
}

function TpsLineGraph({ data, compact = false }: { data: Array<{ timestamp_ms: number; tps: number }>; compact?: boolean }) {
  const width = 320;
  const height = 128;
  const left = 34;
  const right = 8;
  const top = 8;
  const bottom = 22;
  const maxTps = (Math.max(0, ...data.map((point) => point.tps)) || 1);
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const coordinates = data.map((point) => {
    const x = left + ((point.timestamp_ms-data[0].timestamp_ms) / Math.max(1,data[data.length-1].timestamp_ms-data[0].timestamp_ms)) * plotWidth;
    const y = top + plotHeight - (point.tps / maxTps) * plotHeight;
    return { x, y };
  });
  const smoothPath=coordinates.map((point,index)=>`${index===0||data[index].timestamp_ms-data[index-1].timestamp_ms>FIVE_MINUTE_MS?'M':'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
  const firstTime = data[0]?.timestamp_ms;
  const lastTime = data[data.length - 1]?.timestamp_ms;
  const shortTime = (value: number) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div className={`${compact ? "h-32" : "h-44"} rounded border border-[#303449] bg-[#10121c] px-2 pb-2 pt-3`} data-testid="topology-tps-chart">
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="TPS time-series line graph" preserveAspectRatio="none">
        {[0, 0.5, 1].map((ratio) => {
          const y = top + plotHeight * ratio;
          const value = maxTps * (1 - ratio);
          return <g key={ratio}><line x1={left} y1={y} x2={width - right} y2={y} stroke="#25293a" strokeWidth="1" /><text x={left - 5} y={y + 3} fill="#64748b" fontSize="10" textAnchor="end">{n(value, maxTps < 1 ? 3 : 1)}</text></g>;
        })}
        {coordinates.length > 1 && <path className="time-series-curve" d={smoothPath} fill="none" stroke="#38bdf8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
        {data.map((point, index) => {
          const coordinate = coordinates[index];
          return <circle key={`${point.timestamp_ms}-${index}`} cx={coordinate.x} cy={coordinate.y} r="2" fill="#38bdf8"><title>{`${formatTime(point.timestamp_ms)} · ${n(point.tps, 2)} TPS · 5m bucket`}</title></circle>;
        })}
        <text x={left} y={height - 4} fill="#64748b" fontSize="10">{firstTime ? shortTime(firstTime) : ""}</text>
        <text x={width - right} y={height - 4} fill="#64748b" fontSize="10" textAnchor="end">{lastTime ? shortTime(lastTime) : ""}</text>
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

  const orderedEdges = [...edges].sort((left, right) =>
    Number(!!left.active_in_window) - Number(!!right.active_in_window)
    || Number(highlightedEdgeIds.has(left.id)) - Number(highlightedEdgeIds.has(right.id))
  );

  return (
    <div
      ref={surfaceRef}
      className="absolute inset-0 touch-none overflow-hidden bg-[#0c0d14] cursor-grab active:cursor-grabbing"
      aria-label={t("Interactive service topology")}
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
          <marker id="topology-arrow-selected" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4.5" markerHeight="4.5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#facc15" /></marker>
        </defs>
        {orderedEdges.map((edge) => {
          const source = positions[edge.source];
          const target = positions[edge.target];
          if (!source || !target) return null;
          const selected = highlightedEdgeIds.has(edge.id) || (selection?.kind === "edge" && selection.edge.id === edge.id);
          const historical = edge.active_in_window === false;
          const path = edgePath(source, target);
          return (
            <g key={edge.id} role="button" tabIndex={0} aria-label={`${edge.source_name} → ${edge.target_name}`} aria-pressed={selected} onKeyDown={(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect({kind:'edge',edge});}}} data-topology-object="true" onClick={(event) => { event.stopPropagation(); onSelect({ kind: "edge", edge }); }} className="cursor-pointer">
              <path d={path} fill="none" stroke="transparent" strokeWidth="16" />
              <path d={path} fill="none" stroke={selected ? "#facc15" : historical ? "#6b7280" : "#5794c8"} strokeWidth={selected ? 2.5 : 1+edge.metrics.learning.strength*3} strokeDasharray={historical ? "5 6" : edge.inferred ? "7 6" : undefined} markerEnd={historical ? undefined : selected ? "url(#topology-arrow-selected)" : "url(#topology-arrow)"} opacity={selected ? historical ? .8 : 1 : highlightedEdgeIds.size ? .13 : historical ? .3 : .72} />
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
            className={`absolute ${node.type === "service" ? "" : "w-44"} -translate-x-1/2 -translate-y-1/2 cursor-move`}
            style={{ left: `${pos.x / 10}%`, top: `${pos.y / 6.2}%`, width: node.type === "service" ? SERVICE_NODE_WIDTH : undefined, zIndex: isSelected ? 30 : 10 }}
            onPointerDown={(event) => {
              if (event.button !== 0 || (event.target as Element).closest("a, [data-node-drag-ignore='true']")) return;
              nodeDrag.current = { nodeId: node.id, startX: event.clientX, startY: event.clientY, origin: pos, moved: false };
            }}
            onPointerMove={(event) => {
              if (!nodeDrag.current || nodeDrag.current.nodeId !== node.id) return;
              const bounds = event.currentTarget.parentElement?.parentElement?.getBoundingClientRect();
              if (!bounds || bounds.width <= 0 || bounds.height <= 0) return;
              const dx = event.clientX - nodeDrag.current.startX;
              const dy = event.clientY - nodeDrag.current.startY;
              if (Math.abs(dx) + Math.abs(dy) > 3 && !nodeDrag.current.moved) {
                nodeDrag.current.moved = true;
                event.currentTarget.setPointerCapture(event.pointerId);
              }
              const nextPosition = {
                x: nodeDrag.current.origin.x + (dx / zoom) * (1000 / bounds.width),
                y: nodeDrag.current.origin.y + (dy / zoom) * (620 / bounds.height),
              };
              onMoveNode(node.id, nextPosition);
            }}
            onPointerUp={(event) => {
              if (!nodeDrag.current || nodeDrag.current.nodeId !== node.id) return;
              const moved = nodeDrag.current.moved;
              const captured = event.currentTarget.hasPointerCapture(event.pointerId);
              nodeDrag.current = null;
              if (moved) {
                suppressCanvasClick.current = true;
                window.setTimeout(() => { suppressCanvasClick.current = false; }, 0);
              }
              if (captured) event.currentTarget.releasePointerCapture(event.pointerId);
            }}
            onPointerCancel={() => { nodeDrag.current = null; suppressCanvasClick.current = false; }}
            onLostPointerCapture={() => { nodeDrag.current = null; }}
          >
            {node.type === "service" ? (
              <ServiceNodeCard
                node={node}
                selected={isSelected}
                expanded={isExpanded}
                canExpand={canExpand}
                onSelect={() => onSelect({ kind: "node", node })}
                onToggleExpand={() => onToggleExpand(node)}
              />
            ) : (
              <>
                <div className={`group w-full rounded-lg border border-l-4 bg-[#171a28] px-3 py-2 text-left transition hover:border-white/70 ${tone.border} ${isSelected ? "border-white ring-1 ring-white/70" : node.metrics.change?.status === "new" ? "border-cyan-400/70" : node.metrics.change?.status === "changed" ? "border-amber-400/70" : "border-[#303449]"}`}>
                  <button type="button" className={`flex items-center gap-2 text-xs font-semibold focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400 ${tone.text}`} onClick={(event) => { event.stopPropagation(); onSelect({ kind: "node", node }); }} aria-label={`Inspect ${node.type} ${node.name}`}>
                    <NodeIcon type={node.type} /><span className="truncate">{node.name}</span>
                  </button>
                  <span className={`mt-0.5 block text-[10px] uppercase tracking-wider ${tone.text}`}>{node.type === "principal" ? t("Credential", "Credential") : t("API")}</span>
                  <button type="button" className="mt-1 block w-full text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400" onClick={(event) => { event.stopPropagation(); onSelect({ kind: "node", node }); }} aria-label={`Inspect ${node.type} ${node.name}`}>
                    <MetricStrip metrics={node.metrics} vertical />
                  </button>
                </div>
              </>
            )}
          </div>
        );
      })}
      {!nodes.length && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-sm text-[#94a3b8]">
          <div>{t("No learned service relationships yet.", "Chưa có quan hệ Service đã học.")}</div>
          <div className="text-xs text-[#64748b]">
            {t("Check the learning source and environment.", "Kiểm tra nguồn và môi trường học.")}
          </div>
          <div className="text-xs text-cyan-300">{t("Missing caller evidence never creates a service-call edge.", "Thiếu Caller không tạo cạnh lời gọi Service.")}</div>
        </div>
      )}
      </div>
      <div className="absolute bottom-24 left-3 z-20 flex flex-col overflow-hidden rounded border border-[#303449] bg-[#141622] xl:bottom-14" data-topology-object="true" aria-label={t("Canvas navigation controls")}>
        <button type="button" data-testid="topology-zoom-in" className="grid h-7 w-8 place-items-center text-[#cbd5e1] hover:bg-[#202333] hover:text-white" onClick={(event) => { event.stopPropagation(); changeZoom(0.1); }} aria-label={t("Zoom in")} title={t("Zoom in")}><ZoomIn size={14} /></button>
        <button type="button" data-testid="topology-reset-view" className="border-y border-[#303449] px-1 py-1 font-mono text-[10px] font-semibold text-cyan-300" onClick={(event) => { event.stopPropagation(); resetViewport(); }} aria-label={t("Reset canvas view")} title={t("Reset canvas view")}>{Math.round(zoom * 100)}%</button>
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
        {!loading && !error && items.length === 0 && <p className="px-2 py-3 text-xs text-[#94a3b8]">{t("No matching learned relationships.", "Không có quan hệ đã học phù hợp.")}</p>}
        {items.map((item) => (
          <button key={item.id} type="button" data-testid="topology-drilldown-item" onClick={() => onSelect(item)} className={`mb-0.5 flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left transition focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-yellow-400 ${selectedId === item.id ? "bg-[#2a2a25] ring-1 ring-yellow-400/70" : "hover:bg-[#202333]"}`}>
            <span className={`grid h-6 w-6 shrink-0 place-items-center rounded border border-[#303449] ${entityTone(item.type).soft} ${entityTone(item.type).text}`}><NodeIcon type={item.type} /></span>
            <span className="min-w-0 flex-1"><span className={`block truncate text-[11px] font-medium ${entityTone(item.type).text}`}>{item.name}</span><span className="block truncate font-mono text-[10px] text-[#64748b]">{formatCompactTps(item.metrics.tps)} TPS · <ObservationAge at={item.metrics.last_seen_ms}/></span></span>
            {item.type === "service" && item.metrics.api_count !== undefined && <span className="shrink-0 text-[10px] text-[#94a3b8]">{item.metrics.api_count} APIs</span>}
          </button>
        ))}
        {hasMore && <button type="button" className="btn mt-1 w-full justify-center" onClick={onLoadMore}>{t("Load more")}</button>}
      </div>
    </section>
  );
}

function DetailPanel({selection,detail,detailLoading,detailError,ips,onClose}:{selection:Selection;detail?:DetailResponse;detailLoading:boolean;detailError:boolean;ips:IpEvidence[];onClose:()=>void}) {
  const {t}=useI18n();
  if(!selection)return null;
  const object=selection.kind==='edge'?selection.edge:selection.node;
  const metrics=detail?.metrics||object.metrics;const learned=metrics.learning;
  const entityRef:EntityRef|undefined=selection.kind!=='node'?undefined:selection.node.type==='service'?{kind:'service',name:selection.node.name}:selection.node.type==='principal'?{kind:'user',principal:selection.node.principal||selection.node.name}:selection.node.service?{kind:'api',service:selection.node.service,operation:selection.node.api||selection.node.name}:undefined;
  const name=selection.kind==='edge'?`${selection.edge.source_name} → ${selection.edge.target_name}`:selection.node.name;
  return <aside className="absolute bottom-3 right-3 top-auto z-30 flex max-h-[72vh] w-[calc(100%-1.5rem)] flex-col overflow-hidden rounded border border-[#34384c] bg-[#141622] sm:bottom-auto sm:top-16 sm:max-h-[min(74vh,580px)] sm:w-[328px]" aria-label={t('Topology object details')} data-testid="topology-inspector">
    <div className="flex items-start justify-between gap-2 border-b border-[#303449] px-3 py-2.5"><div className="min-w-0"><p className="text-[10px] text-[#a7a9ab]">{t('Learned observation','Quan sát đã học')} · {selection.kind==='edge'?t('Service call','Lời gọi Service'):selection.node.type==='principal'?t('Observed credential','Credential quan sát'):selection.node.type}</p><h3 className="mt-1 break-words text-sm text-white">{entityRef?<EntityLink entity={entityRef} className="text-sky-200 hover:underline">{name} <ChevronRight size={13} className="inline"/></EntityLink>:name}</h3></div><button type="button" className="btn" onClick={onClose} aria-label={t('Close topology detail panel')}><X size={14}/></button></div>
    <div className="min-h-0 space-y-3 overflow-y-auto p-3 text-xs text-[#a7a9ab]">
      {detailLoading?<Loading/>:detailError?<ErrorState message={t('The selected topology detail could not be loaded.')}/>:<>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-[#303449] px-2.5 py-2"><LearningState metrics={metrics}/><ObservationAge at={metrics.last_seen_ms}/></div>
      <div className="grid grid-cols-2 gap-3"><div><div className="label">{t('Observed TPS','TPS quan sát')}</div><strong className="font-mono text-xl text-sky-300">{formatCompactTps(metrics.tps)}</strong></div><div><div className="label">{t('Expected TPS','TPS dự kiến')}</div><strong className="font-mono text-xl">{learned.ready&&learned.expected_tps!=null?formatCompactTps(learned.expected_tps):'—'}</strong></div></div>
      {!learned.ready&&<p className="text-[11px]">{t('Building a traffic reference from completed observations.','Đang tạo tham chiếu lưu lượng từ các quan sát đã hoàn tất.')}</p>}
      {!!detail?.series.length&&<section><h4 className="label mb-1">{t('TPS · last observed day','TPS · ngày quan sát cuối')}</h4><TpsLineGraph data={detail.series} compact/></section>}
      {!detail?.series.length&&<p data-testid="topology-tps-empty">{t('No retained TPS samples for this object.','Không còn mẫu TPS cho đối tượng này.')}</p>}
      {selection.kind==='node'&&selection.node.type==='principal'&&<details className="rounded border border-[#303449]"><summary className="cursor-pointer p-2">{t('Observed IP evidence','Bằng chứng IP quan sát')} ({ips.length})</summary><div className="space-y-2 border-t border-[#303449] p-2">{ips.length?ips.map(ip=><div key={ip.relationship_id+ip.source_ip}><span className="break-all font-mono">{ip.source_ip}</span> · {ip.role==='infrastructure'?t('Infrastructure','Hạ tầng'):t('Unverified peer','Địa chỉ chưa xác minh')}<p><ObservationAge at={ip.last_seen_ms}/></p></div>):<p>{t('No observed IP evidence.','Chưa có bằng chứng IP quan sát.')}</p>}</div></details>}
      <p className="text-[11px] leading-5">{t('TPS covers this object’s relationships in the selected source and environment. Missing observations are gaps, not zero traffic.','TPS gồm các quan hệ của đối tượng trong nguồn và môi trường đã chọn. Thiếu quan sát là khoảng trống dữ liệu, không phải lưu lượng bằng không.')}</p>
      </>}
    </div>
  </aside>;
}

export function InteractiveTopologyPage() {
  const { t } = useI18n();
  const [mode, setMode] = useState<"service-first" | "user-first">("service-first");
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [expandedServiceId, setExpandedServiceId] = useState<string>();
  const [pathSelection, setPathSelection] = useState<{ service?: TopologyNode; api?: TopologyNode; principal?: TopologyNode }>({});
  const [selection, setSelection] = useState<Selection>(null);
  const [positions, setPositions] = useState<Record<string, Position>>({});
  const layoutViewportRef = useRef<HTMLElement>(null);
  const [layoutViewport, setLayoutViewport] = useState({ width: 0, height: 0 });
  const serviceLayoutSignatureRef = useRef<string | null>(null);
  const serviceLayoutInitializedRef = useRef(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [apiSearch, setApiSearch] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [serviceSearch, setServiceSearch] = useState("");
  const [reverseApiSearch, setReverseApiSearch] = useState("");
  const [focusRequest, setFocusRequest] = useState<{ nodeId: string; token: number }>();
  const [source,setSource]=useState('legacy_metrics');
  const [environment,setEnvironment]=useState('');
  const [listLimits,setListLimits]=useState<Record<string,number>>({});
  const qs=new URLSearchParams({source,environment}).toString();

  useEffect(() => {
    const viewport = layoutViewportRef.current;
    if (!viewport) return;
    const updateSize = () => {
      const bounds = viewport.getBoundingClientRect();
      const width = Math.round(bounds.width);
      const height = Math.round(bounds.height);
      if (width <= 0 || height <= 0) return;
      setLayoutViewport((current) => current.width === width && current.height === height
        ? current
        : { width, height });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchTerm.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [searchTerm]);

  const graphQuery=useQuery({queryKey:['learned-topology',qs],queryFn:({signal})=>api<TopologyResponse>('/api/v1/behavior/topology?'+qs,{signal}),refetchInterval:60000});
  const services=graphQuery.data?.nodes||[];
  const graphEdges=graphQuery.data?.edges||[];
  const entities=graphQuery.data?.entities||[];
  const relations=graphQuery.data?.relations||[];
  const entityIndex=useMemo(()=>new Map((graphQuery.data?.entities||[]).map(node=>[node.id,node])),[graphQuery.data?.entities]);
  const searchText=debouncedSearch.toLocaleLowerCase();
  const searchItems=entities.filter(node=>node.name.toLocaleLowerCase().includes(searchText)).sort((a,b)=>Number(b.name.toLocaleLowerCase()===searchText)-Number(a.name.toLocaleLowerCase()===searchText)||Number(b.type==='service')-Number(a.type==='service')||a.name.localeCompare(b.name)).slice(0,20);
  const serviceLayoutSignature = useMemo(() => {
    const nodePart = services.map((node) => node.id).sort().join("|");
    const edgePart = graphEdges.map((edge) => `${edge.source}>${edge.target}`).sort().join("|");
    return `${nodePart}::${edgePart}`;
  }, [services, graphEdges]);

  useEffect(() => {
    if (layoutViewport.width <= 0 || layoutViewport.height <= 0) return;
    if (graphQuery.isLoading || !services.length) return;
    if (serviceLayoutSignatureRef.current === serviceLayoutSignature) return;
    serviceLayoutSignatureRef.current = serviceLayoutSignature;
    const firstLayout = !serviceLayoutInitializedRef.current;
    const calculated = layoutServiceGraph(
      services,
      graphEdges,
      layoutViewport.width,
      layoutViewport.height,
      firstLayout,
    );
    serviceLayoutInitializedRef.current = true;
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
        if ((firstLayout || !Object.prototype.hasOwnProperty.call(next, service.id)) && calculated[service.id]) {
          next[service.id] = calculated[service.id];
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [serviceLayoutSignature, layoutViewport.width, layoutViewport.height, graphQuery.isLoading, services]);

  function nodePage(items:TopologyNode[],search:string,key:string) {
    const matched=items.filter(node=>node.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
    const pageKey=key+':'+search;const limit=listLimits[pageKey]||100;
    return {items:matched.slice(0,limit),hasMore:matched.length>limit,loadMore:()=>setListLimits(current=>({...current,[pageKey]:limit+100}))};
  }
  function relatedNodes(rows:Relation[],kind:TopologyNode['type']) {
    const related=new Map<string,Set<string>>();
    for(const row of rows){const id=kind==='service'?row.target_id:kind==='api'?row.api_id:row.principal_id;if(!id)continue;let edges=related.get(id);if(!edges){edges=new Set();related.set(id,edges);}if(row.edge_id)edges.add(row.edge_id);}
    return [...related].flatMap(([id,edgeIds])=>{const node=entityIndex.get(id);return node?[{...node,edge_ids:[...edgeIds]}]:[]}).sort((a,b)=>a.name.localeCompare(b.name));
  }
  const apiListBase=mode==='service-first'?!!expandedServiceId:!!(pathSelection.principal&&pathSelection.service);
  const apiRelations=relations.filter(r=>r.target_id===pathSelection.service?.id&&(mode==='service-first'||r.principal_id===pathSelection.principal?.id));
  const apiList=nodePage(relatedNodes(apiRelations,'api').map(node=>({...node,principal:mode==='user-first'?pathSelection.principal?.name:undefined})),mode==='service-first'?apiSearch:reverseApiSearch,'apis');
  const apiItems=apiList.items;
  const principalListBase=mode==='service-first'&&!!pathSelection.service&&!!pathSelection.api;
  const principalRelations=apiRelations.filter(r=>r.api_id===pathSelection.api?.id);
  const principalList=nodePage(relatedNodes(principalRelations,'principal').map(node=>({...node,service:pathSelection.service?.name,api:pathSelection.api?.api})),userSearch,'principals');
  const principalItems=principalList.items;
  const directoryList=nodePage(entities.filter(node=>node.type==='principal'),serviceSearch,'directory');
  const directoryItems=directoryList.items;
  const userServicesList=nodePage(relatedNodes(relations.filter(r=>r.principal_id===pathSelection.principal?.id),'service'),serviceSearch,'services');
  const userServiceItems=userServicesList.items;
  const selectedNode=selection?.kind==='node'?selection.node:undefined;
  const selectedObjectId=selection?.kind==='node'?selection.node.id:selection?.kind==='edge'?selection.edge.id:undefined;
  const detailQuery=useQuery({queryKey:['learned-topology-detail',qs,selectedObjectId,graphQuery.data?.version],queryFn:({signal})=>api<DetailResponse>('/api/v1/behavior/topology/detail?'+qs+'&object_id='+selectedObjectId,{signal}),enabled:!!selectedObjectId});
  const selectedRelations=relations.filter(r=>selectedNode&&[r.caller_id,r.target_id,r.api_id,r.principal_id].includes(selectedNode.id)).filter(r=>selectedNode?.type==='service'||!selectedNode?.service||entityIndex.get(r.target_id)?.name===selectedNode.service).filter(r=>!selectedNode?.api||entityIndex.get(r.api_id||'')?.api===selectedNode.api).filter(r=>!selectedNode?.principal||entityIndex.get(r.principal_id||'')?.name===selectedNode.principal);
  const selectedRelationIds=new Set(selectedRelations.map(r=>r.id));
  const ipItems=(graphQuery.data?.ip_associations||[]).filter(ip=>selectedRelationIds.has(ip.relationship_id));
  const highlightedEdgeIds=new Set(selection?.kind==='edge'?[selection.edge.id]:selectedRelations.flatMap(r=>r.edge_id?[r.edge_id]:[]));

  function select(next: Selection) {
    setSelection(next);
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
    const calculated = layoutServiceGraph(services, graphEdges, layoutViewport.width, layoutViewport.height);
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

  function travelTo(node: TopologyNode) {
    if (node.type === "service") {
      setPathSelection({ service: node });
      select({ kind: "node", node });
      setFocusRequest({ nodeId: node.id, token: Date.now() });
    } else if(node.type === "principal") {
      setMode("user-first"); setDirectoryOpen(true); setPathSelection({principal:node}); select({kind:"node",node});
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
      setPathSelection({ service, api: apiNode, principal: undefined });
      select({ kind: "node", node });
      setFocusRequest({ nodeId: service.id, token: Date.now() });
    }
    setSearchTerm(node.name);
    setSearchOpen(false);
  }

  const apiSelectedId = pathSelection.api?.id;
  const principalSelectedId = pathSelection.principal?.id;
  const serviceSelectedId = pathSelection.service?.id;
  const panelsOpen = directoryOpen || !!expandedServiceId || !!pathSelection.principal;

  return (
    <main ref={layoutViewportRef} className="isolate relative h-full min-h-[600px] overflow-hidden border-t border-[#262838] bg-[#0c0d14]" onClickCapture={(event) => {
      if (panelsOpen && !(event.target as Element).closest("[data-testid='topology-drilldown-panel']")) dismissPanels();
    }}>
      {!graphQuery.isLoading && !graphQuery.isError && (
        <GraphSurface
          nodes={services}
          edges={graphEdges}
          positions={positions}
          selection={selection}
          highlightedEdgeIds={highlightedEdgeIds}
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
          <h1 className="flex items-center gap-1.5 text-[13px] font-semibold tracking-tight text-white"><Network size={14} className="shrink-0 text-violet-300" />{t("Learned Service Topology", "Topology Service đã học")}</h1>
          <p className="sr-only">{t("The graph shows services and their connections. Expand a service to browse APIs and users.")}</p>
          <div className="relative mt-1.5" onFocus={() => setSearchOpen(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setSearchOpen(false); }}>
            <Search size={13} className="pointer-events-none absolute left-2.5 top-2 text-[#64748b]" />
            <input type="search" value={searchTerm} onChange={(event) => { setSearchTerm(event.target.value); setSearchOpen(true); }} placeholder={t("Find service, API, or credential...", "Tìm Service, API hoặc Credential...")} aria-label={t("Find service, API, or credential", "Tìm Service, API hoặc Credential")} data-testid="topology-search" className="h-7 w-full rounded border border-[#303449] bg-[#0f111b] pl-8 pr-2 text-[11px] text-white outline-none placeholder:text-[#64748b] focus:border-cyan-400" />
            {searchOpen && debouncedSearch.length >= 2 && (
              <div className="absolute left-0 top-8 z-40 max-h-56 w-full overflow-y-auto rounded border border-[#34384c] bg-[#141622] p-1" data-testid="topology-search-results">
                {graphQuery.isLoading && <div className="px-3 py-3 text-xs text-[#94a3b8]">{t("Searching...")}</div>}
                {!graphQuery.isLoading && !(searchItems.length) && <div className="px-3 py-3 text-xs text-[#94a3b8]">{t("No matching object in the loaded learned graph.", "Không có đối tượng phù hợp trong đồ thị đã tải.")}</div>}
                {searchItems.map((node) => (
                  <button key={node.id + "-" + node.service + "-" + node.api} type="button" data-topology-search-result="true" className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-[#202333] focus:bg-[#202333] focus:outline-none" onMouseDown={(event) => event.preventDefault()} onClick={() => travelTo(node)}>
                    <span className={"grid h-6 w-6 shrink-0 place-items-center rounded border border-[#303449] " + entityTone(node.type).soft + " " + entityTone(node.type).text}><NodeIcon type={node.type} /></span>
                    <span className="min-w-0 flex-1"><span className={"block truncate text-[11px] font-semibold " + entityTone(node.type).text}>{node.name}</span><span className="block truncate text-[10px] uppercase tracking-wider text-[#64748b]">{node.type === "principal" ? t("Credential", "Credential") : t(node.type)}{node.service && node.type !== "service" ? " · " + node.service : ""}</span></span>
                    <span className="font-mono text-[10px] text-sky-300">{n(node.metrics.tps, 2)} tps</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="mt-1.5 flex rounded border border-[#303449] bg-[#10121c] p-0.5" role="group" aria-label={t("Topology navigation mode")}>
            <button type="button" data-testid="topology-mode-service-first" onClick={() => changeMode("service-first")} className={"min-w-0 flex-1 rounded px-1 py-1 text-[10px] font-medium " + (mode === "service-first" ? "bg-[#263043] text-cyan-200" : "text-[#94a3b8] hover:text-white")}>{t("Service → API → Credential", "Service → API → Credential")}</button>
            <button type="button" data-testid="topology-mode-user-first" onClick={() => changeMode("user-first")} className={"min-w-0 flex-1 rounded px-1 py-1 text-[10px] font-medium " + (mode === "user-first" ? "bg-[#263043] text-cyan-200" : "text-[#94a3b8] hover:text-white")}>{t("Credential → Service → API", "Credential → Service → API")}</button>
          </div>
        </div>

        <div className="pointer-events-auto flex flex-wrap items-start justify-end gap-1.5">
          <select className="btn max-w-[160px] bg-[#141622]" aria-label={t('Learning source','Nguồn học')} value={source} onChange={e=>{setSource(e.target.value);setEnvironment('');clearNavigation();setPositions({});serviceLayoutInitializedRef.current=false;}}>{['legacy_metrics'].map(value=><option key={value} value={value}>{value}</option>)}</select>
          <select className="btn max-w-[140px] bg-[#141622]" aria-label={t('Learning environment','Môi trường học')} value={environment||graphQuery.data?.environment||''} onChange={e=>{setEnvironment(e.target.value);clearNavigation();setPositions({});serviceLayoutInitializedRef.current=false;}}>{!graphQuery.data?.environments.length&&<option value="">{t('No environment','Chưa có môi trường')}</option>}{graphQuery.data?.environments.map(value=><option key={value} value={value}>{value}</option>)}</select>
          <button type="button" className="btn bg-[#141622]" onClick={relayout}><Maximize2 size={13} /> {t("Re-layout")}</button>
          <button type="button" className="btn bg-[#141622]" onClick={() => { void graphQuery.refetch(); void detailQuery.refetch(); }}><RefreshCw size={13} /> {t("Refresh")}</button>
        </div>
      </div>

      {(graphQuery.isLoading) && <div className="absolute inset-0 grid place-items-center"><Loading /></div>}
      {(graphQuery.isError) && <div className="absolute inset-0 grid place-items-center p-8"><ErrorState message={t("Learned topology is unavailable. Check the learning worker and source coverage.", "Chưa có topology đã học. Kiểm tra worker học và độ phủ nguồn.")} /></div>}

      <div className="pointer-events-none absolute left-3 top-44 z-20 flex max-w-[calc(100vw-1.5rem)] flex-col items-start gap-1.5 pb-1 sm:top-40">
        {mode === "user-first" && !directoryOpen && <button type="button" className="btn pointer-events-auto bg-[#141622]" onClick={() => setDirectoryOpen(true)}><UserRound size={13} /> {t("Credentials", "Credential")}</button>}
        {mode === "user-first" && directoryOpen && <RelationshipListPanel key="user-directory" title={t("Credentials", "Credential")} items={directoryItems} selectedId={principalSelectedId} loading={graphQuery.isLoading} error={graphQuery.isError} search={serviceSearch} onSearch={setServiceSearch} onSelect={chooseDirectoryPrincipal} onClose={dismissPanels} hasMore={directoryList.hasMore} onLoadMore={directoryList.loadMore} />}
        {mode === "user-first" && pathSelection.principal && <RelationshipListPanel key="user-services" title={pathSelection.principal.name + " · " + t("Services")} items={userServiceItems} selectedId={serviceSelectedId} loading={graphQuery.isLoading} error={graphQuery.isError} search={serviceSearch} onSearch={setServiceSearch} onSelect={chooseUserService} onClose={dismissPanels} hasMore={userServicesList.hasMore} onLoadMore={userServicesList.loadMore} />}
        {apiListBase && <RelationshipListPanel key="api-list" title={(mode === "service-first" ? pathSelection.service?.name : pathSelection.service?.name) + " · " + t("APIs")} items={apiItems} selectedId={apiSelectedId} loading={graphQuery.isLoading} error={graphQuery.isError} search={mode === "service-first" ? apiSearch : reverseApiSearch} onSearch={mode === "service-first" ? setApiSearch : setReverseApiSearch} onSelect={mode === "service-first" ? chooseApi : chooseReverseApi} onClose={dismissPanels} hasMore={apiList.hasMore} onLoadMore={apiList.loadMore} />}
        {principalListBase && <RelationshipListPanel key="api-users" title={pathSelection.api?.name + " · " + t("Credentials", "Credential")} items={principalItems} selectedId={principalSelectedId} loading={graphQuery.isLoading} error={graphQuery.isError} search={userSearch} onSearch={setUserSearch} onSelect={chooseApiPrincipal} onClose={dismissPanels} hasMore={principalList.hasMore} onLoadMore={principalList.loadMore} />}
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 z-20 flex max-w-[calc(100%-1.5rem)] flex-wrap gap-1 text-[10px] text-[#a7a9ab]">
        <div className="rounded border border-[#303449] bg-[#141622] px-2 py-1">{t('Learned topology','Topology đã học')} · {services.length}/{graphQuery.data?.total_services||0} Service · {graphEdges.length}/{graphQuery.data?.total_edges||0} {t('edges','cạnh')}</div>
        <div className="rounded border border-[#303449] bg-[#141622] px-2 py-1">{t('Updated through','Đã cập nhật đến')}: {formatTime(graphQuery.data?.through_ms)}</div>
        <div className="flex flex-wrap items-center gap-2 rounded border border-[#303449] bg-[#141622] px-2 py-1"><span>━ {t('Width = relationship familiarity','Độ dày = mức quen thuộc của quan hệ')}</span><span className="text-[#6b7280]">┄ {t('Last seen >30m','Quan sát cuối >30 phút')}</span><span className="text-yellow-400">━ {t('Selected path')}</span></div>
        <div className="rounded border border-[#303449] bg-[#141622] px-2 py-1">{t('Observed traffic · own learning horizon','Lưu lượng quan sát · phạm vi học riêng')}</div>
        {graphQuery.data?.truncated&&<div className="rounded border border-[#ff9830] bg-[#141622] px-2 py-1 text-[#ff9830]">{t('Display limit reached; some relationships are omitted.','Đạt giới hạn hiển thị; một số quan hệ chưa được hiển thị.')}</div>}
      </div>

      <DetailPanel
        selection={selection}
        detail={detailQuery.data}
        detailLoading={detailQuery.isLoading}
        detailError={detailQuery.isError}
        ips={ipItems}
        onClose={() => select(null)}
      />
    </main>
  );
}
