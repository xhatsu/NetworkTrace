import { useState } from "react";
import { useParams, useNavigate, useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BarChart2,
  CheckCircle2,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  HardDrive,
  Layers,
  Radio,
  RefreshCw,
  Send,
  Server,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";
import { Page, Panel, MetricCard, Loading, ErrorState, n, pct, chartTooltip } from "../components";

// ─── types ────────────────────────────────────────────────────────────────────

export interface AgentSample {
  node: string;
  instance_id: string;
  sequence: number;
  observed_at: number;   // unix seconds
  window_seconds: number;
  mode: string | null;
  status: string;
  reasons_json: string;
  raw_json?: string;
  ingested_at: number;   // unix ms

  // capture
  cap_packets_delta?: number;
  cap_packets_total?: number;
  cap_packet_bytes_delta?: number;
  cap_packet_bytes_total?: number;
  cap_kernel_drops_delta?: number;
  cap_kernel_drops_total?: number;
  cap_kernel_drop_percent?: number;
  cap_invalid_frames_total?: number;
  cap_events_emitted_delta?: number;
  cap_events_emitted_total?: number;
  cap_flows_active?: number;
  cap_pending_requests?: number;
  cap_wsse_body_flows_active?: number;

  // shipping
  ship_events_in_delta?: number;
  ship_events_in_total?: number;
  ship_events_pushed_delta?: number;
  ship_events_pushed_total?: number;
  ship_events_dropped_delta?: number;
  ship_events_dropped_total?: number;
  ship_drop_causes_json?: string;
  ship_push_events_per_second?: number;
  ship_push_kbps?: number;
  ship_drop_events_per_second?: number;
  ship_drop_percent?: number;
  ship_queue_depth_events?: number;
  ship_queue_capacity_events?: number;
  ship_queue_high_water_events?: number;
  ship_last_push_http_status?: number;
  ship_last_success_at?: number;
  ship_consecutive_failures?: number;
  ship_stats_samples_dropped_total?: number;

  // resources
  res_cpu_user_seconds?: number;
  res_cpu_system_seconds?: number;
  res_cpu_percent_one_core?: number;
  res_rss_bytes?: number;
  res_virtual_bytes?: number;
  res_open_fds?: number;
  res_threads?: number;

  // limits
  lim_cpu_core?: string | number;
  lim_address_space_bytes?: number;
  lim_ship_rate_kbps?: number;
  lim_http_body_max_bytes?: number;
  lim_ship_threads_max?: number;
  lim_wsse_body_bytes?: number;
  limits?: {
    cpu_core?: string | number;
    address_space_bytes?: number;
    ship_rate_kbps?: number;
    http_body_max_bytes?: number;
    ship_threads_max?: number;
    wsse_body_bytes?: number;
  };
}

// ─── helpers ──────────────────────────────────────────────────────────────────

const BASE = "/api/agent";

async function fetchLatest(node?: string, instance_id?: string): Promise<{ items: AgentSample[]; count: number }> {
  const params = new URLSearchParams();
  if (node) params.set("node", node);
  if (instance_id) params.set("instance_id", instance_id);
  const qs = params.toString();
  const url = qs ? `${BASE}/stats?${qs}` : `${BASE}/stats`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function fetchNodeDetail(node: string, instance_id?: string): Promise<{ node: string; instance_id: string; latest: AgentSample | null; instances: string[]; found: boolean }> {
  const url = instance_id
    ? `${BASE}/stats/${encodeURIComponent(node)}?instance_id=${encodeURIComponent(instance_id)}`
    : `${BASE}/stats/${encodeURIComponent(node)}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function fetchHistory(node: string, limit = 120, instance_id?: string): Promise<{ node: string; instance_id?: string; items: AgentSample[]; count: number }> {
  const url = instance_id
    ? `${BASE}/stats/${encodeURIComponent(node)}/history?limit=${limit}&instance_id=${encodeURIComponent(instance_id)}`
    : `${BASE}/stats/${encodeURIComponent(node)}/history?limit=${limit}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function deleteAgent(node: string, instance_id?: string): Promise<boolean> {
  const url = instance_id
    ? `${BASE}/stats/${encodeURIComponent(node)}/${encodeURIComponent(instance_id)}`
    : `${BASE}/stats/${encodeURIComponent(node)}`;
  const r = await fetch(url, {
    method: "DELETE",
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${r.status}`);
  }
  return true;
}

function parseReasons(json: string | undefined): string[] {
  if (!json) return [];
  try { return JSON.parse(json) || []; } catch { return []; }
}

function fmtTs(sec: number) {
  if (!sec) return "";
  return new Date(sec * 1000).toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}

function fmtFullDate(sec: number) {
  if (!sec) return "—";
  return new Date(sec * 1000).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}

function fmtAge(sec: number) {
  if (!sec) return "—";
  const diff = Math.max(0, Math.round(Date.now() / 1000 - sec));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

function fmtBytes(b: number | undefined) {
  if (b == null || isNaN(b)) return "—";
  if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`;
  if (b >= 1_048_576)     return `${(b / 1_048_576).toFixed(1)} MB`;
  if (b >= 1024)          return `${(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
}

// ─── status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const ok = status === "ok";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
        ok
          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-400"
          : "border-amber-500/30 bg-amber-500/10 text-amber-400"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
      {status}
    </span>
  );
}

// ─── Fleet Table Row ──────────────────────────────────────────────────────────

function NodeRow({
  sample,
  onDelete,
}: {
  sample: AgentSample;
  onDelete: (node: string, instance_id: string) => void;
}) {
  const nav = useNavigate();
  const reasons = parseReasons(sample.reasons_json);
  const dropWarn = (sample.cap_kernel_drop_percent ?? 0) > 1;
  const queueDepth = sample.ship_queue_depth_events ?? 0;
  const queueCap = sample.ship_queue_capacity_events || 4000;
  const queueRatio = queueDepth / queueCap;
  const queueWarn = queueRatio > 0.7;

  return (
    <tr
      onClick={() => nav(`/agent-stats/${encodeURIComponent(sample.node)}?instance_id=${encodeURIComponent(sample.instance_id)}`)}
      className="cursor-pointer border-b border-[rgba(255,255,255,0.05)] transition hover:bg-white/[0.03] group"
    >
      {/* node */}
      <td className="whitespace-nowrap px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] text-[#8b949e] group-hover:border-indigo-500/50 group-hover:text-indigo-300 transition">
            <Server size={14} />
          </div>
          <div>
            <div className="text-xs font-semibold text-[#f0f3f6] group-hover:text-indigo-300 transition">
              {sample.node}
            </div>
            <div className="text-[10px] text-[#59616b] font-mono">
              {sample.instance_id} · seq #{sample.sequence}
            </div>
          </div>
        </div>
      </td>

      {/* status */}
      <td className="px-4 py-3">
        <div className="flex flex-col gap-1">
          <StatusBadge status={sample.status} />
          {reasons.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {reasons.map((r) => (
                <span key={r} className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-mono text-amber-400">
                  {r}
                </span>
              ))}
            </div>
          )}
        </div>
      </td>

      {/* mode */}
      <td className="px-4 py-3 text-[11px] font-mono text-[#8b949e]">
        <span className="rounded bg-white/[0.04] px-1.5 py-0.5 border border-white/[0.06]">
          {sample.mode ?? "—"}
        </span>
      </td>

      {/* capture */}
      <td className="px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[11px] text-[#c9d1d9]">
            {n(sample.cap_events_emitted_delta)} evt/win
          </span>
          <span className={`font-mono text-[10px] ${dropWarn ? "text-amber-400" : "text-[#59616b]"}`}>
            k-drop {(sample.cap_kernel_drop_percent ?? 0).toFixed(3)}%
          </span>
        </div>
      </td>

      {/* shipping */}
      <td className="px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[11px] text-[#c9d1d9]">
            {(sample.ship_push_kbps ?? 0).toFixed(1)} kbps
          </span>
          <span className={`font-mono text-[10px] ${(sample.ship_drop_percent ?? 0) > 5 ? "text-rose-400" : "text-[#59616b]"}`}>
            drop {(sample.ship_drop_percent ?? 0).toFixed(1)}%
          </span>
        </div>
      </td>

      {/* queue */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 rounded-full bg-[rgba(255,255,255,0.08)] overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${queueWarn ? "bg-amber-400" : "bg-emerald-500"}`}
              style={{ width: `${Math.min(100, queueRatio * 100).toFixed(0)}%` }}
            />
          </div>
          <span className="font-mono text-[10px] text-[#8b949e]">
            {n(queueDepth)}/{n(queueCap)}
          </span>
        </div>
      </td>

      {/* cpu */}
      <td className="px-4 py-3">
        <span className={`font-mono text-[11px] ${(sample.res_cpu_percent_one_core ?? 0) > 80 ? "text-rose-400" : "text-[#c9d1d9]"}`}>
          {(sample.res_cpu_percent_one_core ?? 0).toFixed(1)}%
        </span>
      </td>

      {/* rss */}
      <td className="px-4 py-3 font-mono text-[11px] text-[#c9d1d9]">
        {fmtBytes(sample.res_rss_bytes)}
      </td>

      {/* last seen */}
      <td className="px-4 py-3 text-[11px] text-[#59616b]">
        {fmtAge(sample.observed_at)}
      </td>

      {/* action link & delete */}
      <td className="whitespace-nowrap px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-2.5">
          <div className="inline-flex items-center gap-1 text-[11px] font-medium text-indigo-400 group-hover:text-indigo-300 transition">
            <span>Drilldown</span>
            <ArrowRight size={13} className="group-hover:translate-x-0.5 transition" />
          </div>
          <button
            type="button"
            title={`Delete instance ${sample.instance_id} of node ${sample.node}`}
            onClick={(e) => {
              e.stopPropagation();
              onDelete(sample.node, sample.instance_id);
            }}
            className="grid h-7 w-7 place-items-center rounded-lg border border-transparent text-[#6e7681] hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-400 transition"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </td>
    </tr>
  );
}

// ─── Fleet Overview Page ───────────────────────────────────────────────────────

export function AgentStatsPage() {
  const nav = useNavigate();
  const [targetToDelete, setTargetToDelete] = useState<{ node: string; instance_id: string } | null>(null);
  const [deleteMode, setDeleteMode] = useState<"instance" | "node">("instance");
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["agent-stats-latest"],
    queryFn: () => fetchLatest(),
    refetchInterval: 15_000,
  });

  const samples = data?.items ?? [];
  const okCount = samples.filter((s) => s.status === "ok").length;
  const degradedCount = samples.filter((s) => s.status === "degraded").length;
  const totalFleetKbps = samples.reduce((s, x) => s + (x.ship_push_kbps ?? 0), 0);
  const totalFleetEps = samples.reduce((s, x) => s + (x.ship_push_events_per_second ?? 0), 0);

  const confirmDeleteTarget = async () => {
    if (!targetToDelete) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      if (deleteMode === "instance") {
        await deleteAgent(targetToDelete.node, targetToDelete.instance_id);
      } else {
        await deleteAgent(targetToDelete.node);
      }
      setTargetToDelete(null);
      await refetch();
    } catch (err: any) {
      setDeleteError(err.message || "Failed to delete agent");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <Page
      eyebrow="Infrastructure Fleet"
      title="Capture Agents"
      description="Live operational telemetry, capture health, and resource constraints for oldkernel NetworkTracing agents."
      actions={
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="btn"
          title="Refresh Fleet Status"
        >
          <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      }
    >
      {/* Fleet KPI Summary Cards */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard
          label="Reporting Nodes"
          value={String(samples.length)}
          detail={`${okCount} healthy · ${degradedCount} degraded`}
          tone={degradedCount > 0 ? "bad" : "good"}
        />
        <MetricCard
          label="Fleet Push Rate"
          value={`${n(totalFleetEps, 1)} ev/s`}
          detail="Aggregate event shipping rate"
        />
        <MetricCard
          label="Fleet Bandwidth"
          value={`${n(totalFleetKbps, 1)} kbps`}
          detail="Combined uplink consumption"
        />
        <MetricCard
          label="Health Ratio"
          value={samples.length ? `${((okCount / samples.length) * 100).toFixed(0)}%` : "—"}
          detail={`${okCount} of ${samples.length} nodes nominal`}
          tone={okCount === samples.length && samples.length > 0 ? "good" : "normal"}
        />
      </div>

      {/* Main Table Panel */}
      <Panel
        title="Active Agent Nodes"
        subtitle="Click any agent row to open the complete time-series performance and metric dashboard"
      >
        {isLoading ? (
          <Loading />
        ) : isError ? (
          <ErrorState message={(error as Error)?.message ?? "Failed to load agent stats"} />
        ) : samples.length === 0 ? (
          <div className="flex min-h-56 flex-col items-center justify-center gap-3 text-sm text-[#8b949e]">
            <Server size={36} className="opacity-20 text-indigo-400" />
            <div className="text-center">
              <div className="font-semibold text-[#f0f3f6]">No active agents reporting</div>
              <div className="mt-1 text-xs">
                Agents ship statistics via{" "}
                <code className="rounded bg-white/[0.05] px-1.5 py-0.5 font-mono text-indigo-300">
                  POST /api/agent/stats
                </code>
              </div>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.07)] text-[10px] uppercase tracking-wider text-[#59616b]">
                  {[
                    "Node / Instance",
                    "Status",
                    "Mode",
                    "Capture Rate",
                    "Shipping Rate",
                    "Queue Buffer",
                    "CPU Core",
                    "Memory RSS",
                    "Last Seen",
                    "",
                  ].map((h, idx) => (
                    <th key={idx} className="whitespace-nowrap px-4 py-2.5 text-left font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {samples.map((s) => (
                  <NodeRow
                    key={`${s.node}-${s.instance_id}`}
                    sample={s}
                    onDelete={(node, inst) => {
                      setTargetToDelete({ node, instance_id: inst });
                      setDeleteMode("instance");
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* Delete Confirmation Modal */}
      {targetToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-xl border border-[rgba(255,255,255,0.12)] bg-[#0e1116] p-5 shadow-2xl">
            <div className="flex items-center gap-3 text-rose-400">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-rose-500/10 border border-rose-500/20">
                <Trash2 size={20} />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-[#f0f3f6]">Delete Agent Telemetry</h3>
                <p className="text-xs text-[#8b949e]">Select deletion scope for {targetToDelete.node}</p>
              </div>
            </div>

            <div className="mt-4 space-y-2.5 text-xs text-[#c9d1d9]">
              <div className="rounded-lg border border-[rgba(255,255,255,0.06)] bg-white/[0.02] p-3 space-y-1">
                <div className="flex justify-between">
                  <span className="text-[#8b949e]">Node:</span>
                  <span className="font-mono font-semibold text-white">{targetToDelete.node}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#8b949e]">Target Instance:</span>
                  <span className="font-mono text-indigo-300">{targetToDelete.instance_id}</span>
                </div>
              </div>

              <div className="space-y-2 pt-1">
                <label className="flex items-start gap-2.5 p-2.5 rounded-lg border border-[rgba(255,255,255,0.06)] bg-white/[0.01] cursor-pointer hover:bg-white/[0.03] transition">
                  <input
                    type="radio"
                    name="deleteScope"
                    checked={deleteMode === "instance"}
                    onChange={() => setDeleteMode("instance")}
                    className="mt-0.5 accent-rose-500"
                  />
                  <div>
                    <div className="font-semibold text-[#f0f3f6]">Delete this instance only</div>
                    <div className="text-[11px] text-[#8b949e] mt-0.5">
                      Purges only instance <code className="font-mono text-indigo-300">{targetToDelete.instance_id}</code>. Other active or historical instances of <span className="font-mono text-white">{targetToDelete.node}</span> remain unaffected.
                    </div>
                  </div>
                </label>

                <label className="flex items-start gap-2.5 p-2.5 rounded-lg border border-rose-500/20 bg-rose-500/5 cursor-pointer hover:bg-rose-500/10 transition">
                  <input
                    type="radio"
                    name="deleteScope"
                    checked={deleteMode === "node"}
                    onChange={() => setDeleteMode("node")}
                    className="mt-0.5 accent-rose-500"
                  />
                  <div>
                    <div className="font-semibold text-rose-300">Delete entire node "{targetToDelete.node}"</div>
                    <div className="text-[11px] text-[#8b949e] mt-0.5">
                      Purges all instances and complete historical metrics recorded under this node hostname.
                    </div>
                  </div>
                </label>
              </div>
            </div>

            {deleteError && (
              <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-300">
                {deleteError}
              </div>
            )}

            <div className="mt-6 flex items-center justify-end gap-2.5">
              <button
                type="button"
                className="btn"
                disabled={isDeleting}
                onClick={() => {
                  setTargetToDelete(null);
                  setDeleteError(null);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isDeleting}
                onClick={confirmDeleteTarget}
                className="btn border-rose-500/40 bg-rose-600/80 hover:bg-rose-600 text-white font-semibold transition"
              >
                <Trash2 size={13} />
                <span>{isDeleting ? "Deleting…" : (deleteMode === "instance" ? "Delete Instance" : "Delete Whole Node")}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </Page>
  );
}

// ─── Dedicated Node Time-Series Dashboard Page ─────────────────────────────────

export function AgentNodeDetailPage() {
  const { node = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const nav = useNavigate();
  const queryInstanceId = searchParams.get("instance_id") || undefined;
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | undefined>(queryInstanceId);
  const [sampleLimit, setSampleLimit] = useState<number>(120);
  const [selectedTab, setSelectedTab] = useState<"all" | "shipping" | "capture" | "resources">("all");
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [deleteMode, setDeleteMode] = useState<"instance" | "node">("instance");
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const nodeDetailQuery = useQuery({
    queryKey: ["agent-node-detail", node, selectedInstanceId],
    queryFn: () => fetchNodeDetail(node, selectedInstanceId),
    refetchInterval: 15_000,
  });

  const latest = nodeDetailQuery.data?.latest;
  const activeInstanceId = selectedInstanceId || nodeDetailQuery.data?.instance_id || latest?.instance_id;
  const knownInstances = nodeDetailQuery.data?.instances || [];

  const historyQuery = useQuery({
    queryKey: ["agent-history", node, sampleLimit, activeInstanceId],
    queryFn: () => fetchHistory(node, sampleLimit, activeInstanceId),
    refetchInterval: 15_000,
  });

  const confirmDelete = async () => {
    setIsDeleting(true);
    setDeleteError(null);
    try {
      if (deleteMode === "instance" && activeInstanceId) {
        await deleteAgent(node, activeInstanceId);
        const remaining = knownInstances.filter((id) => id !== activeInstanceId);
        if (remaining.length > 0) {
          setSelectedInstanceId(remaining[0]);
          setSearchParams({ instance_id: remaining[0] });
          setShowDeleteModal(false);
          await nodeDetailQuery.refetch();
          await historyQuery.refetch();
        } else {
          nav("/agent-stats", { replace: true });
        }
      } else {
        await deleteAgent(node);
        nav("/agent-stats", { replace: true });
      }
    } catch (err: any) {
      setDeleteError(err.message || "Failed to delete agent");
      setIsDeleting(false);
    }
  };

  const historyRaw = historyQuery.data?.items ?? [];

  // Sort chronological (oldest to newest) for chart plotting
  const chartPoints = historyRaw
    .slice()
    .reverse()
    .map((item) => {
      const reasons = parseReasons(item.reasons_json);
      const rssMb = item.res_rss_bytes ? Math.round(item.res_rss_bytes / 1048576) : 0;
      return {
        timestamp: item.observed_at,
        time: fmtTs(item.observed_at),
        fullDate: fmtFullDate(item.observed_at),
        sequence: item.sequence,
        statusVal: item.status === "ok" ? 1 : 0,
        statusText: item.status,
        reasonsCount: reasons.length,
        // Throughput
        pushKbps: item.ship_push_kbps ?? 0,
        pushEps: item.ship_push_events_per_second ?? 0,
        // Drops
        shipDropPercent: item.ship_drop_percent ?? 0,
        kernelDropPercent: item.cap_kernel_drop_percent ?? 0,
        eventsDroppedDelta: item.ship_events_dropped_delta ?? 0,
        kernelDropsDelta: item.cap_kernel_drops_delta ?? 0,
        // Capture
        eventsEmittedDelta: item.cap_events_emitted_delta ?? 0,
        packetsDelta: item.cap_packets_delta ?? 0,
        flowsActive: item.cap_flows_active ?? 0,
        // Resources
        cpuPercent: item.res_cpu_percent_one_core ?? 0,
        rssMb: rssMb,
        openFds: item.res_open_fds ?? 0,
        threads: item.res_threads ?? 0,
        // Queue
        queueDepth: item.ship_queue_depth_events ?? 0,
        queueCapacity: item.ship_queue_capacity_events || 4000,
        queueHighWater: item.ship_queue_high_water_events ?? 0,
        consecutiveFailures: item.ship_consecutive_failures ?? 0,
        httpStatus: item.ship_last_push_http_status ?? 200,
      };
    });

  if (nodeDetailQuery.isLoading && historyQuery.isLoading) {
    return (
      <Page eyebrow="Agent Drilldown" title={node} description="Loading node telemetry and time-series history…">
        <Loading />
      </Page>
    );
  }

  if (nodeDetailQuery.isError || (!latest && !nodeDetailQuery.isLoading)) {
    return (
      <Page
        eyebrow="Agent Drilldown"
        title={node}
        description="Node not found or no telemetry received yet."
        actions={
          <button className="btn" onClick={() => nav("/agent-stats")}>
            <ArrowLeft size={13} />
            Agent Fleet
          </button>
        }
      >
        <ErrorState message={`No health telemetry records found for agent node "${node}".`} />
      </Page>
    );
  }

  const reasons = parseReasons(latest?.reasons_json);
  const limits = latest?.limits || {};

  return (
    <Page
      eyebrow="Infrastructure Drilldown"
      title={`Node: ${node}`}
      description={`Mode: ${latest?.mode ?? "native"} · Instance: ${activeInstanceId ?? "—"} · Sequence: #${latest?.sequence ?? 0} · Observed ${fmtAge(latest?.observed_at ?? 0)}`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {/* Instance Selector Dropdown if multiple instances exist */}
          {knownInstances.length > 1 && (
            <div className="flex items-center gap-1.5 rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] px-2.5 py-1">
              <span className="text-[11px] text-[#8b949e]">Instance:</span>
              <select
                value={activeInstanceId}
                onChange={(e) => {
                  const val = e.target.value;
                  setSelectedInstanceId(val);
                  setSearchParams({ instance_id: val });
                }}
                className="bg-transparent font-mono text-xs font-semibold text-indigo-300 focus:outline-none cursor-pointer"
              >
                {knownInstances.map((inst) => (
                  <option key={inst} value={inst} className="bg-[#0e1116] text-[#f0f3f6]">
                    {inst} {inst === knownInstances[0] ? "(current)" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Sample Window Limit Segmented Control */}
          <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] p-0.5">
            {[
              { label: "30 pts (~15m)", val: 30 },
              { label: "60 pts (~30m)", val: 60 },
              { label: "120 pts (~1h)", val: 120 },
              { label: "240 pts (~2h)", val: 240 },
            ].map(({ label, val }) => (
              <button
                key={val}
                onClick={() => setSampleLimit(val)}
                className={`rounded px-2 py-1 text-xs font-medium transition ${
                  sampleLimit === val
                    ? "bg-white/[0.12] text-white shadow-sm font-semibold"
                    : "text-[#8b949e] hover:text-[#f0f3f6]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <button
            className="btn"
            onClick={() => {
              nodeDetailQuery.refetch();
              historyQuery.refetch();
            }}
            disabled={historyQuery.isFetching}
            title="Refresh Time Series"
          >
            <RefreshCw size={13} className={historyQuery.isFetching ? "animate-spin" : ""} />
            Refresh
          </button>

          <button
            className="btn border-rose-500/30 text-rose-400 hover:bg-rose-500/10 hover:border-rose-500/50 transition"
            onClick={() => setShowDeleteModal(true)}
            title="Delete this agent node and its entire telemetry history"
          >
            <Trash2 size={13} />
            <span>Delete Node</span>
          </button>

          <button className="btn" onClick={() => nav("/agent-stats")}>
            <ArrowLeft size={13} />
            All Agents
          </button>
        </div>
      }
    >
      {/* Node Status Banner */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[rgba(255,255,255,0.07)] bg-[#0e1116] p-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
            <Server size={20} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold text-[#f0f3f6]">{node}</span>
              <StatusBadge status={latest?.status ?? "unknown"} />
              <span className="rounded bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-[#8b949e]">
                {latest?.mode ?? "cpp"}
              </span>
            </div>
            <div className="mt-0.5 text-xs text-[#8b949e]">
              Last heartbeat: <span className="font-mono text-[#c9d1d9]">{fmtFullDate(latest?.observed_at ?? 0)}</span> ({fmtAge(latest?.observed_at ?? 0)})
            </div>
          </div>
        </div>

        {reasons.length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold text-amber-400">Active Degradation Causes:</span>
            {reasons.map((r) => (
              <span key={r} className="rounded bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 text-xs font-mono text-amber-300">
                {r}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Key Metric Snapshot Cards */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard
          label="Shipping Throughput"
          value={`${(latest?.ship_push_kbps ?? 0).toFixed(1)} kbps`}
          detail={`${(latest?.ship_push_events_per_second ?? 0).toFixed(1)} events/sec pushed`}
        />
        <MetricCard
          label="Drop & Loss Rate"
          value={`${(latest?.ship_drop_percent ?? 0).toFixed(2)}%`}
          detail={`Kernel drop: ${(latest?.cap_kernel_drop_percent ?? 0).toFixed(3)}%`}
          tone={(latest?.ship_drop_percent ?? 0) > 2 || (latest?.cap_kernel_drop_percent ?? 0) > 1 ? "bad" : "normal"}
        />
        <MetricCard
          label="Process CPU & Memory"
          value={`${(latest?.res_cpu_percent_one_core ?? 0).toFixed(1)}%`}
          detail={`RSS: ${fmtBytes(latest?.res_rss_bytes)} (${latest?.res_threads ?? 1} threads)`}
          tone={(latest?.res_cpu_percent_one_core ?? 0) > 80 ? "bad" : "normal"}
        />
        <MetricCard
          label="Buffer Queue Depth"
          value={`${n(latest?.ship_queue_depth_events)} / ${n(latest?.ship_queue_capacity_events || 4000)}`}
          detail={`High-water: ${n(latest?.ship_queue_high_water_events)} events`}
          tone={
            latest?.ship_queue_depth_events != null &&
            latest?.ship_queue_capacity_events != null &&
            latest.ship_queue_depth_events / (latest.ship_queue_capacity_events || 1) > 0.7
              ? "bad"
              : "normal"
          }
        />
      </div>

      {/* Time-Series Charts Section */}
      <div className="space-y-6">
        {/* 1. Throughput & Shipping Rate Time Series */}
        <Panel
          title="Shipping Throughput & Event Rate Over Time"
          subtitle="Real-time uplink rate (kbps) and event publishing velocity (events/s) across sample windows"
        >
          {chartPoints.length === 0 ? (
            <div className="h-64 flex items-center justify-center text-xs text-[#6e7681]">
              Awaiting consecutive historical sample snapshots…
            </div>
          ) : (
            <div className="h-72 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartPoints}>
                  <defs>
                    <linearGradient id="colorKbps" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="colorEps" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="time" stroke="#59616b" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="left" stroke="#10b981" tick={{ fontSize: 11 }} unit=" kbps" />
                  <YAxis yAxisId="right" orientation="right" stroke="#818cf8" tick={{ fontSize: 11 }} unit=" ev/s" />
                  <Tooltip
                    {...chartTooltip}
                    formatter={(v: any, name: any) => [
                      name === "Throughput (kbps)" ? `${Number(v).toFixed(2)} kbps` : `${Number(v).toFixed(2)} ev/s`,
                      name,
                    ]}
                  />
                  <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="pushKbps"
                    name="Throughput (kbps)"
                    stroke="#10b981"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorKbps)"
                  />
                  <Area
                    yAxisId="right"
                    type="monotone"
                    dataKey="pushEps"
                    name="Push Velocity (ev/s)"
                    stroke="#818cf8"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorEps)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        {/* 2. Drops & Loss Timeline */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Panel
            title="Drop Rate & In-Flight Loss Over Time"
            subtitle="Kernel socket buffer packet drop % vs Agent shipping queue drop %"
          >
            {chartPoints.length === 0 ? (
              <div className="h-60 flex items-center justify-center text-xs text-[#6e7681]">No history</div>
            ) : (
              <div className="h-64 p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartPoints}>
                    <defs>
                      <linearGradient id="colorShipDrop" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="colorKernDrop" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="time" stroke="#59616b" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#8b949e" tick={{ fontSize: 10 }} unit="%" />
                    <Tooltip
                      {...chartTooltip}
                      formatter={(v: any, name: any) => [`${Number(v).toFixed(3)}%`, name]}
                    />
                    <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                    <Area
                      type="monotone"
                      dataKey="shipDropPercent"
                      name="Shipping Drop %"
                      stroke="#f43f5e"
                      strokeWidth={1.5}
                      fill="url(#colorShipDrop)"
                    />
                    <Area
                      type="monotone"
                      dataKey="kernelDropPercent"
                      name="Kernel tp_drop %"
                      stroke="#f59e0b"
                      strokeWidth={1.5}
                      fill="url(#colorKernDrop)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          {/* 3. System Resources Timeline */}
          <Panel
            title="System Resources & Footprint Over Time"
            subtitle="Pinned CPU consumption (1-core scale) and Resident Set Size (MB)"
          >
            {chartPoints.length === 0 ? (
              <div className="h-60 flex items-center justify-center text-xs text-[#6e7681]">No history</div>
            ) : (
              <div className="h-64 p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartPoints}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="time" stroke="#59616b" tick={{ fontSize: 10 }} />
                    <YAxis yAxisId="left" stroke="#818cf8" tick={{ fontSize: 10 }} unit="%" domain={[0, 'auto']} />
                    <YAxis yAxisId="right" orientation="right" stroke="#34d399" tick={{ fontSize: 10 }} unit=" MB" />
                    <Tooltip
                      {...chartTooltip}
                      formatter={(v: any, name: any) => [
                        name === "CPU One-Core %" ? `${Number(v).toFixed(1)}%` : `${Number(v).toFixed(0)} MB`,
                        name,
                      ]}
                    />
                    <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="cpuPercent"
                      name="CPU One-Core %"
                      stroke="#818cf8"
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="rssMb"
                      name="Memory RSS (MB)"
                      stroke="#34d399"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>
        </div>

        {/* 4. Queue Depth & Emission Delta */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Panel
            title="Shipping Queue Backpressure Over Time"
            subtitle="Queue buffer occupancy vs high-water mark"
          >
            {chartPoints.length === 0 ? (
              <div className="h-60 flex items-center justify-center text-xs text-[#6e7681]">No history</div>
            ) : (
              <div className="h-64 p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartPoints}>
                    <defs>
                      <linearGradient id="colorQueue" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="time" stroke="#59616b" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#8b949e" tick={{ fontSize: 10 }} unit=" ev" />
                    <Tooltip {...chartTooltip} />
                    <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                    <Area
                      type="monotone"
                      dataKey="queueDepth"
                      name="Queue Depth (events)"
                      stroke="#38bdf8"
                      strokeWidth={2}
                      fill="url(#colorQueue)"
                    />
                    <Line
                      type="stepAfter"
                      dataKey="queueHighWater"
                      name="High-Water Mark"
                      stroke="#fbbf24"
                      strokeWidth={1.5}
                      strokeDasharray="4 4"
                      dot={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel
            title="Capture Packet & Event Volume Over Time"
            subtitle="Packets captured vs parsed events emitted per window"
          >
            {chartPoints.length === 0 ? (
              <div className="h-60 flex items-center justify-center text-xs text-[#6e7681]">No history</div>
            ) : (
              <div className="h-64 p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartPoints}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="time" stroke="#59616b" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#8b949e" tick={{ fontSize: 10 }} />
                    <Tooltip {...chartTooltip} />
                    <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                    <Line
                      type="monotone"
                      dataKey="eventsEmittedDelta"
                      name="Emitted Events (delta)"
                      stroke="#a855f7"
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="flowsActive"
                      name="Active Network Flows"
                      stroke="#f97316"
                      strokeWidth={1.5}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>
        </div>

        {/* 5. Agent Constraints & Process Isolation Specs */}
        <Panel title="Process Safety & Hardware Constraints" subtitle="Enforced host-protection limits reported by agent">
          <div className="grid grid-cols-2 gap-4 p-5 sm:grid-cols-3 lg:grid-cols-6 text-xs">
            <div className="flex flex-col gap-1 border-r border-[rgba(255,255,255,0.06)] pr-3">
              <span className="text-[10px] uppercase font-semibold text-[#6e7681]">CPU Core Pin</span>
              <span className="font-mono text-[#f0f3f6] text-sm">Core #{String(limits.cpu_core ?? latest?.lim_cpu_core ?? "2")}</span>
              <span className="text-[10px] text-[#8b949e]">Affinity isolated</span>
            </div>
            <div className="flex flex-col gap-1 border-r border-[rgba(255,255,255,0.06)] pr-3">
              <span className="text-[10px] uppercase font-semibold text-[#6e7681]">Bandwidth Ceiling</span>
              <span className="font-mono text-[#f0f3f6] text-sm">{limits.ship_rate_kbps ?? latest?.lim_ship_rate_kbps ?? 1024} kbps</span>
              <span className="text-[10px] text-[#8b949e]">Rate limiter capped</span>
            </div>
            <div className="flex flex-col gap-1 border-r border-[rgba(255,255,255,0.06)] pr-3">
              <span className="text-[10px] uppercase font-semibold text-[#6e7681]">Address Space Limit</span>
              <span className="font-mono text-[#f0f3f6] text-sm">{fmtBytes(limits.address_space_bytes ?? latest?.lim_address_space_bytes ?? 268435456)}</span>
              <span className="text-[10px] text-[#8b949e]">RLIMIT_AS hard ceiling</span>
            </div>
            <div className="flex flex-col gap-1 border-r border-[rgba(255,255,255,0.06)] pr-3">
              <span className="text-[10px] uppercase font-semibold text-[#6e7681]">Max Upload Body</span>
              <span className="font-mono text-[#f0f3f6] text-sm">{fmtBytes(limits.http_body_max_bytes ?? latest?.lim_http_body_max_bytes ?? 65536)}</span>
              <span className="text-[10px] text-[#8b949e]">Single batch cap</span>
            </div>
            <div className="flex flex-col gap-1 border-r border-[rgba(255,255,255,0.06)] pr-3">
              <span className="text-[10px] uppercase font-semibold text-[#6e7681]">Max Ship Threads</span>
              <span className="font-mono text-[#f0f3f6] text-sm">{limits.ship_threads_max ?? latest?.lim_ship_threads_max ?? 8} threads</span>
              <span className="text-[10px] text-[#8b949e]">Worker thread pool</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] uppercase font-semibold text-[#6e7681]">WSSE Body Window</span>
              <span className="font-mono text-[#f0f3f6] text-sm">{fmtBytes(limits.wsse_body_bytes ?? latest?.lim_wsse_body_bytes ?? 8192)}</span>
              <span className="text-[10px] text-[#8b949e]">Sanitization window</span>
            </div>
          </div>
        </Panel>

        {/* 6. Chronological Sample History Table */}
        <Panel
          title={`Historical Telemetry Snapshots (Last ${historyRaw.length} points)`}
          subtitle="Idempotent sequential telemetry records reported by this agent node"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] text-[10px] uppercase tracking-wider text-[#59616b]">
                  <th className="px-4 py-2.5 text-left font-semibold">Sequence</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Observation Time</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Status</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Throughput</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Push Rate</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Drops</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Queue</th>
                  <th className="px-4 py-2.5 text-left font-semibold">CPU</th>
                  <th className="px-4 py-2.5 text-left font-semibold">RSS</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Reasons / Degradation</th>
                </tr>
              </thead>
              <tbody>
                {historyRaw.map((h) => {
                  const rList = parseReasons(h.reasons_json);
                  return (
                    <tr
                      key={`${h.node}-${h.instance_id}-${h.sequence}`}
                      className="border-b border-[rgba(255,255,255,0.04)] hover:bg-white/[0.02] font-mono text-[11px]"
                    >
                      <td className="px-4 py-2.5 text-[#8b949e]">#{h.sequence}</td>
                      <td className="px-4 py-2.5 text-[#c9d1d9]">{fmtFullDate(h.observed_at)}</td>
                      <td className="px-4 py-2.5">
                        <StatusBadge status={h.status} />
                      </td>
                      <td className="px-4 py-2.5 text-[#f0f3f6]">
                        {(h.ship_push_kbps ?? 0).toFixed(1)} kbps
                      </td>
                      <td className="px-4 py-2.5 text-[#c9d1d9]">
                        {(h.ship_push_events_per_second ?? 0).toFixed(1)} ev/s
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={(h.ship_drop_percent ?? 0) > 1 ? "text-rose-400 font-semibold" : "text-[#8b949e]"}>
                          {(h.ship_drop_percent ?? 0).toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-[#8b949e]">
                        {n(h.ship_queue_depth_events)} / {n(h.ship_queue_capacity_events || 4000)}
                      </td>
                      <td className="px-4 py-2.5 text-[#c9d1d9]">
                        {(h.res_cpu_percent_one_core ?? 0).toFixed(1)}%
                      </td>
                      <td className="px-4 py-2.5 text-[#8b949e]">
                        {fmtBytes(h.res_rss_bytes)}
                      </td>
                      <td className="px-4 py-2.5">
                        {rList.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {rList.map((r) => (
                              <span key={r} className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-400">
                                {r}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-[#59616b]">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-xl border border-[rgba(255,255,255,0.12)] bg-[#0e1116] p-5 shadow-2xl">
            <div className="flex items-center gap-3 text-rose-400">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-rose-500/10 border border-rose-500/20">
                <Trash2 size={20} />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-[#f0f3f6]">Delete Agent Node</h3>
                <p className="text-xs text-[#8b949e]">Confirm permanent telemetry removal</p>
              </div>
            </div>

            <div className="mt-4 space-y-2.5 text-xs text-[#c9d1d9]">
              <div className="rounded-lg border border-[rgba(255,255,255,0.06)] bg-white/[0.02] p-3 space-y-1">
                <div className="flex justify-between">
                  <span className="text-[#8b949e]">Node:</span>
                  <span className="font-mono font-semibold text-white">{node}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#8b949e]">Target Instance:</span>
                  <span className="font-mono text-indigo-300">{activeInstanceId ?? "all"}</span>
                </div>
              </div>

              <div className="space-y-2 pt-1">
                {activeInstanceId && (
                  <label className="flex items-start gap-2.5 p-2.5 rounded-lg border border-[rgba(255,255,255,0.06)] bg-white/[0.01] cursor-pointer hover:bg-white/[0.03] transition">
                    <input
                      type="radio"
                      name="detailDeleteScope"
                      checked={deleteMode === "instance"}
                      onChange={() => setDeleteMode("instance")}
                      className="mt-0.5 accent-rose-500"
                    />
                    <div>
                      <div className="font-semibold text-[#f0f3f6]">Delete this instance only</div>
                      <div className="text-[11px] text-[#8b949e] mt-0.5">
                        Purges only instance <code className="font-mono text-indigo-300">{activeInstanceId}</code>. Other instances for this node will remain intact.
                      </div>
                    </div>
                  </label>
                )}

                <label className="flex items-start gap-2.5 p-2.5 rounded-lg border border-rose-500/20 bg-rose-500/5 cursor-pointer hover:bg-rose-500/10 transition">
                  <input
                    type="radio"
                    name="detailDeleteScope"
                    checked={deleteMode === "node"}
                    onChange={() => setDeleteMode("node")}
                    className="mt-0.5 accent-rose-500"
                  />
                  <div>
                    <div className="font-semibold text-rose-300">Delete entire node "{node}"</div>
                    <div className="text-[11px] text-[#8b949e] mt-0.5">
                      Purges all {knownInstances.length} instances and complete historical metrics recorded under this node hostname.
                    </div>
                  </div>
                </label>
              </div>
            </div>

            {deleteError && (
              <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-300">
                {deleteError}
              </div>
            )}

            <div className="mt-6 flex items-center justify-end gap-2.5">
              <button
                type="button"
                className="btn"
                disabled={isDeleting}
                onClick={() => {
                  setShowDeleteModal(false);
                  setDeleteError(null);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isDeleting}
                onClick={confirmDelete}
                className="btn border-rose-500/40 bg-rose-600/80 hover:bg-rose-600 text-white font-semibold transition"
              >
                <Trash2 size={13} />
                <span>{isDeleting ? "Deleting…" : (deleteMode === "instance" ? "Delete Instance" : "Delete Whole Node")}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </Page>
  );
}
