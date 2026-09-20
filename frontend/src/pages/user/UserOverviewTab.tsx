import { useOutletContext, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  Clock,
  ExternalLink,
  GitCompareArrows,
  HelpCircle,
  Network,
  Radio,
  ShieldAlert,
  Sparkles,
  Zap,
} from "lucide-react";
import {
  ResponsiveContainer,
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

export function UserOverviewTab() {
  const { principal, profile } = useOutletContext<{ principal: string; profile: any }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();

  const rangeHours = Math.round(
    (new Date(filters.end).getTime() - new Date(filters.start).getTime()) / 3600_000,
  );
  const isMultiDay = rangeHours > 24;

  const formatTick = (ts: any) => {
    try {
      const d = new Date(Number(ts));
      return isMultiDay
        ? `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
        : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return String(ts);
    }
  };

  const formatTooltip = (ts: any) => {
    if (!ts) return "";
    try {
      return new Date(Number(ts)).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return String(ts);
    }
  };

  const formatMiBRate = (value: any) => {
    const bytesPerSecond = Number(value || 0);
    if (!Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return "0.00 MiB/s";
    return `${(bytesPerSecond / (1024 * 1024)).toFixed(2)} MiB/s`;
  };

  // Fetch performance series and Current 5m vs Baseline KPIs
  const { data: perfData, isLoading: perfLoading } = useQuery({
    queryKey: ["user-performance", principal, filters],
    queryFn: () =>
      api<any>(`/api/v1/users/${encodeURIComponent(principal)}/performance?${queryString(filters)}`),
    enabled: !!principal,
  });

  const kpis = perfData?.kpis || {};
  const cur = kpis.current_5m || {};
  const deltas = kpis.deltas || {};
  const series = perfData?.series || [];
  const sourceIps: any[] = perfData?.available_sources || [];

  // Recent changes from profile
  const recentChanges: any[] = (profile?.changes || []).slice(0, 5);

  // Tiny new relationships summary
  const newCallers = (profile?.current?.callers || []).filter(
    (c: any) => !(profile?.normal?.callers || []).some((nc: any) => nc.value === c.value)
  );
  const newTargets = (profile?.current?.targets || []).filter(
    (t: any) => !(profile?.normal?.targets || []).some((nt: any) => nt.value === t.value)
  );
  const newOperations = (profile?.current?.operations || []).filter(
    (o: any) => !(profile?.normal?.operations || []).some((no: any) => no.value === o.value)
  );

  const formatDelta = (val: number | undefined, isPct = true) => {
    if (val === undefined || isNaN(val)) return "0%";
    const sign = val > 0 ? "↑ " : val < 0 ? "↓ " : "";
    return `${sign}${Math.abs(val)}${isPct ? "%" : ""}`;
  };

  const deltaColor = (val: number | undefined, invert = false) => {
    if (!val || val === 0) return "text-[#94a3b8] bg-white/5 border-white/10";
    const isBad = invert ? val < 0 : val > 0;
    return isBad
      ? "text-rose-300 bg-rose-500/15 border-rose-500/40"
      : "text-emerald-300 bg-emerald-500/15 border-emerald-500/40";
  };

  return (
    <div className="space-y-6">
      {/* Page Intent Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-cyan-500/20 text-cyan-300">
            <Radio size={16} />
          </div>
          <div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-white">
              {t("Executive Operational Signals · Current 5m Window")}
            </h2>
            <p className="text-[11px] text-[#cbd5e1]">
              {t("Primary Question:")} <strong className="text-cyan-300">“{t("Is this user behaving normally right now?")}”</strong>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono text-[#cbd5e1]">
          <span className="flex h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
          <span>{t("Evaluation vs Established Baseline")}</span>
        </div>
      </div>

      {/* Important changes stay above the charts so the page answers what changed first. */}
      <div className="grid gap-4">
        <div className="rounded-xl border border-rose-500/25 bg-[#171329] p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <GitCompareArrows size={15} className="text-rose-300" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">{t("Important Changes")}</h3>
            </div>
            <button onClick={() => nav(`/users/${encodeURIComponent(principal)}/changes`)} className="text-[11px] font-semibold text-cyan-300 hover:underline">
              {t("View all changes")}
            </button>
          </div>
          {recentChanges.length ? (
            <div className="space-y-2">
              {recentChanges.slice(0, 3).map((change, index) => (
                <div key={`${change.id || change.change_type}-${index}`} className="flex items-start justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${change.severity === "high" ? "bg-rose-500/20 text-rose-200" : change.severity === "medium" ? "bg-amber-500/20 text-amber-200" : "bg-cyan-500/20 text-cyan-200"}`}>
                        {change.change_type || t("Changed")}
                      </span>
                      <span className="truncate font-mono text-[11px] font-semibold text-white">{change.new_value || change.target_service || change.caller_service || t("Shift observed")}</span>
                    </div>
                    <p className="mt-1 truncate text-[11px] text-[#cbd5e1]">{change.reason?.what_changed || change.reason?.compared_with || t("Deviates from established historical behavior")}</p>
                  </div>
                  <span className="shrink-0 font-mono text-[10px] text-[#94a3b8]">{change.detected_at ? new Date(change.detected_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-4 text-center text-xs text-emerald-300">{t("No behavioral deviations detected. User operating strictly within baseline.")}</div>
          )}
        </div>

      </div>

      {/* Primary user signals: keep the throughput trend beside the main KPI block. */}
      <div className="grid gap-5 lg:grid-cols-2 lg:items-stretch">
        <div className="rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-4 shadow-md">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                {t("TPS vs Baseline")}
              </h3>
              <p className="text-[11px] text-[#cbd5e1]">{t("Throughput rate vs historical baseline")}</p>
            </div>
            <span className="rounded-md border border-cyan-500/40 bg-cyan-500/20 px-2 py-0.5 text-[10px] font-bold text-cyan-200">
              {t("Live")}
            </span>
          </div>

          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis dataKey="bucket_start" tickFormatter={formatTick} stroke="#cbd5e1" fontSize={11} />
                <YAxis stroke="#cbd5e1" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                  formatter={(val: any, name: any, item: any) => {
                    const key = item?.dataKey || "";
                    const isObserved = key === "rps" || name === "Observed TPS" || name === "Observed RPS" || String(name).toLowerCase().includes("observed");
                    return [`${Number(val || 0).toFixed(2)} tps`, isObserved ? t("Observed TPS") : t("Baseline TPS")];
                  }}
                  labelFormatter={formatTooltip}
                />
                <Legend iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Line type="monotone" dataKey="rps" name={t("Observed TPS")} stroke="#00f0ff" strokeWidth={2.5} dot={false} activeDot={{ r: 5, fill: "#00f0ff" }} />
                <Line type="monotone" dataKey="baseline_rps" name={t("Baseline TPS")} stroke="#b388ff" strokeWidth={1.8} strokeDasharray="4 4" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="grid h-full min-h-[348px] auto-rows-fr grid-cols-2 gap-3">
        {/* 1. Requests */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.16)] bg-[#171329] p-3.5 shadow-sm transition hover:border-cyan-400/50">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("Requests")}</div>
          <div className="mt-1 font-mono text-xl font-bold text-white">
            {(cur.requests ?? 0).toLocaleString()}
          </div>
          <div className="mt-2 flex items-center gap-1">
            <span
              className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold border ${deltaColor(
                deltas.requests_pct
              )}`}
            >
              {formatDelta(deltas.requests_pct)}
            </span>
            <span className="text-[10px] text-[#94a3b8]">{t("vs base")}</span>
          </div>
        </div>

        {/* 2. TPS */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.16)] bg-[#171329] p-3.5 shadow-sm transition hover:border-cyan-400/50">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("TPS")}</div>
          <div className="mt-1 font-mono text-xl font-bold text-cyan-300">
            {cur.rps ?? "0.0"}
          </div>
          <div className="mt-2 flex items-center gap-1">
            <span
              className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold border ${deltaColor(
                deltas.rps_pct
              )}`}
            >
              {formatDelta(deltas.rps_pct)}
            </span>
            <span className="text-[10px] text-[#94a3b8]">{t("vs base")}</span>
          </div>
        </div>

        {/* 3. Error Rate */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.16)] bg-[#171329] p-3.5 shadow-sm transition hover:border-cyan-400/50">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("Error Rate")}</div>
          <div
            className={`mt-1 font-mono text-xl font-bold ${
              (cur.error_rate || 0) > 0.02 ? "text-rose-400" : "text-white"
            }`}
          >
            {((cur.error_rate ?? 0) * 100).toFixed(1)}%
          </div>
          <div className="mt-2 flex items-center gap-1">
            <span
              className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold border ${deltaColor(
                deltas.error_rate_pct
              )}`}
            >
              {formatDelta(deltas.error_rate_pct)}
            </span>
            <span className="text-[10px] text-[#94a3b8]">{t("shift")}</span>
          </div>
        </div>

        {/* 4. P95 Latency */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.16)] bg-[#171329] p-3.5 shadow-sm transition hover:border-cyan-400/50">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("P95 Latency")}</div>
          <div className="mt-1 font-mono text-xl font-bold text-amber-300">
            {Math.round(cur.p95 ?? 0)} ms
          </div>
          <div className="mt-2 flex items-center gap-1">
            <span
              className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold border ${deltaColor(
                deltas.p95_pct
              )}`}
            >
              {formatDelta(deltas.p95_pct)}
            </span>
            <span className="text-[10px] text-[#94a3b8]">{t("shift")}</span>
          </div>
        </div>

        </div>
      </div>

      {/* Source IP evidence replaces relationship-count cards with concrete origins. */}
      <div className="rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-4 shadow-md">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-white">{t("Source IPs")}</h3>
            <p className="mt-0.5 text-[11px] text-[#cbd5e1]">{t("Observed network origins for this user")}</p>
          </div>
          <span className="rounded-md border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 font-mono text-[10px] font-bold text-amber-200">
            {sourceIps.length} {t("origins")}
          </span>
        </div>
        {sourceIps.length ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {sourceIps.slice(0, 12).map((source: any) => (
              <div key={`${source.ip || "unknown"}-${source.role || "source"}`} className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-xs font-semibold text-cyan-200">{source.ip || "—"}</span>
                  {source.is_load_balancer && <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/15 px-1 py-0.5 text-[9px] font-bold text-amber-200">LB</span>}
                </div>
                <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-[#94a3b8]">
                  <span>{Number(source.requests || 0).toLocaleString()} {t("requests")}</span>
                  <span className="truncate text-right">{source.role_label || source.role || t("Observed source")}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-white/10 px-3 py-4 text-center text-xs text-[#94a3b8]">{t("No source IP observations in this window.")}</div>
        )}
      </div>

      {/* Below the cards: 4 Distinct High-Contrast Line Charts in 2 lines (2 cards per line) */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Chart 1: Error Rate Line */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-4 shadow-md">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                {t("Error Rate Over Time")}
              </h3>
              <p className="text-[11px] text-[#cbd5e1]">{t("4xx client errors & 5xx server outages")}</p>
            </div>
            <span className="rounded-md bg-rose-500/20 px-2 py-0.5 text-[10px] font-bold text-rose-200 border border-rose-500/40">
              {t("Error Trend")}
            </span>
          </div>

          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis
                  dataKey="bucket_start"
                  tickFormatter={formatTick}
                  stroke="#cbd5e1"
                  fontSize={11}
                />
                <YAxis
                  stroke="#cbd5e1"
                  fontSize={11}
                  tickFormatter={(val) => `${(val * 100).toFixed(0)}%`}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                  formatter={(val: any) => [`${(Number(val) * 100).toFixed(2)}%`, t("Error Rate")]}
                  labelFormatter={formatTooltip}
                />
                <Legend iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Line
                  type="monotone"
                  dataKey="error_rate"
                  name={t("Error Rate")}
                  stroke="#ff1744"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 5, fill: "#ff1744" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 2: P95 Latency Line */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-4 shadow-md">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                {t("P95 Latency Over Time")}
              </h3>
              <p className="text-[11px] text-[#cbd5e1]">{t("95th percentile execution tail (ms)")}</p>
            </div>
            <span className="rounded-md bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-200 border border-amber-500/40">
              {t("Tail Latency")}
            </span>
          </div>

          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis
                  dataKey="bucket_start"
                  tickFormatter={formatTick}
                  stroke="#cbd5e1"
                  fontSize={11}
                />
                <YAxis stroke="#cbd5e1" fontSize={11} tickFormatter={(val) => `${val}ms`} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                  formatter={(val: any, name: any, item: any) => {
                    const key = item?.dataKey || "";
                    const isObserved = key === "latency_p95" || name === "Observed P95" || String(name).toLowerCase().includes("observed");
                    if (isObserved) {
                      return [`${Number(val || 0).toFixed(1)} ms`, t("Observed P95")];
                    }
                    return [`${Number(val || 0).toFixed(1)} ms`, t("Baseline P95")];
                  }}
                  labelFormatter={formatTooltip}
                />
                <Legend iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Line
                  type="monotone"
                  dataKey="latency_p95"
                  name={t("Observed P95")}
                  stroke="#ffab00"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 5, fill: "#ffab00" }}
                />
                <Line
                  type="monotone"
                  dataKey="baseline_p95"
                  name={t("Baseline P95")}
                  stroke="#94a3b8"
                  strokeWidth={1.8}
                  strokeDasharray="4 4"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 3: Bandwidth Line */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-4 shadow-md">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                {t("Bandwidth Over Time")}
              </h3>
              <p className="text-[11px] text-[#cbd5e1]">{t("Request and response throughput")}</p>
            </div>
            <span className="rounded-md border border-sky-500/40 bg-sky-500/20 px-2 py-0.5 text-[10px] font-bold text-sky-200">
              MiB/s
            </span>
          </div>

          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis dataKey="bucket_start" tickFormatter={formatTick} stroke="#cbd5e1" fontSize={11} />
                <YAxis stroke="#cbd5e1" fontSize={11} tickFormatter={formatMiBRate} width={68} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                  formatter={(val: any) => [formatMiBRate(val), t("Bandwidth")]}
                  labelFormatter={formatTooltip}
                />
                <Legend iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Line
                  type="monotone"
                  dataKey="bandwidth_bytes_per_second"
                  name={t("Bandwidth")}
                  stroke="#38bdf8"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 5, fill: "#38bdf8" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 4: Abnormality Score Spike Line */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-4 shadow-md">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                {t("Abnormality Score Spike", "Đột Biến Điểm Bất Thường")}
              </h3>
              <p className="text-[11px] text-[#cbd5e1]">{t("Scaled behavioral anomaly & TPS surge (0–100)", "Điểm bất thường & đột biến TPS co giãn (0–100)")}</p>
            </div>
            <span className="rounded-md bg-fuchsia-500/20 px-2 py-0.5 text-[10px] font-bold text-fuchsia-200 border border-fuchsia-500/40">
              {t("Scaled Risk Spike", "Đột biến rủi ro co giãn")}
            </span>
          </div>

          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis
                  dataKey="bucket_start"
                  tickFormatter={formatTick}
                  stroke="#cbd5e1"
                  fontSize={11}
                />
                <YAxis
                  stroke="#cbd5e1"
                  fontSize={11}
                  domain={[0, (dataMax: number) => Math.max(100, Math.ceil(dataMax || 0))]}
                  tickFormatter={(val) => `${val}`}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                  formatter={(val: any, name: any, item: any) => {
                    const key = item?.dataKey || "";
                    const num = Number(val || 0);
                    if (key === "anomaly_score" || name === "Anomaly Score" || String(name).toLowerCase().includes("anomaly") || String(name).toLowerCase().includes("bất thường")) {
                      let level = t("Normal", "Bình thường");
                      if (num >= 60) level = t("High Spike", "Đột biến cao");
                      else if (num >= 25) level = t("Medium Spike", "Đột biến trung bình");
                      else if (num > 0) level = t("Low Spike", "Đột biến thấp");
                      const rpsPts = item?.payload?.rps_score;
                      const rpsExtra = rpsPts > 0 ? ` (${t("TPS scale:", "Tỷ lệ TPS:")} +${rpsPts} pts)` : "";
                      return [`${num} pts${rpsExtra} · ${level}`, t("Anomaly Score", "Điểm bất thường")];
                    }
                    return [`${num} pts`, t("Baseline Normal", "Mức cơ sở")];
                  }}
                  labelFormatter={formatTooltip}
                />
                <Legend iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Line
                  type="monotone"
                  dataKey="anomaly_score"
                  name={t("Anomaly Score", "Điểm bất thường")}
                  stroke="#d946ef"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 5, fill: "#d946ef" }}
                />
                <Line
                  type="monotone"
                  dataKey="baseline_anomaly_score"
                  name={t("Baseline Normal (0)", "Đường cơ sở (0)")}
                  stroke="#64748b"
                  strokeWidth={1.8}
                  strokeDasharray="4 4"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Detailed change markup is retained for compatibility but the compact summary above is the primary view. */}
      <div className="hidden">
        {/* Left: Mini Change Timeline */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-4 shadow-md">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <GitCompareArrows size={16} className="text-cyan-400" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                {t("Recent Important Changes")}
              </h3>
            </div>
            <button
              onClick={() => nav(`/users/${encodeURIComponent(principal)}/changes`)}
              className="text-[11px] font-bold text-cyan-300 hover:text-cyan-200 hover:underline flex items-center gap-1"
            >
              <span>{t("View all changes")}</span>
              <ExternalLink size={12} />
            </button>
          </div>

          {recentChanges.length === 0 ? (
            <div className="py-8 text-center text-xs text-[#cbd5e1]">
              <Sparkles size={20} className="mx-auto mb-2 text-emerald-400" />
              <span>{t("No behavioral deviations detected. User operating strictly within baseline.")}</span>
            </div>
          ) : (
            <div className="divide-y divide-white/10 space-y-2">
              {recentChanges.map((change, idx) => (
                <div key={idx} className="pt-2 flex items-start justify-between gap-3">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase border ${
                          change.severity === "high"
                            ? "border-rose-500/50 bg-rose-500/20 text-rose-200"
                            : change.severity === "medium"
                            ? "border-amber-500/50 bg-amber-500/20 text-amber-200"
                            : "border-cyan-500/50 bg-cyan-500/20 text-cyan-200"
                        }`}
                      >
                        {change.change_type}
                      </span>
                      <span className="font-mono text-xs font-bold text-white">
                        {change.new_value || change.target_service || change.caller_service || t("Shift observed")}
                      </span>
                    </div>
                    <p className="text-[11px] text-[#cbd5e1] line-clamp-1">
                      {change.reason?.what_changed || change.reason?.compared_with || t("Deviates from established historical behavior")}
                    </p>
                  </div>
                  <span className="text-[10px] font-mono text-[#94a3b8] whitespace-nowrap">
                    {new Date(change.detected_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Tiny New Relationships Summary */}
        <div className="rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-4 shadow-md">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Network size={16} className="text-violet-400" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                {t("New Relationships Summary")}
              </h3>
            </div>
            <button
              onClick={() => nav(`/users/${encodeURIComponent(principal)}/topology`)}
              className="text-[11px] font-bold text-violet-300 hover:text-violet-200 hover:underline flex items-center gap-1"
            >
              <span>{t("Explore topology")}</span>
              <ExternalLink size={12} />
            </button>
          </div>

          <div className="space-y-3">
            {/* New Callers */}
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">
                {t("Novel Callers Touchpoints")} ({newCallers.length})
              </span>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {newCallers.length === 0 ? (
                  <span className="text-xs text-[#cbd5e1] italic">{t("No new callers")}</span>
                ) : (
                  newCallers.slice(0, 4).map((c: any, i: number) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded-md border border-violet-500/50 bg-violet-500/20 px-2 py-0.5 text-xs font-mono font-bold text-violet-200"
                    >
                      <span>+ {c.value}</span>
                    </span>
                  ))
                )}
              </div>
            </div>

            {/* New Targets */}
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">
                {t("Novel Target Services")} ({newTargets.length})
              </span>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {newTargets.length === 0 ? (
                  <span className="text-xs text-[#cbd5e1] italic">{t("No new targets")}</span>
                ) : (
                  newTargets.slice(0, 4).map((t: any, i: number) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded-md border border-cyan-500/50 bg-cyan-500/20 px-2 py-0.5 text-xs font-mono font-bold text-cyan-200"
                    >
                      <span>+ {t.value}</span>
                    </span>
                  ))
                )}
              </div>
            </div>

            {/* New Operations */}
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">
                {t("Novel Operations")} ({newOperations.length})
              </span>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {newOperations.length === 0 ? (
                  <span className="text-xs text-[#cbd5e1] italic">{t("No new operations")}</span>
                ) : (
                  newOperations.slice(0, 3).map((o: any, i: number) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded-md border border-emerald-500/50 bg-emerald-500/20 px-2 py-0.5 text-xs font-mono font-bold text-emerald-200"
                    >
                      <span>+ {o.value}</span>
                    </span>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
