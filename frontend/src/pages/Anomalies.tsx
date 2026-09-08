import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowLeft,
  Check,
  Clock,
  ExternalLink,
  Eye,
  Info,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";
import { api, queryString } from "../api";
import {
  ErrorState,
  Loading,
  MetricCard,
  Page,
  Panel,
  chartTooltip,
  n,
} from "../components";
import { useFilters } from "../App";
import type { Anomaly, SeriesPoint } from "../types";

export function AnomaliesPage() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  const qs = queryString(filters, status ? { status } : {});

  const q = useQuery({
    queryKey: ["anomalies", qs],
    queryFn: () => api<{ items: Anomaly[] }>(`/api/v1/anomalies?${qs}`),
  });
  return (
    <Page
      eyebrow="Explainable Detection"
      title="Structural & Metric Anomalies"
      description="Transparent Wilson score confidence intervals and MAD baseline comparisons against matching minute-of-week distributions."
      actions={
        <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.03] p-0.5">
          {[
            { label: "All", val: "" },
            { label: "Open", val: "open" },
            { label: "Acknowledged", val: "acknowledged" },
            { label: "Resolved", val: "resolved" },
            { label: "Suppressed", val: "suppressed" },
          ].map(({ label, val }) => (
            <button
              key={label}
              onClick={() => setStatus(val)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                status === val
                  ? "bg-white/[0.12] text-white shadow-sm"
                  : "text-[#8b949e] hover:text-[#f0f3f6]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      }
    >
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState message={q.error.message} />
      ) : (
        <Panel
          title={`${q.data?.items.length || 0} Detected Findings`}
          subtitle="Ordered by severity and detection recency. Select an incident row to inspect baseline evidence."
        >
          <div className="overflow-auto scrollbar">
            <table className="w-full min-w-[1100px]">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01]">
                  {[
                    "Severity",
                    "Entity & Detector",
                    "Window Timing",
                    "Current Value",
                    "Expected Baseline",
                    "Absolute Δ",
                    "Relative Change",
                    "Samples (cur/base)",
                    "Persistence",
                    "Entity Type",
                    "Status",
                  ].map((h) => (
                    <th key={h} className="table-head px-4 py-2.5">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {q.data?.items.map((a) => (
                  <tr
                    key={a.id}
                    onClick={() =>
                      nav(`/anomalies/${a.id}?${queryString(filters)}`)
                    }
                    className="cursor-pointer border-b border-[rgba(255,255,255,0.04)] transition hover:bg-white/[0.03]"
                  >
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                          a.severity === "critical"
                            ? "border border-rose-500/30 bg-rose-500/10 text-rose-400"
                            : a.severity === "high"
                              ? "border border-amber-500/30 bg-amber-500/10 text-amber-400"
                              : "border border-indigo-500/30 bg-indigo-500/10 text-indigo-400"
                        }`}
                      >
                        {a.severity}
                      </span>
                    </td>
                    <td className="px-4 font-mono">
                      <div className="text-xs font-semibold text-[#f0f3f6]">{a.entity_id || a.target_service || a.caller_service || "Service"}</div>
                      <div className="text-[10px] text-[#8b949e]">
                        {(a.anomaly_type || "").replaceAll("_", " ")}
                      </div>
                    </td>
                    <td className="px-4 font-mono text-[10px] text-[#8b949e]">
                      {new Date(a.last_detected_ms || a.detected_at || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      <span className="block text-[9px] text-[#6e7681]">
                        {new Date(a.last_detected_ms || a.detected_at || Date.now()).toLocaleDateString()}
                      </span>
                    </td>
                    <td className="px-4 font-mono text-xs tabular-nums font-medium text-[#f0f3f6]">
                      {n(a.current_value || 0)} {a.unit || ""}
                    </td>
                    <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">
                      {a.baseline_value == null
                        ? "—"
                        : `${n(a.normal_low ?? a.baseline_value)}–${n(a.normal_high ?? a.baseline_value)} ${a.unit || ""}`}
                    </td>
                    <td className="px-4 font-mono text-xs tabular-nums text-[#f43f5e]">
                      {(a.absolute_difference || 0) > 0 ? "+" : ""}
                      {n(a.absolute_difference ?? Math.abs((a.current_value || 0) - (a.baseline_value || 0)))}
                    </td>
                    <td className="px-4 font-mono text-xs tabular-nums">
                      {a.percent_change == null && a.delta_percentage == null ? (
                        <span className="text-[#6e7681]">n/a</span>
                      ) : (
                        (() => {
                          const pct = Number(a.percent_change ?? a.delta_percentage ?? 0);
                          return (
                            <span className={pct > 0 ? "text-[#f43f5e]" : "text-[#10b981]"}>
                              {pct > 0 ? "+" : ""}
                              {pct.toFixed(0)}%
                            </span>
                          );
                        })()
                      )}
                    </td>
                    <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">
                      {n(a.current_samples ?? 0)} / {n(a.baseline_samples ?? 0)}
                    </td>
                    <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">
                      {a.persistence_buckets || 1} bucket{(a.persistence_buckets || 1) > 1 ? "s" : ""}
                    </td>
                    <td className="px-4">
                      <span className="rounded bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-[#8b949e]">
                        {a.entity_type || (a.target_service ? "service" : "operation")}
                      </span>
                    </td>
                    <td className="px-4">
                      <span className="chip uppercase text-[10px]">{a.status || "open"}</span>
                    </td>
                  </tr>
                ))}
                {!q.data?.items.length && (
                  <tr>
                    <td
                      colSpan={11}
                      className="p-12 text-center text-xs text-[#8b949e]"
                    >
                      No anomalies detected matching this lifecycle filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </Page>
  );
}

type Detail = Anomaly & {
  series?: SeriesPoint[];
  training_start_ms?: number;
  training_end_ms?: number;
};

export function AnomalyDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const client = useQueryClient();

  const q = useQuery({
    queryKey: ["anomaly", id],
    queryFn: () => api<Detail>(`/api/v1/anomalies/${id}`),
  });
  const relatedUsers = useQuery({
    queryKey: ["anomaly-users", id],
    queryFn: () => api<{items:Array<{principal_name:string;requests:number;traffic_share:number;changes:Array<{id:number;change_type:string;severity:string}>}>}>(`/api/v1/anomalies/${id}/users`),
  });

  const mutate = useMutation({
    mutationFn: (status: string) =>
      api(`/api/v1/anomalies/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status,
          suppressed_until:
            status === "suppressed"
              ? new Date(Date.now() + 24 * 3600_000).toISOString()
              : null,
        }),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["anomaly", id] });
      client.invalidateQueries({ queryKey: ["anomalies"] });
    },
  });

  if (q.isLoading) {
    return (
      <Page eyebrow="Incident Investigation" title="Loading incident…" description="">
        <Loading />
      </Page>
    );
  }

  if (q.error) {
    return (
      <Page eyebrow="Incident Investigation" title="Incident Unavailable" description="">
        <ErrorState message={q.error.message} />
      </Page>
    );
  }

  const a = q.data!;
  const metric = a.anomaly_type?.includes("latency") ? "p95_ms" : "rps";
  const chartData = (a.series || []).map((p) => ({ ...p, expected: a.baseline_value }));

  return (
    <Page
      eyebrow={`Finding #${a.id} · ${(a.severity || "info").toUpperCase()} · ${(a.status || "open").toUpperCase()}`}
      title={`${a.entity_id || "Target"}: ${(a.anomaly_type || "").replaceAll("_", " ")}`}
      description={a.explanation}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="btn"
            onClick={() => nav(-1)}
          >
            <ArrowLeft size={13} />
            Back
          </button>
          <button
            className="btn hover:border-indigo-500/40 hover:bg-indigo-500/10 hover:text-indigo-300"
            onClick={() => mutate.mutate("acknowledged")}
          >
            <Eye size={13} />
            Acknowledge
          </button>
          <button
            className="btn hover:border-emerald-500/40 hover:bg-emerald-500/10 hover:text-emerald-300"
            onClick={() => mutate.mutate("resolved")}
          >
            <Check size={13} />
            Mark Resolved
          </button>
          <button
            className="btn hover:border-amber-500/40 hover:bg-amber-500/10 hover:text-amber-300"
            onClick={() => mutate.mutate("suppressed")}
          >
            <Clock size={13} />
            Suppress 24h
          </button>
        </div>
      }
    >
      {/* What Changed Compared With Normal Explainability Card */}
      <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-5 backdrop-blur-sm">
        <div className="flex items-center gap-2 mb-2">
          <ShieldAlert className="text-indigo-400" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-indigo-200">
            What Changed Compared With Normal?
          </h3>
        </div>
        <p className="text-xs text-[#c9d1d9] leading-relaxed">
          {a.explanation}
        </p>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2 pt-3 border-t border-[rgba(255,255,255,0.06)]">
          <div className="rounded-lg border border-[rgba(255,255,255,0.06)] bg-white/[0.02] p-3.5 text-xs">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
              <AlertTriangle size={12} /> Probable Incident Origin
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="font-mono text-sm font-bold text-white">
                {a.root_cause?.origin_service || a.entity_id}
              </span>
              {a.root_cause?.confidence_score != null && (
                <span className="text-[10px] font-mono text-[#8b949e]">
                  (confidence: {(Number(a.root_cause.confidence_score) * 100).toFixed(0)}%)
                </span>
              )}
            </div>
            <p className="mt-1 text-[11px] text-[#8b949e]">
              {a.root_cause?.reason || "Observed baseline deviation originated on this service component."}
            </p>
          </div>

          <div className="rounded-lg border border-[rgba(255,255,255,0.06)] bg-white/[0.02] p-3.5 text-xs">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-rose-400 flex items-center gap-1.5">
              <AlertOctagon size={12} /> Incident Blast Radius
            </span>
            <div className="mt-2 space-y-1.5 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-[#8b949e]">Upstream Callers:</span>
                <span className="font-mono text-[#f0f3f6]">
                  {a.blast_radius?.direct_callers?.length ? a.blast_radius.direct_callers.join(", ") : "None detected"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#8b949e]">Affected Principals:</span>
                <span className="font-mono text-indigo-300">
                  {a.blast_radius?.affected_principals?.length ? a.blast_radius.affected_principals.join(", ") : "None identified"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#8b949e]">Impacted Operations:</span>
                <span className="font-mono text-[#f0f3f6]">
                  {a.blast_radius?.affected_operations?.length || 1} operations
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <MetricCard
          label="Current Value"
          value={`${n(a.current_value || 0)} ${a.unit || ""}`}
          detail={`n=${n(a.current_samples || 0)} samples`}
          tone="bad"
        />
        <MetricCard
          label="Expected Baseline"
          value={
            a.baseline_value === null || a.baseline_value === undefined
              ? "Unavailable"
              : `${n(a.baseline_value)} ${a.unit || ""}`
          }
          detail={`Baseline n=${n(a.baseline_samples || 0)}`}
        />
        <MetricCard
          label="Absolute Delta"
          value={`${(a.absolute_difference || 0) > 0 ? "+" : ""}${n(a.absolute_difference || 0)} ${a.unit || ""}`}
          detail="Observed minus expected"
        />
        <MetricCard
          label="Relative Shift"
          value={
            a.percent_change == null && a.delta_percentage == null
              ? "n/a"
              : `${Number(a.percent_change ?? a.delta_percentage ?? 0) > 0 ? "+" : ""}${Number(a.percent_change ?? a.delta_percentage ?? 0).toFixed(0)}%`
          }
          detail="Non-zero baseline shift"
        />
        <MetricCard
          label="Persistence"
          value={`${a.persistence_buckets || 1} bucket${(a.persistence_buckets || 1) > 1 ? "s" : ""}`}
          detail="Consecutive detections"
        />
      </div>

      <Panel
        title="Incident Time Horizon: Actual vs Expected Baseline"
        subtitle={`Shaded region highlights the anomaly window (${a.unit || "metrics"})`}
        className="mt-4"
      >
        <div className="h-[340px] p-4">
          <ResponsiveContainer>
            <ComposedChart data={chartData}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="timestamp_ms"
                tickFormatter={(v) =>
                  new Date(v).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                }
                stroke="#484f58"
              />
              <YAxis stroke="#484f58" />
              <Tooltip {...chartTooltip} />
              <ReferenceArea
                x1={a.window_start_ms}
                x2={a.window_end_ms}
                fill="#f43f5e"
                fillOpacity={0.15}
              />
              <Area
                dataKey={metric}
                stroke="#818cf8"
                fill="#6366f1"
                fillOpacity={0.15}
                name="Actual Observed"
              />
              <Line
                dataKey="expected"
                stroke="#10b981"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                dot={false}
                name="Expected Baseline"
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel
          title="Detection Logic & Evaluation Context"
          subtitle="Wilson score & MAD threshold specifics"
        >
          <div className="p-5 space-y-4">
            <div className="rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] p-4 text-xs leading-relaxed text-[#c9d1d9] font-mono">
              {a.rule || "Baseline MAD & rolling statistics thresholding"}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Fact
                k="Training Window"
                v={a.training_start_ms && a.training_end_ms ? `${new Date(a.training_start_ms).toLocaleTimeString()} – ${new Date(a.training_end_ms).toLocaleTimeString()}` : "Dynamic 7-day rolling"}
              />
              <Fact
                k="Incident Window"
                v={a.window_start_ms && a.window_end_ms ? `${new Date(a.window_start_ms).toLocaleTimeString()} – ${new Date(a.window_end_ms).toLocaleTimeString()}` : (a.last_detected_ms ? new Date(a.last_detected_ms).toLocaleTimeString() : "Recent")}
              />
              <Fact k="Current Samples" v={n(a.current_samples)} />
              <Fact k="Baseline Samples" v={n(a.baseline_samples)} />
            </div>
          </div>
        </Panel>

        <Panel
          title="Evidence & Diagnostic Limitations"
          subtitle="Contributing dimensions and explicit limitations"
        >
          <div className="p-5 space-y-4">
            {Boolean(a.contributors && a.contributors.length > 0) && (
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-2">
                  Contributing Factors
                </div>
                <div className="space-y-2">
                  {(a.contributors || []).map((c, i) => (
                    <pre
                      key={i}
                      className="overflow-auto rounded-lg border border-[rgba(255,255,255,0.08)] bg-black/40 p-3 font-mono text-[11px] text-[#c9d1d9]"
                    >
                      {JSON.stringify(c, null, 2)}
                    </pre>
                  ))}
                </div>
              </div>
            )}

            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-2">
                Documented Limitations
              </div>
              <div className="space-y-1.5">
                {(a.limitations && a.limitations.length > 0 ? a.limitations : [
                  "Inference relies on observed transaction spans and 60s metric bucket rollups.",
                  "Baselines update dynamically across rolling 24h & 7d matching minute windows."
                ]).map((l) => (
                  <div
                    key={l}
                    className="flex items-start gap-2 rounded-md border border-amber-500/20 bg-amber-500/5 p-2.5 text-xs text-amber-200/80"
                  >
                    <ShieldAlert size={14} className="mt-0.5 shrink-0 text-amber-400" />
                    <span>{l}</span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-2">
                Representative Traces
              </div>
              {Boolean(a.trace_ids && a.trace_ids.length > 0) ? (
                <div className="flex flex-wrap gap-2">
                  {(a.trace_ids || []).map((trace) => (
                    <a
                      key={trace}
                      href={`/api/v1/traces/${encodeURIComponent(trace)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 rounded-md border border-[rgba(255,255,255,0.08)] bg-white/[0.03] px-2.5 py-1 font-mono text-xs text-indigo-400 hover:border-indigo-500/40 hover:bg-white/[0.06]"
                    >
                      <span>{trace.slice(0, 16)}…</span>
                      <ExternalLink size={11} />
                    </a>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-[#8b949e]">
                  No individual trace IDs were retained for this aggregate statistical finding.
                </div>
              )}
            </div>
          </div>
        </Panel>
      </div>
      <Panel title="Related Users" subtitle="Principals contributing traffic during the telemetry anomaly window" className="mt-4">
        <div className="divide-y divide-white/[.05]">{(relatedUsers.data?.items||[]).map(user=><button key={user.principal_name} onClick={()=>nav(`/users/${encodeURIComponent(user.principal_name)}`)} className="flex w-full items-center justify-between gap-4 p-3 text-left hover:bg-white/[.03]"><div><div className="font-mono text-xs text-indigo-300">{user.principal_name}</div><div className="mt-1 text-[10px] text-[#8b949e]">{user.changes.length?user.changes.map(c=>c.change_type.replaceAll("_"," ")).join(" · "):"No user changes in anomaly window"}</div></div><div className="text-right"><div className="font-mono text-sm">{(user.traffic_share*100).toFixed(1)}%</div><div className="text-[10px] text-[#8b949e]">{user.requests} requests</div></div></button>)}</div>
      </Panel>
    </Page>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-lg border border-[rgba(255,255,255,0.06)] bg-white/[0.02] p-3">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e]">{k}</div>
      <div className="mt-1 text-xs font-medium text-[#f0f3f6]">{v}</div>
    </div>
  );
}
