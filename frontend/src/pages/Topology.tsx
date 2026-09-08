import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Focus,
  LocateFixed,
  Maximize2,
  Network,
  Search,
  Table2,
} from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, Page, Panel, n, pct } from "../components";
import { useFilters } from "../App";
import type { Edge, NodeItem } from "../types";
type Graph = {
  nodes: NodeItem[];
  edges: Edge[];
  unknown_callers_preserved: boolean;
};
type VNode = {
  id: string;
  label: string;
  group: string;
  module: string;
  aggregate: boolean;
  members: string[];
};
type VEdge = Edge & { id: string };
function groupedGraph(graph: Graph, expanded: Set<string>, minTraffic: number) {
  const nodeBy = new Map(graph.nodes.map((x) => [x.name, x]));
  const mapName = (name: string) => {
    const node = nodeBy.get(name);
    if (!node) return name;
    if (!expanded.has(node.service_group)) return `group:${node.service_group}`;
    const moduleKey = `module:${node.service_group}:${node.service_module}`;
    return expanded.has(moduleKey) ? name : moduleKey;
  };
  const nodeMap = new Map<string, VNode>();
  for (const node of graph.nodes) {
    const id = mapName(node.name),
      existing = nodeMap.get(id);
    if (existing) existing.members.push(node.name);
    else
      nodeMap.set(id, {
        id,
        label: id.startsWith("group:")
          ? node.service_group
          : id.startsWith("module:")
            ? node.service_module
            : node.name,
        group: node.service_group,
        module: node.service_module,
        aggregate: id.startsWith("group:") || id.startsWith("module:"),
        members: [node.name],
      });
  }
  const edgeMap = new Map<string, VEdge>();
  for (const edge of graph.edges.filter((e) => e.requests >= minTraffic)) {
    const source = mapName(edge.source),
      target = mapName(edge.target);
    if (source === target) continue;
    const id = `${source}|${target}|${edge.evidence}`,
      existing = edgeMap.get(id);
    if (existing) {
      existing.requests += edge.requests;
      existing.failure_rate = Math.max(
        existing.failure_rate,
        edge.failure_rate,
      );
      existing.avg_ms = Math.max(existing.avg_ms, edge.avg_ms);
    } else edgeMap.set(id, { ...edge, id, source, target });
  }
  return { nodes: [...nodeMap.values()], edges: [...edgeMap.values()] };
}
export function TopologyPage() {
  const { filters } = useFilters();
  const [evidence, setEvidence] = useState("");
  const [minTraffic, setMinTraffic] = useState(1);
  const [expanded, setExpanded] = useState(new Set<string>());
  const [selected, setSelected] = useState<VNode | VEdge | null>(null);
  const [search, setSearch] = useState("");
  const [neighbors, setNeighbors] = useState(false);
  const q = useQuery({
    queryKey: ["topology", queryString(filters), evidence],
    queryFn: () =>
      api<Graph>(
        `/api/v1/topology?${queryString(filters, evidence ? { evidence } : {})}`,
      ),
    refetchInterval: 60000,
  });
  const view = useMemo(
    () =>
      q.data
        ? groupedGraph(q.data, expanded, minTraffic)
        : { nodes: [], edges: [] },
    [q.data, expanded, minTraffic],
  );
  function focusSearch() {
    const node = q.data?.nodes.find((n) =>
      n.name.toLowerCase().includes(search.toLowerCase()),
    );
    if (node) {
      setExpanded((old) =>
        new Set(old)
          .add(node.service_group)
          .add(`module:${node.service_group}:${node.service_module}`),
      );
      setTimeout(
        () =>
          setSelected({
            id: node.name,
            label: node.name,
            group: node.service_group,
            module: node.service_module,
            aggregate: false,
            members: [node.name],
          }),
        0,
      );
    }
  }
  return (
    <Page
      eyebrow="Dependency evidence"
      title="Service topology"
      description="Grouped level-of-detail view. Solid calls have parent linkage; dashed calls rely on explicit destination evidence."
      actions={
        <div className="flex gap-2">
          <span className="chip">{view.nodes.length} visible nodes</span>
          <span className="chip">{view.edges.length} edges</span>
        </div>
      }
    >
      <div className="card mb-4 flex flex-wrap items-center gap-2.5 p-3">
        <div className="flex min-w-56 flex-1 items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.03] px-3 focus-within:border-indigo-500/60">
          <Search size={14} className="text-[#8b949e]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && focusSearch()}
            placeholder="Search and focus a service node…"
            className="w-full bg-transparent py-1.5 text-xs text-[#f0f3f6] placeholder:text-[#6e7681] outline-none"
          />
          <button
            onClick={focusSearch}
            className="rounded bg-indigo-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-indigo-300 hover:bg-indigo-500/30"
          >
            Focus
          </button>
        </div>
        <select
          className="btn"
          value={evidence}
          onChange={(e) => setEvidence(e.target.value)}
        >
          <option value="" className="bg-[#12151a]">All Evidence</option>
          <option value="confirmed" className="bg-[#12151a]">Confirmed Only</option>
          <option value="inferred" className="bg-[#12151a]">Inferred Only</option>
        </select>
        <label className="btn flex items-center gap-2">
          <span>Traffic ≥</span>
          <input
            className="w-14 bg-transparent font-mono text-center outline-none border-b border-white/20"
            type="number"
            min="1"
            value={minTraffic}
            onChange={(e) => setMinTraffic(Number(e.target.value) || 1)}
          />
        </label>
        <button
          className={`btn ${neighbors ? "border-indigo-500/50 bg-indigo-500/20 text-indigo-300" : ""}`}
          onClick={() => setNeighbors(!neighbors)}
        >
          Immediate Neighbors
        </button>
      </div>
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState message={q.error.message} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
          <Panel
            title="Observed call graph"
            subtitle="Pan, wheel zoom, drag nodes, or select an edge/service. Double-click a group to expand it."
          >
            <TopologyCanvas
              nodes={view.nodes}
              edges={view.edges}
              selected={selected}
              onSelect={setSelected}
              onExpand={(group) =>
                setExpanded((old) => {
                  const next = new Set(old);
                  next.has(group) ? next.delete(group) : next.add(group);
                  return next;
                })
              }
              neighbors={neighbors}
            />
          </Panel>
          <Panel
            title={selected ? "Selection evidence" : "Selection details"}
            subtitle={
              selected
                ? "Values for the selected window"
                : "Choose a node or directed edge"
            }
          >
            {selected ? (
              <Selection
                item={selected}
                graph={q.data!}
                onExpand={(g) => setExpanded((old) => new Set(old).add(g))}
              />
            ) : (
              <div className="grid min-h-72 place-items-center p-8 text-center text-xs text-[#7e7489]">
                <div>
                  <Network className="mx-auto mb-3" />
                  <p>
                    Select an object to see traffic, latency, outcomes,
                    accounts, operations, freshness, and evidence.
                  </p>
                </div>
              </div>
            )}
          </Panel>
        </div>
      )}
      <Panel
        title="Accessible edge table"
        subtitle="Keyboard-accessible equivalent of the canvas · sorted by observed traffic"
        className="mt-4"
        action={<Table2 size={15} className="text-[#81768d]" />}
      >
        <div className="max-h-80 overflow-auto scrollbar">
          <table className="w-full min-w-[800px]">
            <thead className="sticky top-0 bg-panel">
              <tr>
                {[
                  "Source",
                  "Target",
                  "Evidence",
                  "Requests",
                  "Average latency",
                  "Failure rate",
                  "Freshness",
                ].map((h) => (
                  <th key={h} className="table-head px-4 py-3">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.edges
                .sort((a, b) => b.requests - a.requests)
                .map((edge) => (
                  <tr
                    key={edge.id}
                    tabIndex={0}
                    onClick={() => setSelected(edge)}
                    onKeyDown={(e) => e.key === "Enter" && setSelected(edge)}
                    className="focus-ring cursor-pointer border-t border-line hover:bg-[#292133]"
                  >
                    <td className="px-4 py-3 text-xs text-white">
                      {edge.source}
                    </td>
                    <td className="px-4 text-xs text-white">{edge.target}</td>
                    <td className="px-4">
                      <span className="chip">{edge.evidence}</span>
                    </td>
                    <td className="px-4 font-mono text-xs">
                      {n(edge.requests)}
                    </td>
                    <td className="px-4 font-mono text-xs">
                      {n(edge.avg_ms)} ms
                    </td>
                    <td className="px-4 font-mono text-xs">
                      {pct(edge.failure_rate)}
                    </td>
                    <td className="px-4 text-xs text-[#8c8297]">
                      {new Date(edge.freshness_ms).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="mt-3 flex flex-wrap gap-4 text-[10px] text-[#7e7489]">
        <span>
          <b className="text-[#b9b0c2]">Solid</b> parent-linked confirmed call
        </span>
        <span>
          <b className="text-[#b9b0c2]">Dashed</b> explicit destination,
          inferred direction
        </span>
        <span>
          <b className="text-lime">Width</b> bounded √traffic
        </span>
        <span>
          <b className="text-coral">Coral</b> elevated failure rate
        </span>
        <span>Unknown callers remain unknown.</span>
      </div>
    </Page>
  );
}
function Selection({
  item,
  graph,
  onExpand,
}: {
  item: VNode | VEdge;
  graph: Graph;
  onExpand: (g: string) => void;
}) {
  const nav = useNavigate();
  if ("aggregate" in item) {
    const incident = graph.edges.filter(
      (e) => item.members.includes(e.source) || item.members.includes(e.target),
    );
    const traffic = incident.reduce((a, b) => a + b.requests, 0);
    return (
      <div className="p-4">
        <div className="label">
          {item.aggregate ? "Aggregate group" : "Service"}
        </div>
        <div className="mt-2 text-lg text-white">{item.label}</div>
        <div className="mt-1 text-xs text-[#887e94]">
          {item.group} / {item.module}
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-3">
          <Stat k="Members" v={String(item.members.length)} />
          <Stat k="Edge traffic" v={n(traffic)} />
          <Stat k="Operations" v="Open detail" />
          <Stat k="Accounts" v="Open detail" />
        </dl>
        {item.aggregate && (
          <button
            onClick={() =>
              onExpand(item.id.startsWith("module:") ? item.id : item.group)
            }
            className="btn mt-5 w-full"
          >
            Expand {item.members.length} services
          </button>
        )}
        <p className="mt-4 text-[10px] leading-4 text-[#756b81]">
          Service detail provides outcomes, accounts, operation percentiles,
          instances, anomalies, and supporting traces.
        </p>
      </div>
    );
  }
  return (
    <div className="p-4">
      <div className="label">Directed {item.evidence} edge</div>
      <div className="mt-2 flex items-center gap-2 text-sm text-white">
        <span>{item.source}</span>
        <span className="text-lime">→</span>
        <span>{item.target}</span>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-3">
        <Stat k="Observed traffic" v={n(item.requests)} />
        <Stat k="Average latency" v={`${n(item.avg_ms)} ms`} />
        <Stat k="Failure rate" v={pct(item.failure_rate)} />
        <Stat
          k="Freshness"
          v={new Date(item.freshness_ms).toLocaleTimeString()}
        />
      </dl>

      {/* Top Principals on this Edge */}
      {item.top_principals && item.top_principals.length > 0 && (
        <div className="mt-4">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-1.5">
            Top Principals on Edge
          </div>
          <div className="space-y-1">
            {item.top_principals.map((p) => (
              <button onClick={()=>nav(`/users/${encodeURIComponent(p.principal_name)}`)} key={p.principal_name} className="flex w-full items-center justify-between text-xs bg-white/[0.02] p-2 rounded border border-[rgba(255,255,255,0.06)] hover:border-indigo-500/40">
                <span className="font-mono text-indigo-300 truncate max-w-[170px]">{p.principal_name}</span>
                <span className="font-mono text-[#8b949e] text-[10px]">{n(p.requests)} reqs</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Top Operations on this Edge */}
      {item.top_operations && item.top_operations.length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-1.5">
            Top Operations on Edge
          </div>
          <div className="space-y-1">
            {item.top_operations.map((o) => (
              <div key={o.operation} className="flex items-center justify-between text-xs bg-white/[0.02] p-2 rounded border border-[rgba(255,255,255,0.06)]">
                <span className="font-mono text-[#f0f3f6] truncate max-w-[170px]">{o.operation}</span>
                <span className="font-mono text-[#8b949e] text-[10px]">{n(o.requests)} reqs</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 rounded-lg border border-[rgba(255,255,255,0.06)] bg-white/[0.02] p-3">
        <div className="text-[10px] font-semibold uppercase text-[#8b949e] mb-1">Evidence</div>
        <p className="text-xs leading-5 text-[#aba2b5]">
          {item.evidence_detail}
        </p>
      </div>
      <p className="mt-2 text-[10px] text-[#756b81]">
        Shared trace IDs or usernames alone are never used to create this edge.
      </p>
    </div>
  );
}
function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-lg border border-line p-3">
      <dt className="label">{k}</dt>
      <dd className="mt-1 font-mono text-xs text-white">{v}</dd>
    </div>
  );
}

function TopologyCanvas({
  nodes,
  edges,
  selected,
  onSelect,
  onExpand,
  neighbors,
}: {
  nodes: VNode[];
  edges: VEdge[];
  selected: VNode | VEdge | null;
  onSelect: (v: VNode | VEdge | null) => void;
  onExpand: (g: string) => void;
  neighbors: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const spatial = useRef(new Map<string, VNode[]>());
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    text: string;
  } | null>(null);
  const state = useRef({
    scale: 1,
    ox: 0,
    oy: 0,
    drag: "" as string,
    panning: false,
    lastX: 0,
    lastY: 0,
    hover: "",
  });
  const frame = useRef(0);
  const signature = nodes
    .map((n) => n.id)
    .sort()
    .join("|");
  function invalidate() {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(draw);
  }
  useEffect(() => {
    const p = positions.current;
    nodes.forEach((node, i) => {
      if (!p.has(node.id)) {
        const groupHash = [...node.group].reduce(
            (a, c) => a + c.charCodeAt(0),
            0,
          ),
          angle = ((groupHash % 12) / 12) * Math.PI * 2 + (i % 7) * 0.12,
          radius = 100 + (groupHash % 4) * 115;
        p.set(node.id, {
          x: 520 + Math.cos(angle) * radius + (i % 5) * 28,
          y: 330 + Math.sin(angle) * radius + (i % 3) * 22,
        });
      }
    });
    invalidate();
  }, [signature, edges, selected, neighbors]);
  useEffect(() => {
    const resize = () => invalidate();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(frame.current);
    };
  }, []);
  function point(e: { clientX: number; clientY: number }) {
    const r = canvas.current!.getBoundingClientRect(),
      s = state.current;
    return {
      x: (e.clientX - r.left - s.ox) / s.scale,
      y: (e.clientY - r.top - s.oy) / s.scale,
      sx: e.clientX - r.left,
      sy: e.clientY - r.top,
    };
  }
  function hitNode(x: number, y: number) {
    let best: VNode | undefined;
    const cx = Math.floor(x / 64),
      cy = Math.floor(y / 64);
    const candidates: VNode[] = [];
    for (let gx = cx - 1; gx <= cx + 1; gx++) {
      for (let gy = cy - 1; gy <= cy + 1; gy++)
        candidates.push(...(spatial.current.get(`${gx}:${gy}`) || []));
    }
    for (const node of candidates) {
      const p = positions.current.get(node.id)!;
      if ((p.x - x) ** 2 + (p.y - y) ** 2 < (node.aggregate ? 30 : 22) ** 2) {
        best = node;
        break;
      }
    }
    return best;
  }
  function distEdge(x: number, y: number, e: VEdge) {
    const a = positions.current.get(e.source),
      b = positions.current.get(e.target);
    if (!a || !b) return 999;
    const dx = b.x - a.x,
      dy = b.y - a.y,
      t = Math.max(
        0,
        Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / (dx * dx + dy * dy)),
      );
    return Math.hypot(x - (a.x + t * dx), y - (a.y + t * dy));
  }
  function draw() {
    const c = canvas.current;
    if (!c) return;
    const r = c.getBoundingClientRect(),
      dpr = window.devicePixelRatio || 1;
    if (c.width !== r.width * dpr || c.height !== r.height * dpr) {
      c.width = r.width * dpr;
      c.height = r.height * dpr;
    }
    const x = c.getContext("2d")!;
    x.setTransform(dpr, 0, 0, dpr, 0, 0);
    x.clearRect(0, 0, r.width, r.height);
    const s = state.current;
    x.save();
    x.translate(s.ox, s.oy);
    x.scale(s.scale, s.scale);
    const selectedNode = selected && "aggregate" in selected ? selected.id : "";
    spatial.current.clear();
    for (const node of nodes) {
      const p = positions.current.get(node.id)!;
      const key = `${Math.floor(p.x / 64)}:${Math.floor(p.y / 64)}`;
      const cell = spatial.current.get(key) || [];
      cell.push(node);
      spatial.current.set(key, cell);
    }
    const adjacent = new Set<string>();
    if (neighbors && selectedNode) {
      adjacent.add(selectedNode);
      edges.forEach((e) => {
        if (e.source === selectedNode) adjacent.add(e.target);
        if (e.target === selectedNode) adjacent.add(e.source);
      });
    }
    for (const edge of edges) {
      const a = positions.current.get(edge.source),
        b = positions.current.get(edge.target);
      if (!a || !b) continue;
      const muted =
        neighbors &&
        selectedNode &&
        (!adjacent.has(edge.source) || !adjacent.has(edge.target));
      x.globalAlpha = muted ? 0.12 : 1;
      x.beginPath();
      x.moveTo(a.x, a.y);
      x.lineTo(b.x, b.y);
      x.strokeStyle = edge.failure_rate > 0.03 ? "#f43f5e" : "#30363d";
      x.lineWidth = Math.min(6, 1 + Math.sqrt(edge.requests) / 7);
      x.setLineDash(edge.evidence === "inferred" ? [6, 5] : []);
      x.stroke();
      x.setLineDash([]);
      const t = 0.72,
        px = a.x + (b.x - a.x) * t,
        py = a.y + (b.y - a.y) * t,
        ang = Math.atan2(b.y - a.y, b.x - a.x);
      x.beginPath();
      x.moveTo(px, py);
      x.lineTo(px - 7 * Math.cos(ang - 0.5), py - 7 * Math.sin(ang - 0.5));
      x.lineTo(px - 7 * Math.cos(ang + 0.5), py - 7 * Math.sin(ang + 0.5));
      x.fillStyle = x.strokeStyle;
      x.fill();
    }
    x.globalAlpha = 1;
    for (const node of nodes) {
      const p = positions.current.get(node.id)!,
        radius = node.aggregate ? 28 : 20,
        muted = neighbors && selectedNode && !adjacent.has(node.id);
      x.globalAlpha = muted ? 0.16 : 1;
      x.beginPath();
      x.arc(p.x, p.y, radius, 0, Math.PI * 2);
      x.fillStyle =
        selected && "aggregate" in selected && selected.id === node.id
          ? "#6366f1"
          : node.aggregate
            ? "#1c212b"
            : "#161b22";
      x.fill();
      x.strokeStyle =
        selected && "aggregate" in selected && selected.id === node.id
          ? "#a5b4fc"
          : node.aggregate
            ? "#6366f1"
            : "rgba(255,255,255,0.16)";
      x.lineWidth = 1.5;
      x.stroke();
      x.fillStyle =
        selected && "aggregate" in selected && selected.id === node.id
          ? "#ffffff"
          : "#f0f3f6";
      x.font = `${node.aggregate ? "600" : "500"} 11px Inter, system-ui, sans-serif`;
      x.textAlign = "center";
      x.fillText(
        node.label.length > 18 ? node.label.slice(0, 16) + "…" : node.label,
        p.x,
        p.y + 4,
      );
      if (node.aggregate) {
        x.fillStyle = "#818cf8";
        x.font = "600 10px JetBrains Mono";
        x.fillText(String(node.members.length), p.x, p.y + 42);
      }
    }
    x.restore();
    x.globalAlpha = 1;
  }
  function down(e: React.PointerEvent) {
    canvas.current!.setPointerCapture(e.pointerId);
    const p = point(e),
      node = hitNode(p.x, p.y);
    state.current.lastX = p.sx;
    state.current.lastY = p.sy;
    if (node) state.current.drag = node.id;
    else state.current.panning = true;
  }
  function move(e: React.PointerEvent) {
    const p = point(e),
      s = state.current;
    if (s.drag) {
      positions.current.set(s.drag, { x: p.x, y: p.y });
      invalidate();
    } else if (s.panning) {
      s.ox += p.sx - s.lastX;
      s.oy += p.sy - s.lastY;
      s.lastX = p.sx;
      s.lastY = p.sy;
      invalidate();
    } else {
      const hit = hitNode(p.x, p.y);
      canvas.current!.style.cursor = hit ? "pointer" : "grab";
      setTooltip(
        hit
          ? {
              x: p.sx + 14,
              y: p.sy + 14,
              text: `${hit.label} · ${hit.aggregate ? `${hit.members.length} services` : `${hit.group} / ${hit.module}`}`,
            }
          : null,
      );
    }
  }
  function up(e: React.PointerEvent) {
    const p = point(e),
      s = state.current;
    if (s.drag) {
      const node = nodes.find((n) => n.id === s.drag);
      if (node) onSelect(node);
    } else if (!s.panning) {
      const node = hitNode(p.x, p.y);
      if (node) onSelect(node);
      else {
        const edge = edges.find((e) => distEdge(p.x, p.y, e) < 7 / s.scale);
        onSelect(edge || null);
      }
    }
    s.drag = "";
    s.panning = false;
  }
  function wheel(e: React.WheelEvent) {
    e.preventDefault();
    const r = canvas.current!.getBoundingClientRect(),
      s = state.current,
      old = s.scale,
      next = Math.max(0.25, Math.min(2.5, old * (e.deltaY < 0 ? 1.12 : 0.89))),
      mx = e.clientX - r.left,
      my = e.clientY - r.top;
    s.ox = mx - ((mx - s.ox) * next) / old;
    s.oy = my - ((my - s.oy) * next) / old;
    s.scale = next;
    invalidate();
  }
  function fit() {
    const c = canvas.current;
    if (!c || !nodes.length) return;
    const ps = nodes.map((n) => positions.current.get(n.id)!);
    const minX = Math.min(...ps.map((p) => p.x)) - 50,
      maxX = Math.max(...ps.map((p) => p.x)) + 50,
      minY = Math.min(...ps.map((p) => p.y)) - 50,
      maxY = Math.max(...ps.map((p) => p.y)) + 50,
      r = c.getBoundingClientRect(),
      scale = Math.min(r.width / (maxX - minX), r.height / (maxY - minY), 1.4);
    state.current.scale = scale;
    state.current.ox = (r.width - (maxX - minX) * scale) / 2 - minX * scale;
    state.current.oy = (r.height - (maxY - minY) * scale) / 2 - minY * scale;
    invalidate();
  }
  return (
    <div className="relative">
      <canvas
        ref={canvas}
        role="img"
        aria-label={`Interactive service topology with ${nodes.length} nodes and ${edges.length} directed edges. Use the edge table below for a keyboard-accessible view.`}
        className="h-[640px] w-full touch-none bg-[radial-gradient(#332a3e_1px,transparent_1px)] [background-size:24px_24px]"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onWheel={wheel}
        onDoubleClick={(e) => {
          const p = point(e),
            node = hitNode(p.x, p.y);
          if (node?.aggregate)
            onExpand(node.id.startsWith("module:") ? node.id : node.group);
        }}
      />
      {tooltip && (
        <div
          className="pointer-events-none absolute z-10 max-w-56 rounded-lg border border-line bg-[#171220]/95 px-3 py-2 text-[11px] text-white shadow-panel"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.text}
        </div>
      )}
      <div className="absolute left-3 top-3 flex gap-2">
        <button className="btn flex items-center gap-1" onClick={fit}>
          <Maximize2 size={12} />
          Fit
        </button>
        <button
          className="btn flex items-center gap-1"
          onClick={() => {
            state.current = { ...state.current, scale: 1, ox: 0, oy: 0 };
            invalidate();
          }}
        >
          <LocateFixed size={12} />
          Reset
        </button>
      </div>
    </div>
  );
}
