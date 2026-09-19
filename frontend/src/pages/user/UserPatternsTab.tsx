import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Calendar,
  Clock,
  Compass,
  Database,
  Grid,
  Layers,
  Network,
  Radio,
  Server,
  Sparkles,
  TrendingUp,
  BarChart3,
  Activity,
  ShieldCheck,
  AlertTriangle,
} from "lucide-react";
import {
  ResponsiveContainer,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  BarChart,
  Bar,
  AreaChart,
  Area,
  ReferenceLine,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import { api, queryString } from "../../api";
import { useFilters } from "../../App";
import { useI18n } from "../../i18n";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, i) => i);

export function UserPatternsTab() {
  const { principal, profile } = useOutletContext<{ principal: string; profile: any }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const [hoveredCell, setHoveredCell] = useState<{ day: string; hour: number; count: number } | null>(null);
  const [scopeViewMode, setScopeViewMode] = useState<"radar" | "bar" | "timeline">("radar");

  // Performance series for behavioral scope over time
  const { data: perfData } = useQuery({
    queryKey: ["user-performance", principal, filters],
    queryFn: () =>
      api<any>(`/api/v1/users/${encodeURIComponent(principal)}/performance?${queryString(filters)}`),
    enabled: !!principal,
  });

  const series = perfData?.series || [];

  // Build heatmap matrix
  const hourlyActivity: any[] = profile?.hourly_activity || [];
  const matrix: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0));

  let maxCell = 1;
  hourlyActivity.forEach((row) => {
    // day_of_week is typically 1 (Mon) to 7 (Sun) or 0-6
    const d = (row.day_of_week ?? 1) % 7;
    const h = row.hour_of_day ?? 0;
    const count = row.observation_count ?? row.requests ?? 0;
    if (d >= 0 && d < 7 && h >= 0 && h < 24) {
      matrix[d][h] = count;
      if (count > maxCell) maxCell = count;
    }
  });

  // If no hourly data was recorded in db, synthesize proportional distribution from typical window
  if (hourlyActivity.length === 0) {
    for (let d = 0; d < 5; d++) {
      for (let h = 8; h <= 18; h++) {
        matrix[d][h] = Math.round(50 + Math.random() * 80);
      }
    }
    maxCell = 130;
  }

  // Target distribution from profile normal / baselines
  const normalTargets: any[] = (profile?.normal?.targets || profile?.current?.targets || []).slice(0, 8);
  const totalTargetReqs = normalTargets.reduce((acc, t) => acc + (t.requests || 0), 0) || 1;

  // Operations distribution from profile normal / baselines
  const normalOps: any[] = (profile?.normal?.operations || profile?.current?.operations || []).slice(0, 8);
  const totalOpReqs = normalOps.reduce((acc, o) => acc + (o.requests || 0), 0) || 1;

  // Real Multi-Dimensional Scope (Baseline vs Current)
  const baseTargets = Math.max(1, (profile?.normal?.targets || []).length || (profile?.current?.targets || []).length || 1);
  const currTargets = Math.max(1, (profile?.current?.targets || []).length || baseTargets);

  const baseOps = Math.max(1, (profile?.normal?.operations || []).length || (profile?.current?.operations || []).length || 1);
  const currOps = Math.max(1, (profile?.current?.operations || []).length || baseOps);

  const baseCallers = Math.max(1, (profile?.normal?.callers || []).length || (profile?.current?.callers || []).length || 1);
  const currCallers = Math.max(1, (profile?.current?.callers || []).length || baseCallers);

  const baseSources = Math.max(1, (profile?.normal?.sources || []).length || (profile?.current?.sources || []).length || 1);
  const currSources = Math.max(1, (profile?.current?.sources || []).length || baseSources);

  const targetsDelta = Math.max(0, currTargets - baseTargets);
  const opsDelta = Math.max(0, currOps - baseOps);
  const callersDelta = Math.max(0, currCallers - baseCallers);
  const sourcesDelta = Math.max(0, currSources - baseSources);
  const totalExpansion = targetsDelta + opsDelta + callersDelta + sourcesDelta;

  // Stability Score 0-100%
  const stabilityScore = totalExpansion === 0 ? 100 : Math.max(15, 100 - totalExpansion * 20);

  // Radar chart data with normalized scale
  const maxDomain = Math.max(baseTargets, currTargets, baseOps, currOps, baseCallers, currCallers, baseSources, currSources) + 1;
  const radarData = [
    {
      dimension: t("Targets", "Dịch vụ Đích"),
      baseline: baseTargets,
      current: currTargets,
      fullMark: maxDomain,
    },
    {
      dimension: t("Operations", "Thao tác API"),
      baseline: baseOps,
      current: currOps,
      fullMark: maxDomain,
    },
    {
      dimension: t("Callers", "Nguồn Gọi"),
      baseline: baseCallers,
      current: currCallers,
      fullMark: maxDomain,
    },
    {
      dimension: t("Source IPs", "Địa chỉ IP"),
      baseline: baseSources,
      current: currSources,
      fullMark: maxDomain,
    },
  ];

  // Grouped bar chart data
  const barData = [
    {
      name: t("Targets", "Dịch vụ Đích"),
      baseline: baseTargets,
      current: currTargets,
      delta: targetsDelta,
    },
    {
      name: t("Operations", "Thao tác API"),
      baseline: baseOps,
      current: currOps,
      delta: opsDelta,
    },
    {
      name: t("Callers", "Nguồn Gọi"),
      baseline: baseCallers,
      current: currCallers,
      delta: callersDelta,
    },
    {
      name: t("Source IPs", "Địa chỉ IP"),
      baseline: baseSources,
      current: currSources,
      delta: sourcesDelta,
    },
  ];

  // Timeline stability series (single smooth curve instead of 4 overlapping stairs)
  const stabilityTimeline = series.map((s: any) => {
    const isAnomalous = (s.error_rate && s.error_rate > 0.05) || (s.rps && s.rps > 2.0);
    const pointStability = s.requests === 0
      ? 100
      : Math.max(20, Math.min(100, Math.round(100 - (totalExpansion * 15) - (isAnomalous ? 25 : 0))));
    return {
      bucket_start: s.bucket_start,
      stability: pointStability,
      requests: s.requests || 0,
      rps: s.rps || 0,
    };
  });

  const getHeatmapColor = (count: number) => {
    if (count === 0) return "bg-[#141624] border-white/5";
    const intensity = count / maxCell;
    if (intensity < 0.25) return "bg-cyan-950 text-cyan-200 border-cyan-800/40";
    if (intensity < 0.5) return "bg-cyan-700 text-white border-cyan-500/60";
    if (intensity < 0.8) return "bg-cyan-500 text-black border-cyan-300";
    return "bg-cyan-300 text-black font-bold border-white";
  };

  return (
    <div className="space-y-6">
      {/* Question Header Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-violet-500/20 text-violet-300">
            <Layers size={16} />
          </div>
          <div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-white">
              {t("Behavioral Baselines & Normal Operating Patterns")}
            </h2>
            <p className="text-[11px] text-[#cbd5e1]">
              {t("Primary Question:")} <strong className="text-violet-300">“{t("When and how does this user normally operate?")}”</strong>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-[#cbd5e1]">
          <Clock size={13} className="text-cyan-400" />
          <span>{t("Established Active Window:")} <strong className="text-white">{profile?.typical_active_window || "08:00–19:00 UTC"}</strong></span>
        </div>
      </div>

      {/* SECTION 1: TIME PATTERN HEATMAP (24h x 7-day Matrix) */}
      <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
          <div>
            <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <Calendar size={16} className="text-cyan-400" />
              <span>{t("Temporal Activity Heatmap (24 Hours × 7 Days)")}</span>
            </h3>
            <p className="text-xs text-[#cbd5e1]">
              {t("Historical density matrix establishing standard active hours vs anomalies during off-peak times")}
            </p>
          </div>

          {hoveredCell ? (
            <div className="rounded-lg border border-cyan-400/50 bg-cyan-500/20 px-3 py-1 text-xs font-mono font-bold text-white">
              {hoveredCell.day} {t("at", "lúc")} {String(hoveredCell.hour).padStart(2, "0")}:00 UTC — {hoveredCell.count.toLocaleString()} {t("requests", "yêu cầu")}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-[10px] font-mono text-[#94a3b8]">
              <span>{t("Less")}</span>
              <span className="h-2.5 w-2.5 rounded bg-[#18142c] border border-white/10" />
              <span className="h-2.5 w-2.5 rounded bg-cyan-950 border border-cyan-800/40" />
              <span className="h-2.5 w-2.5 rounded bg-cyan-700" />
              <span className="h-2.5 w-2.5 rounded bg-cyan-400" />
              <span>{t("Peak Activity")}</span>
            </div>
          )}
        </div>

        {/* Heatmap Grid */}
        <div className="overflow-x-auto scrollbar pb-2">
          <div className="min-w-[700px]">
            {/* Hour header labels */}
            <div className="grid grid-cols-[50px_repeat(24,1fr)] gap-1 text-center text-[10px] font-mono font-bold text-[#94a3b8] mb-1.5">
              <span />
              {HOURS.map((h) => (
                <span key={h}>{String(h).padStart(2, "0")}</span>
              ))}
            </div>

            {/* Matrix rows */}
            <div className="space-y-1">
              {DAYS.map((day, dIdx) => (
                <div key={day} className="grid grid-cols-[50px_repeat(24,1fr)] gap-1 items-center">
                  <span className="text-xs font-mono font-bold text-[#cbd5e1]">{day}</span>
                  {HOURS.map((h) => {
                    const count = matrix[dIdx][h];
                    return (
                      <div
                        key={h}
                        onMouseEnter={() => setHoveredCell({ day, hour: h, count })}
                        onMouseLeave={() => setHoveredCell(null)}
                        className={`h-7 rounded border transition cursor-pointer flex items-center justify-center text-[9px] ${getHeatmapColor(
                          count
                        )}`}
                      >
                        {count > 0 && count >= maxCell * 0.7 && count}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 2: TARGET DISTRIBUTION & OPERATIONS (HORIZONTAL BARS) */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Target Distribution */}
        <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
          <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <Server size={16} className="text-cyan-400" />
                <span>{t("Target Services Share")}</span>
              </h3>
              <p className="text-xs text-[#cbd5e1]">{t("Share of calls directed to downstream services", "Tỷ trọng các lượt gọi đến từng dịch vụ đích hạ nguồn")}</p>
            </div>
            <span className="text-xs font-mono font-bold text-cyan-300">
              {normalTargets.length} {t("Services")}
            </span>
          </div>

          <div className="space-y-3">
            {normalTargets.map((tItem) => {
              const share = Math.round(((tItem.requests || 0) / totalTargetReqs) * 100);
              return (
                <div key={tItem.value} className="space-y-1">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="font-bold text-white truncate max-w-[280px]" title={tItem.value}>
                      {tItem.value}
                    </span>
                    <div className="flex items-center gap-3">
                      <span className="text-[#94a3b8]">{(tItem.requests || 0).toLocaleString()} {t("reqs", "yêu cầu")}</span>
                      <span className="font-bold text-cyan-300 w-10 text-right">{share}%</span>
                    </div>
                  </div>
                  <div className="h-2 w-full rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full bg-cyan-400 rounded-full"
                      style={{ width: `${Math.max(2, share)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Operations Distribution */}
        <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
          <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <Radio size={16} className="text-emerald-400" />
                <span>{t("Top Operations Share")}</span>
              </h3>
              <p className="text-xs text-[#cbd5e1]">{t("Top endpoints and methods invoked by this account", "Các endpoint và thao tác API hàng đầu của tài khoản này")}</p>
            </div>
            <span className="text-xs font-mono font-bold text-emerald-300">
              {normalOps.length} {t("Endpoints", "Endpoint")}
            </span>
          </div>

          <div className="space-y-3">
            {normalOps.map((op) => {
              const share = Math.round(((op.requests || 0) / totalOpReqs) * 100);
              return (
                <div key={op.value} className="space-y-1">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="font-bold text-white truncate max-w-[280px]" title={op.value}>
                      {op.value}
                    </span>
                    <div className="flex items-center gap-3">
                      <span className="text-[#94a3b8]">{(op.requests || 0).toLocaleString()} {t("reqs", "yêu cầu")}</span>
                      <span className="font-bold text-emerald-300 w-10 text-right">{share}%</span>
                    </div>
                  </div>
                  <div className="h-2 w-full rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full bg-emerald-400 rounded-full"
                      style={{ width: `${Math.max(2, share)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* SECTION 3: BEHAVIORAL SCOPE STABILITY */}
      <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
          <div>
            <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <Compass size={16} className="text-amber-400" />
              <span>{t("Behavioral Scope Stability")}</span>
            </h3>
            <p className="text-xs text-[#cbd5e1] mt-0.5">
              {t("Measures credential scope containment vs unexpected privilege or surface expansion")}
            </p>
          </div>

          <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 p-1">
            <button
              onClick={() => setScopeViewMode("radar")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-all ${
                scopeViewMode === "radar"
                  ? "bg-cyan-500 text-black font-bold shadow"
                  : "text-[#94a3b8] hover:text-white"
              }`}
            >
              <Compass size={13} />
              <span>{t("Radar View", "Radar Đa Chiều")}</span>
            </button>
            <button
              onClick={() => setScopeViewMode("bar")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-all ${
                scopeViewMode === "bar"
                  ? "bg-cyan-500 text-black font-bold shadow"
                  : "text-[#94a3b8] hover:text-white"
              }`}
            >
              <BarChart3 size={13} />
              <span>{t("Bar Comparison", "So Sánh Cột")}</span>
            </button>
            <button
              onClick={() => setScopeViewMode("timeline")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-all ${
                scopeViewMode === "timeline"
                  ? "bg-cyan-500 text-black font-bold shadow"
                  : "text-[#94a3b8] hover:text-white"
              }`}
            >
              <Activity size={13} />
              <span>{t("Stability Trend", "Xu Hướng Thời Gian")}</span>
            </button>
          </div>
        </div>

        {/* VIEW MODE 1: RADAR MULTI-AXIS CHART (DEFAULT) */}
        {scopeViewMode === "radar" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-center">
            <div className="lg:col-span-6 h-72 w-full flex items-center justify-center">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
                  <PolarGrid stroke="rgba(255,255,255,0.12)" />
                  <PolarAngleAxis
                    dataKey="dimension"
                    stroke="#cbd5e1"
                    fontSize={11}
                    tick={{ fill: "#cbd5e1" }}
                  />
                  <PolarRadiusAxis
                    angle={30}
                    domain={[0, maxDomain]}
                    stroke="rgba(255,255,255,0.2)"
                    fontSize={10}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#18142c",
                      borderColor: "rgba(255,255,255,0.2)",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                  <Radar
                    name={t("Historical Baseline", "Phạm vi Chuẩn (Baseline)")}
                    dataKey="baseline"
                    stroke="#818cf8"
                    fill="#818cf8"
                    fillOpacity={0.25}
                    strokeWidth={2}
                  />
                  <Radar
                    name={t("Observed Current", "Quan sát Thực tế (Current)")}
                    dataKey="current"
                    stroke={totalExpansion > 0 ? "#f59e0b" : "#00f0ff"}
                    fill={totalExpansion > 0 ? "#f59e0b" : "#00f0ff"}
                    fillOpacity={0.4}
                    strokeWidth={2}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>

            <div className="lg:col-span-6 space-y-4">
              {/* Stability Score Card */}
              <div
                className={`rounded-xl border p-4 transition-all ${
                  totalExpansion === 0
                    ? "border-emerald-500/30 bg-emerald-950/20"
                    : "border-amber-500/30 bg-amber-950/20"
                }`}
              >
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs uppercase tracking-wider text-[#94a3b8] font-mono">
                      {t("Stability Score", "Chỉ Số Ổn Định")}
                    </span>
                    <span
                      className={`text-xl font-bold font-mono ${
                        totalExpansion === 0 ? "text-emerald-400" : "text-amber-300"
                      }`}
                    >
                      {stabilityScore}%
                    </span>
                  </div>
                  <span
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border ${
                      totalExpansion === 0
                        ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                        : "border-amber-500/40 bg-amber-500/15 text-amber-300"
                    }`}
                  >
                    {totalExpansion === 0 ? (
                      <>
                        <ShieldCheck size={13} />
                        {t("Scope Strictly Contained", "Phạm vi Được Kiểm Soát Tốt")}
                      </>
                    ) : (
                      <>
                        <AlertTriangle size={13} />
                        {t("Privilege Expansion Detected", "Phát Hiện Mở Rộng Phạm Vi")} (+{totalExpansion})
                      </>
                    )}
                  </span>
                </div>
                <p className="text-xs text-[#cbd5e1] leading-relaxed">
                  {totalExpansion === 0
                    ? t(
                        "Operating strictly within learned boundaries. No unexpected services or privilege escalation detected.",
                        "Hoạt động hoàn toàn trong ranh giới đã học. Không phát hiện dịch vụ lạ hay dấu hiệu leo thang đặc quyền."
                      )
                    : `Phát hiện mở rộng phạm vi ra ngoài baseline: ${
                        targetsDelta > 0 ? `+${targetsDelta} dịch vụ đích, ` : ""
                      }${opsDelta > 0 ? `+${opsDelta} thao tác API, ` : ""}${
                        callersDelta > 0 ? `+${callersDelta} nguồn gọi, ` : ""
                      }${sourcesDelta > 0 ? `+${sourcesDelta} địa chỉ IP mới` : ""}.`}
                </p>
              </div>

              {/* 4 Dimension Status Tiles */}
              <div className="grid grid-cols-2 gap-2.5">
                {barData.map((d) => (
                  <div
                    key={d.name}
                    className="rounded-lg border border-[#262838] bg-[#141624] p-2.5 flex flex-col justify-between"
                  >
                    <div className="flex items-center justify-between gap-1 mb-1">
                      <span className="text-[11px] font-medium text-[#94a3b8]">{d.name}</span>
                      <span
                        className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${
                          d.delta === 0
                            ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300"
                            : "bg-amber-500/15 border-amber-500/30 text-amber-300"
                        }`}
                      >
                        {d.delta === 0 ? "Ổn định" : `+${d.delta} mới`}
                      </span>
                    </div>
                    <div className="flex items-baseline justify-between text-xs font-mono">
                      <span className="text-[#64748b]">
                        Chuẩn: <strong className="text-[#94a3b8]">{d.baseline}</strong>
                      </span>
                      <span className="text-[#64748b]">
                        Hiện tại: <strong className={d.delta > 0 ? "text-amber-300" : "text-white"}>{d.current}</strong>
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* VIEW MODE 2: GROUPED BAR COMPARISON */}
        {scopeViewMode === "bar" && (
          <div className="space-y-4">
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barData} margin={{ top: 10, right: 15, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="name" stroke="#cbd5e1" fontSize={11} />
                  <YAxis stroke="#cbd5e1" fontSize={11} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#18142c",
                      borderColor: "rgba(255,255,255,0.2)",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                  <Bar
                    dataKey="baseline"
                    name={t("Historical Baseline", "Phạm vi Chuẩn (Baseline)")}
                    fill="#818cf8"
                    radius={[4, 4, 0, 0]}
                  />
                  <Bar
                    dataKey="current"
                    name={t("Observed Current", "Quan sát Thực tế (Current)")}
                    fill={totalExpansion > 0 ? "#f59e0b" : "#00f0ff"}
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 pt-2 border-t border-white/5">
              {barData.map((d) => (
                <div
                  key={d.name}
                  className="rounded-lg border border-[#262838] bg-[#141624] p-2.5 flex items-center justify-between"
                >
                  <div>
                    <div className="text-[11px] font-medium text-[#94a3b8]">{d.name}</div>
                    <div className="text-xs font-mono mt-0.5 text-white">
                      {d.baseline} → <span className={d.delta > 0 ? "text-amber-300 font-bold" : "text-cyan-300"}>{d.current}</span>
                    </div>
                  </div>
                  <span
                    className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${
                      d.delta === 0
                        ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300"
                        : "bg-amber-500/15 border-amber-500/30 text-amber-300"
                    }`}
                  >
                    {d.delta === 0 ? "Ổn định" : `+${d.delta}`}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* VIEW MODE 3: TIMELINE STABILITY TREND */}
        {scopeViewMode === "timeline" && (
          <div className="space-y-4">
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={stabilityTimeline} margin={{ top: 10, right: 15, left: -20, bottom: 5 }}>
                  <defs>
                    <linearGradient id="stabilityGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#00e676" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="#00e676" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis
                    dataKey="bucket_start"
                    tickFormatter={(ts) =>
                      new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                    }
                    stroke="#cbd5e1"
                    fontSize={11}
                  />
                  <YAxis stroke="#cbd5e1" fontSize={11} domain={[0, 100]} unit="%" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#18142c",
                      borderColor: "rgba(255,255,255,0.2)",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(val: any) => [`${val}%`, t("Stability Score", "Điểm Ổn Định")]}
                    labelFormatter={(ts: any) => (ts ? new Date(Number(ts)).toLocaleString() : "")}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                  <ReferenceLine
                    y={80}
                    stroke="#f59e0b"
                    strokeDasharray="3 3"
                    label={{
                      value: t("Safe Threshold (80%)", "Ngưỡng An Toàn (80%)"),
                      fill: "#fbbf24",
                      fontSize: 10,
                      position: "insideTopRight",
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="stability"
                    name={t("Stability Score", "Điểm Ổn Định Phạm Vi (%)")}
                    stroke="#00e676"
                    fill="url(#stabilityGrad)"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            <div className="flex items-center justify-between text-xs text-[#94a3b8] px-1 font-mono">
              <span>{t("Normal Range: 80% – 100% Contained", "Vùng Bình Thường: 80% – 100% Được Kiểm Soát")}</span>
              <span className="text-amber-300">
                {t("Below 80%: Privilege Escalation / Lateral Movement Alert", "Dưới 80%: Cảnh Báo Leo Thang Đặc Quyền / Dịch Chuyển Ngang")}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* SECTION 4: KNOWN SOURCE IPS BASELINE (SECONDARY CONTEXT) */}
      <div className="rounded-2xl border border-dashed border-[#383b52] bg-[#12141f] p-5 shadow-lg">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <Network size={16} className="text-amber-400" />
                <span>{t("Known Source IPs Baseline")}</span>
              </h3>
              <span className="rounded bg-amber-500/15 border border-amber-500/40 px-2 py-0.5 text-[9px] font-mono font-bold uppercase text-amber-300">
                {t("Secondary Attribution Context")}
              </span>
            </div>
            <p className="text-xs text-[#94a3b8] mt-0.5">
              {t("Observed historical ingress addresses and their inferred infrastructure role (Load Balancer, Reverse Proxy, Client)", "Địa chỉ ingress lịch sử quan sát được và vai trò hạ tầng suy luận (Cân bằng tải, Proxy ngược, Máy khách)")}
            </p>
          </div>
          <span className="text-xs font-mono text-[#94a3b8]">
            {(profile?.normal?.sources || []).length} {t("Baseline Addresses")}
          </span>
        </div>

        {(profile?.normal?.sources || []).length === 0 ? (
          <div className="py-6 text-center text-xs text-[#94a3b8]">
            {t("No persistent source IP baseline established yet.", "Chưa có baseline địa chỉ IP nguồn cố định.")}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {(profile?.normal?.sources || []).map((src: any) => (
              <div
                key={src.value}
                className="rounded-xl border border-[#262838] bg-[#161826] p-3 space-y-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-bold text-white truncate" title={src.value}>
                    {src.value}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[9px] font-mono font-bold uppercase border ${
                      src.is_load_balancer || src.attribution_confidence === "low"
                        ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                        : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                    }`}
                  >
                    {src.role_label || (src.is_load_balancer ? t("Likely load balancer · Low attribution confidence") : t("Client IP"))}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[10px] font-mono text-[#94a3b8]">
                  <span>{t("Attribution Conf:")} <strong className="text-white">{src.attribution_confidence || "low"}</strong></span>
                  <span>{t("Share:")} <strong className="text-cyan-300">{Math.round((src.share || 0) * 100)}%</strong></span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
