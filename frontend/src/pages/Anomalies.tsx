import { useState, useMemo } from "react";
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
  ArrowRight,
  Check,
  Clock,
  ExternalLink,
  Eye,
  Info,
  Search,
  Shield,
  ShieldAlert,
  SlidersHorizontal,
  User,
  UserCheck,
  UserRoundSearch,
  Users,
  Zap,
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

function getEntityName(item: any): string {
  if (!item) return "";
  if (typeof item === "string") return item;
  if (typeof item === "object") {
    return String(item.name || item.caller_service || item.principal_name || item.service_name || "");
  }
  return String(item);
}

function isUserAnomaly(a: Anomaly): boolean {
  if (a.principal_name && a.principal_name.trim() !== "" && a.principal_name !== "unknown") {
    return true;
  }
  if (a.source_ip && a.source_ip.trim() !== "") {
    return true;
  }
  const type = (a.anomaly_type || "").toLowerCase();
  if (
    type.includes("user") ||
    type.includes("principal") ||
    type.includes("identity") ||
    type.includes("cred") ||
    type.includes("auth") ||
    type.includes("token")
  ) {
    return true;
  }
  if (a.blast_radius?.affected_principals && a.blast_radius.affected_principals.length > 0) {
    return true;
  }
  return false;
}

export function AnomaliesPage() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  const [perspective, setPerspective] = useState<"all" | "user" | "service">("all");
  const [search, setSearch] = useState("");

  const qs = queryString(filters, status ? { status } : {});

  const q = useQuery({
    queryKey: ["anomalies", qs],
    queryFn: () => api<{ items: Anomaly[] }>(`/api/v1/anomalies?${qs}`),
  });

  const rawItems = q.data?.items || [];

  // Summary KPIs computation
  const { userCount, uniqueUsers, topUser, criticalUserCount } = useMemo(() => {
    let uCount = 0;
    const userFrequency: Record<string, number> = {};
    let critCount = 0;

    rawItems.forEach((item) => {
      const isUser = isUserAnomaly(item);
      if (isUser) {
        uCount += 1;
        if (item.severity === "critical" || item.severity === "high") {
          critCount += 1;
        }
      }
      if (item.principal_name && item.principal_name !== "unknown") {
        userFrequency[item.principal_name] = (userFrequency[item.principal_name] || 0) + 1;
      }
      (item.blast_radius?.affected_principals || []).forEach((p) => {
        const pName = getEntityName(p);
        if (pName && pName !== "unknown") {
          userFrequency[pName] = (userFrequency[pName] || 0) + 1;
        }
      });
    });

    const userKeys = Object.keys(userFrequency);
    const sortedUsers = userKeys.sort((a, b) => userFrequency[b] - userFrequency[a]);

    return {
      userCount: uCount,
      uniqueUsers: userKeys.length,
      topUser: sortedUsers[0] || null,
      criticalUserCount: critCount,
    };
  }, [rawItems]);

  // Filtered findings according to perspective and search query
  const filteredItems = useMemo(() => {
    return rawItems.filter((item) => {
      if (perspective === "user" && !isUserAnomaly(item)) return false;
      if (perspective === "service" && isUserAnomaly(item)) return false;

      if (search.trim()) {
        const query = search.toLowerCase().trim();
        const matchesUser = (item.principal_name || "").toLowerCase().includes(query);
        const matchesIp = (item.source_ip || "").toLowerCase().includes(query);
        const matchesSvc = (item.entity_id || item.target_service || item.caller_service || "").toLowerCase().includes(query);
        const matchesType = (item.anomaly_type || "").toLowerCase().includes(query);
        const matchesOp = (item.operation || "").toLowerCase().includes(query);
        const matchesBlast = (item.blast_radius?.affected_principals || []).some((p) =>
          getEntityName(p).toLowerCase().includes(query)
        );

        if (!matchesUser && !matchesIp && !matchesSvc && !matchesType && !matchesOp && !matchesBlast) {
          return false;
        }
      }
      return true;
    });
  }, [rawItems, perspective, search]);

  return (
    <Page
      eyebrow="Identity & System Observability"
      title="Behavioral & Structural Anomalies"
      description="User-centric anomaly detection, Wilson score confidence intervals, and credential baseline deviation analytics."
      actions={
        <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] p-0.5">
          {[
            { label: "All", val: "", activeClass: "bg-gradient-to-r from-violet-600 to-indigo-600 text-white" },
            { label: "Open", val: "open", activeClass: "bg-rose-600 text-white shadow-[0_0_8px_rgba(244,63,94,0.6)]" },
            { label: "Acknowledged", val: "acknowledged", activeClass: "bg-amber-600 text-white shadow-[0_0_8px_rgba(245,158,11,0.6)]" },
            { label: "Resolved", val: "resolved", activeClass: "bg-emerald-600 text-white shadow-[0_0_8px_rgba(16,185,129,0.6)]" },
            { label: "Suppressed", val: "suppressed", activeClass: "bg-purple-600 text-white shadow-[0_0_8px_rgba(168,85,247,0.6)]" },
          ].map(({ label, val, activeClass }) => (
            <button
              key={label}
              onClick={() => setStatus(val)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                status === val
                  ? `${activeClass} shadow-sm font-semibold`
                  : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      }
    >
      {/* User-Centric Anomaly Summary KPIs */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-4">
        <MetricCard
          label="Total Findings"
          value={String(rawItems.length)}
          detail={`${rawItems.filter((a) => a.status === "open").length} open in window`}
          accent="purple"
        />
        <MetricCard
          label="Identity-Centric Findings"
          value={String(userCount)}
          detail={`${criticalUserCount} high/critical alerts`}
          tone={criticalUserCount > 0 ? "bad" : "normal"}
          accent="cyan"
        />
        <MetricCard
          label="Impacted Users"
          value={String(uniqueUsers)}
          detail="Identities flagged or in blast"
          accent="indigo"
        />
        <MetricCard
          label="Top Offending Identity"
          value={topUser || "None"}
          detail={topUser ? "High-volume anomaly source" : "No flagged identity"}
          accent="amber"
        />
      </div>

      {/* Perspective Switcher & Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4 rounded-xl border border-[rgba(255,255,255,0.08)] bg-[#161424] p-3">
        <div className="flex items-center gap-1.5 rounded-lg border border-[rgba(255,255,255,0.1)] bg-white/[0.02] p-1">
          <button
            onClick={() => setPerspective("all")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              perspective === "all"
                ? "bg-violet-600 text-white shadow-sm"
                : "text-[#c4bdd9] hover:text-white hover:bg-white/[0.04]"
            }`}
          >
            <span>All Findings</span>
            <span className="rounded-full bg-white/20 px-1.5 py-0.2 text-[10px]">{rawItems.length}</span>
          </button>

          <button
            onClick={() => setPerspective("user")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              perspective === "user"
                ? "bg-cyan-500 text-slate-950 font-bold shadow-[0_0_12px_rgba(6,182,212,0.5)]"
                : "text-cyan-300 hover:text-cyan-100 hover:bg-cyan-500/10"
            }`}
          >
            <UserRoundSearch size={13} />
            <span>User & Identity Centric</span>
            <span className={`rounded-full px-1.5 py-0.2 text-[10px] ${perspective === "user" ? "bg-slate-950/30 text-slate-900" : "bg-cyan-500/20 text-cyan-200"}`}>
              {userCount}
            </span>
          </button>

          <button
            onClick={() => setPerspective("service")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              perspective === "service"
                ? "bg-indigo-600 text-white shadow-sm"
                : "text-[#c4bdd9] hover:text-white hover:bg-white/[0.04]"
            }`}
          >
            <span>Service & Fleet</span>
            <span className="rounded-full bg-white/20 px-1.5 py-0.2 text-[10px]">{rawItems.length - userCount}</span>
          </button>
        </div>

        {/* Real-time search filter */}
        <div className="relative min-w-[260px] flex-1 max-w-md">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b949e]" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by user, IP, service, detector..."
            className="w-full rounded-lg border border-[rgba(255,255,255,0.12)] bg-black/40 py-1.5 pl-8 pr-3 text-xs text-white placeholder-[#8b949e] outline-none transition focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
          />
        </div>
      </div>

      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState message={q.error.message} />
      ) : (
        <Panel
          title={`${filteredItems.length} Detected Findings`}
          subtitle={
            perspective === "user"
              ? "Showing user, credential, and identity-attributed deviations."
              : perspective === "service"
                ? "Showing service-level metric anomalies and infrastructure shifts."
                : "Ordered by severity and detection recency. Select an incident row to inspect identity and baseline evidence."
          }
        >
          <div className="overflow-auto scrollbar">
            <table className="w-full min-w-[1200px]">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01]">
                  {[
                    "Severity",
                    "Attributed Identity / User",
                    "Entity & Service",
                    "Anomaly Detector",
                    "Window Timing",
                    "Current Value",
                    "Expected Baseline",
                    "Absolute Δ",
                    "Relative Shift",
                    "Samples",
                    "Status",
                    "Action",
                  ].map((h) => (
                    <th key={h} className="table-head px-4 py-2.5">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((a) => {
                  const detectorType = a.anomaly_type || "";
                  const isUser = isUserAnomaly(a);

                  const detectorBadgeColor = detectorType.includes("user") || detectorType.includes("cred") || detectorType.includes("auth")
                    ? "text-cyan-300 bg-cyan-500/15 border-cyan-500/30"
                    : detectorType.includes("spike")
                      ? "text-sky-300 bg-sky-500/15 border-sky-500/30"
                      : detectorType.includes("drop")
                        ? "text-indigo-300 bg-indigo-500/15 border-indigo-500/30"
                        : detectorType.includes("latency") || detectorType.includes("slow")
                          ? "text-violet-300 bg-violet-500/15 border-violet-500/30"
                          : detectorType.includes("cascading") || detectorType.includes("error")
                            ? "text-rose-300 bg-rose-500/15 border-rose-500/30"
                            : detectorType.includes("relationship") || detectorType.includes("edge")
                              ? "text-amber-300 bg-amber-500/15 border-amber-500/30"
                              : "text-[#c4bdd9] bg-white/[0.05] border-white/10";

                  const statusClasses: Record<string, string> = {
                    open: "border-rose-500/40 bg-rose-500/15 text-rose-300",
                    acknowledged: "border-amber-500/40 bg-amber-500/15 text-amber-300",
                    resolved: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
                    suppressed: "border-purple-500/40 bg-purple-500/15 text-purple-300",
                  };
                  const statusStyle = statusClasses[a.status || "open"] || "border-rose-500/40 bg-rose-500/15 text-rose-300";

                  return (
                    <tr
                      key={a.id}
                      onClick={() => nav(`/anomalies/${a.id}?${queryString(filters)}`)}
                      className="cursor-pointer border-b border-[rgba(255,255,255,0.08)] transition hover:bg-white/[0.05]"
                    >
                      {/* Severity */}
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                            a.severity === "critical"
                              ? "border border-rose-500/40 bg-rose-500/15 text-rose-300"
                              : a.severity === "high"
                                ? "border border-amber-500/40 bg-amber-500/15 text-amber-300"
                                : "border border-violet-500/40 bg-violet-500/15 text-violet-300"
                          }`}
                        >
                          {a.severity}
                        </span>
                      </td>

                      {/* User / Attributed Identity (User Centric Hero Column) */}
                      <td className="px-4 py-2 font-mono">
                        {a.principal_name && a.principal_name !== "unknown" ? (
                          <div className="flex flex-col gap-1 items-start">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                nav(`/users/${encodeURIComponent(a.principal_name!)}`);
                              }}
                              className="inline-flex items-center gap-1.5 rounded-md border border-cyan-500/40 bg-cyan-500/15 px-2 py-0.5 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-500/25 hover:border-cyan-400 hover:text-white"
                              title="Investigate User Profile"
                            >
                              <User size={11} className="text-cyan-400" />
                              <span>{a.principal_name}</span>
                              <ExternalLink size={10} className="text-cyan-400" />
                            </button>
                            {a.source_ip && (
                              <span className="inline-block text-[10px] font-mono text-cyan-300/80">
                                IP: {a.source_ip}
                              </span>
                            )}
                          </div>
                        ) : a.source_ip ? (
                          <div className="text-xs font-semibold text-cyan-300 font-mono">
                            IP: {a.source_ip}
                          </div>
                        ) : a.blast_radius?.affected_principals && a.blast_radius.affected_principals.length > 0 ? (
                          <div className="text-xs font-mono text-violet-300">
                            <span className="font-semibold">{getEntityName(a.blast_radius.affected_principals[0])}</span>
                            {a.blast_radius.affected_principals.length > 1 && (
                              <span className="ml-1 text-[10px] text-[#8b949e]">
                                +{a.blast_radius.affected_principals.length - 1} more
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-[11px] text-[#766e92] italic">
                            System / Service
                          </span>
                        )}
                      </td>

                      {/* Entity & Service */}
                      <td className="px-4 font-mono">
                        <div className="text-xs font-semibold text-[#f5f3fa]">
                          {a.target_service || a.caller_service || a.entity_id || "Service"}
                        </div>
                        {a.operation && (
                          <div className="text-[10px] text-violet-300/80 truncate max-w-[180px]">
                            {a.operation}
                          </div>
                        )}
                      </td>

                      {/* Anomaly Detector */}
                      <td className="px-4">
                        <span className={`inline-block rounded border px-2 py-0.5 text-[9px] font-medium uppercase tracking-wide ${detectorBadgeColor}`}>
                          {(a.anomaly_type || "").replaceAll("_", " ")}
                        </span>
                      </td>

                      {/* Window Timing */}
                      <td className="px-4 font-mono text-[10px] text-[#c4bdd9]">
                        {new Date(a.last_detected_ms || a.detected_at || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        <span className="block text-[9px] text-[#9e96b8]">
                          {new Date(a.last_detected_ms || a.detected_at || Date.now()).toLocaleDateString()}
                        </span>
                      </td>

                      {/* Current Value */}
                      <td className="px-4 font-mono text-xs tabular-nums font-medium text-[#f5f3fa]">
                        {n(a.current_value || 0)} {a.unit || ""}
                      </td>

                      {/* Expected Baseline */}
                      <td className="px-4 font-mono text-xs tabular-nums text-[#c4bdd9]">
                        {a.baseline_value == null
                          ? "—"
                          : `${n(a.normal_low ?? a.baseline_value)}–${n(a.normal_high ?? a.baseline_value)} ${a.unit || ""}`}
                      </td>

                      {/* Absolute Delta */}
                      <td className="px-4 font-mono text-xs tabular-nums text-[#fb7185] font-semibold">
                        {(a.absolute_difference || 0) > 0 ? "+" : ""}
                        {n(a.absolute_difference ?? Math.abs((a.current_value || 0) - (a.baseline_value || 0)))}
                      </td>

                      {/* Relative Change */}
                      <td className="px-4 font-mono text-xs tabular-nums">
                        {a.percent_change == null && a.delta_percentage == null ? (
                          <span className="text-[#9e96b8]">n/a</span>
                        ) : (
                          (() => {
                            const pct = Number(a.percent_change ?? a.delta_percentage ?? 0);
                            return (
                              <span className={pct > 0 ? "text-[#fb7185] font-semibold" : "text-[#34d399] font-semibold"}>
                                {pct > 0 ? "+" : ""}
                                {pct.toFixed(0)}%
                              </span>
                            );
                          })()
                        )}
                      </td>

                      {/* Samples */}
                      <td className="px-4 font-mono text-xs tabular-nums text-[#c4bdd9]">
                        {n(a.current_samples ?? 0)} / {n(a.baseline_samples ?? 0)}
                      </td>

                      {/* Status */}
                      <td className="px-4">
                        <span className={`inline-block rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${statusStyle}`}>
                          {a.status || "open"}
                        </span>
                      </td>

                      {/* Action */}
                      <td className="px-4 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            nav(`/anomalies/${a.id}?${queryString(filters)}`);
                          }}
                          className="inline-flex items-center gap-1 rounded border border-[rgba(255,255,255,0.1)] bg-white/[0.03] px-2 py-1 text-[11px] font-medium text-[#c4bdd9] hover:bg-white/[0.08] hover:text-white"
                        >
                          <span>Inspect</span>
                          <ArrowRight size={11} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {!filteredItems.length && (
                  <tr>
                    <td
                      colSpan={12}
                      className="p-12 text-center text-xs text-[#c4bdd9]"
                    >
                      No anomalies detected matching this perspective and search filter.
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
    queryFn: () =>
      api<{
        items: Array<{
          principal_name: string;
          requests: number;
          traffic_share: number;
          changes: Array<{ id: number; change_type: string; severity: string }>;
        }>;
      }>(`/api/v1/anomalies/${id}/users`),
    retry: 1,
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
  const usersList = relatedUsers.data?.items || [];

  return (
    <Page
      eyebrow={`Finding #${a.id} · ${(a.severity || "info").toUpperCase()} · ${(a.status || "open").toUpperCase()}`}
      title={`${a.entity_id || "Target"}: ${(a.anomaly_type || "").replaceAll("_", " ")}`}
      description={a.explanation}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn" onClick={() => nav(-1)}>
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
      {/* User-Centric Attributed Identity Profile Card */}
      {Boolean(a.principal_name || a.source_ip || (a.blast_radius?.affected_principals && a.blast_radius.affected_principals.length > 0)) && (
        <div className="mb-4 rounded-xl border border-cyan-500/40 bg-gradient-to-r from-cyan-950/40 to-indigo-950/30 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-400/40 bg-cyan-500/20 text-cyan-300">
                <UserRoundSearch size={22} />
              </div>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-cyan-300">
                  User Intelligence & Identity Context
                </div>
                <div className="text-base font-bold text-white flex items-center gap-2 mt-0.5">
                  <span>{a.principal_name && a.principal_name !== "unknown" ? a.principal_name : "Identity Attributed Finding"}</span>
                  {a.source_ip && (
                    <span className="rounded border border-cyan-400/40 bg-cyan-400/10 px-2 py-0.5 font-mono text-xs text-cyan-200">
                      IP: {a.source_ip}
                    </span>
                  )}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {a.principal_name && a.principal_name !== "unknown" && (
                <button
                  onClick={() => nav(`/users/${encodeURIComponent(a.principal_name!)}`)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/50 bg-cyan-500/20 px-3 py-1.5 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-500/30 hover:border-cyan-300 hover:text-white"
                >
                  <User size={13} />
                  <span>Investigate User Profile</span>
                  <ExternalLink size={11} />
                </button>
              )}
              <button
                onClick={() => nav("/user-graph")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-violet-500/40 bg-violet-500/15 px-3 py-1.5 text-xs font-medium text-violet-200 transition hover:bg-violet-500/25 hover:text-white"
              >
                <span>View User Graph</span>
              </button>
              <button
                onClick={() => nav("/user-changes")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-xs font-medium text-amber-200 transition hover:bg-amber-500/25 hover:text-white"
              >
                <span>User Changes Feed</span>
              </button>
            </div>
          </div>

          {/* Affected Principals summary if present */}
          {Boolean(a.blast_radius?.affected_principals && a.blast_radius.affected_principals.length > 0) && (
            <div className="mt-4 pt-3 border-t border-cyan-500/20 flex items-center gap-2 flex-wrap">
              <span className="text-[11px] font-semibold text-[#c4bdd9]">
                Affected Principals in Blast Radius:
              </span>
              {(a.blast_radius?.affected_principals || []).map((p, idx) => {
                const pName = getEntityName(p);
                return (
                  <button
                    key={pName || idx}
                    onClick={() => nav(`/users/${encodeURIComponent(pName)}`)}
                    className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 font-mono text-[11px] text-cyan-300 transition hover:bg-cyan-500/20 hover:text-white"
                  >
                    {pName}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* What Changed Compared With Normal Explainability Card */}
      <div className="rounded-xl border border-violet-500/40 bg-violet-950/20 p-5 backdrop-blur-sm">
        <div className="flex items-center gap-2 mb-2">
          <ShieldAlert className="text-violet-400" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-violet-200">
            What Changed Compared With Normal?
          </h3>
        </div>
        <p className="text-xs text-[#f5f3fa] leading-relaxed">
          {a.explanation}
        </p>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2 pt-3 border-t border-[rgba(255,255,255,0.12)]">
          <div className="rounded-lg border border-[rgba(255,255,255,0.12)] bg-white/[0.04] p-3.5 text-xs">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-300 flex items-center gap-1.5">
              <AlertTriangle size={12} /> Probable Incident Origin
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="font-mono text-sm font-bold text-white">
                {a.root_cause?.origin_service || a.entity_id}
              </span>
              {a.root_cause?.confidence_score != null && (
                <span className="text-[10px] font-mono text-[#c4bdd9]">
                  (confidence: {(Number(a.root_cause.confidence_score) * 100).toFixed(0)}%)
                </span>
              )}
            </div>
            <p className="mt-1 text-[11px] text-[#c4bdd9]">
              {a.root_cause?.reason || "Observed baseline deviation originated on this service component."}
            </p>
          </div>

          <div className="rounded-lg border border-[rgba(255,255,255,0.12)] bg-white/[0.04] p-3.5 text-xs">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-rose-300 flex items-center gap-1.5">
              <AlertOctagon size={12} /> Incident Blast Radius
            </span>
            <div className="mt-2 space-y-1.5 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-[#c4bdd9]">Upstream Callers:</span>
                <span className="font-mono text-[#f5f3fa]">
                  {a.blast_radius?.direct_callers?.length
                    ? a.blast_radius.direct_callers.map(getEntityName).filter(Boolean).join(", ")
                    : "None detected"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#c4bdd9]">Affected Principals:</span>
                <span className="font-mono text-cyan-300">
                  {a.blast_radius?.affected_principals?.length
                    ? a.blast_radius.affected_principals.map(getEntityName).filter(Boolean).join(", ")
                    : "None identified"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#c4bdd9]">Impacted Operations:</span>
                <span className="font-mono text-[#f5f3fa]">
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
              <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
              <XAxis
                dataKey="timestamp_ms"
                tickFormatter={(v) =>
                  new Date(v).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                }
                stroke="#766e92"
              />
              <YAxis stroke="#766e92" />
              <Tooltip {...chartTooltip} />
              <ReferenceArea
                x1={a.window_start_ms}
                x2={a.window_end_ms}
                fill="#fb7185"
                fillOpacity={0.2}
              />
              <Area
                dataKey={metric}
                stroke="#a78bfa"
                fill="#8b5cf6"
                fillOpacity={0.2}
                name="Actual Observed"
              />
              <Line
                dataKey="expected"
                stroke="#34d399"
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
              {a.source_ip && <Fact k="Source IP" v={a.source_ip} />}
              {a.principal_name && <Fact k="Principal" v={a.principal_name} />}
            </div>
          </div>
        </Panel>

        <Panel
          title="Evidence & Diagnostic Limitations"
          subtitle="Verified diagnostic evidence and baseline limitations"
        >
          <div className="p-5 space-y-4">
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

      {/* Related Users in Window Panel */}
      <Panel
        title="Related Users & Identity Activity"
        subtitle="Principals contributing traffic and behavioral change flags during this anomaly window"
        className="mt-4"
      >
        {usersList.length > 0 ? (
          <div className="divide-y divide-white/[.06]">
            {usersList.map((user) => (
              <button
                key={user.principal_name}
                onClick={() => nav(`/users/${encodeURIComponent(user.principal_name)}`)}
                className="flex w-full items-center justify-between gap-4 p-4 text-left transition hover:bg-white/[.04]"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-500/30 bg-cyan-500/10 text-cyan-300">
                    <User size={15} />
                  </div>
                  <div>
                    <div className="font-mono text-xs font-semibold text-cyan-300 flex items-center gap-2">
                      <span>{user.principal_name}</span>
                      <ExternalLink size={10} className="text-[#8b949e]" />
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {user.changes.length ? (
                        user.changes.map((c) => (
                          <span
                            key={c.id}
                            className={`rounded px-1.5 py-0.2 text-[9px] font-medium uppercase tracking-wide ${
                              c.severity === "critical"
                                ? "border border-rose-500/40 bg-rose-500/20 text-rose-300"
                                : c.severity === "high"
                                  ? "border border-amber-500/40 bg-amber-500/20 text-amber-300"
                                  : "border border-cyan-500/40 bg-cyan-500/20 text-cyan-300"
                            }`}
                          >
                            {c.change_type.replaceAll("_", " ")}
                          </span>
                        ))
                      ) : (
                        <span className="text-[10px] text-[#8b949e]">
                          Normal behavior pattern during window
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <div className="font-mono text-sm font-semibold text-white">
                    {(user.traffic_share * 100).toFixed(1)}%
                  </div>
                  <div className="text-[10px] text-[#8b949e]">
                    {n(user.requests)} requests
                  </div>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-[#8b949e]">
            No user-specific traffic records were attributed to this anomaly window.
          </div>
        )}
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
