import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Clock,
  Crosshair,
  Flame,
  Gauge,
  Info,
  Server,
  ShieldAlert,
  Zap,
} from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import { api, queryString } from "../../api";
import { useFilters } from "../../App";
import { useI18n } from "../../i18n";

export function UserActivityTab() {
  const { principal } = useOutletContext<{ principal: string; profile: any }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const [selectedSlice, setSelectedSlice] = useState<any | null>(null);
  const [selectedSourceIp, setSelectedSourceIp] = useState<string>("");

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

  const { data: perfData, isLoading } = useQuery({
    queryKey: ["user-performance", principal, filters, selectedSourceIp],
    queryFn: () => {
      const extra = selectedSourceIp ? { source_ip: selectedSourceIp } : {};
      return api<any>(`/api/v1/users/${encodeURIComponent(principal)}/performance?${queryString(filters, extra)}`);
    },
    enabled: !!principal,
  });

  const series = perfData?.series || [];
  const burstiness = perfData?.burstiness ?? 1.0;
  const availableSources: any[] = perfData?.available_sources || [];

  // Compute aggregated totals for Traffic, Errors, Latency
  const totalRequests = series.reduce((acc: number, s: any) => acc + (s.requests || 0), 0);
  const totalErrors = series.reduce((acc: number, s: any) => acc + (s.errors || 0), 0);
  const total2xx = series.reduce((acc: number, s: any) => acc + (s.s_2xx || 0), 0);
  const total4xx = series.reduce((acc: number, s: any) => acc + (s.s_4xx || 0), 0);
  const total5xx = series.reduce((acc: number, s: any) => acc + (s.s_5xx || 0), 0);
  const totalTimeout = series.reduce((acc: number, s: any) => acc + (s.s_timeout || 0), 0);

  const maxRps = series.length ? Math.max(...series.map((s: any) => s.rps || 0)) : 0;
  const avgRps = series.length ? (series.reduce((acc: number, s: any) => acc + (s.rps || 0), 0) / series.length).toFixed(1) : "0.0";

  // Compute 100% stacked values for status chart
  const stackedSeries = series.map((s: any) => {
    const total = (s.s_2xx || 0) + (s.s_4xx || 0) + (s.s_5xx || 0) + (s.s_timeout || 0) || 1;
    return {
      ...s,
      pct_2xx: Math.round(((s.s_2xx || 0) / total) * 100),
      pct_4xx: Math.round(((s.s_4xx || 0) / total) * 100),
      pct_5xx: Math.round(((s.s_5xx || 0) / total) * 100),
      pct_timeout: Math.round(((s.s_timeout || 0) / total) * 100),
    };
  });

  const handleChartClick = (e: any) => {
    if (e && e.activePayload && e.activePayload.length > 0) {
      setSelectedSlice(e.activePayload[0].payload);
    }
  };

  const selectedSrcObj = availableSources.find((s: any) => s.ip === selectedSourceIp);

  return (
    <div className="space-y-6">
      {/* Question header banner & IP filter */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-emerald-500/20 text-emerald-300">
            <Activity size={16} />
          </div>
          <div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-white">
              {t("Traffic Dynamics & Execution Latency")}
            </h2>
            <p className="text-[11px] text-[#cbd5e1]">
              {t("Primary Question:")} <strong className="text-emerald-300">“{t("How has this user’s traffic/performance changed?")}”</strong>
            </p>
          </div>
        </div>

        {/* Optional Filter by Source IP */}
        <div className="flex flex-wrap items-center gap-2">
          {availableSources.length > 0 && (
            <div className="flex items-center gap-1.5 rounded-lg border border-[#383b52] bg-[#141624] px-2.5 py-1">
              <span className="text-[10px] uppercase font-bold tracking-wider text-[#94a3b8]">{t("Filter by Source IP")}:</span>
              <select
                value={selectedSourceIp}
                onChange={(e) => setSelectedSourceIp(e.target.value)}
                className="bg-transparent text-xs font-mono text-cyan-300 focus:outline-none cursor-pointer"
              >
                <option value="" className="bg-[#141624] text-white">{t("All Source IPs (Aggregated)")}</option>
                {availableSources.map((src: any) => (
                  <option key={src.ip} value={src.ip} className="bg-[#141624] text-white">
                    {src.ip} [{src.role_label}]
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex items-center gap-1.5 text-xs font-mono text-[#cbd5e1]">
            <Crosshair size={13} className="text-cyan-400" />
            <span className="hidden sm:inline">{t("Click any point on any chart to freeze that 1-minute bucket")}</span>
          </div>
        </div>
      </div>

      {selectedSourceIp && selectedSrcObj && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-mono text-amber-200">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-amber-400" />
            <span>
              {t("Filtered by Source IP")}: <strong>{selectedSourceIp}</strong> ({selectedSrcObj.role_label} · {selectedSrcObj.attribution_confidence} {t("confidence")})
            </span>
          </div>
          <button
            onClick={() => setSelectedSourceIp("")}
            className="rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-amber-500/20 hover:bg-amber-500/30 text-white"
          >
            {t("Reset to All IPs", "Đặt lại tất cả IP")}
          </button>
        </div>
      )}

      {selectedSlice && (
        <div className="rounded-xl border border-cyan-500/40 bg-[#151826] p-4 animate-in fade-in duration-200">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="flex h-2.5 w-2.5 rounded-full bg-cyan-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-cyan-300">
                {t("Interactive Pinned Time-Slice Inspector")}: {new Date(selectedSlice.bucket_start).toLocaleString()}
              </span>
            </div>
            <button
              onClick={() => setSelectedSlice(null)}
              className="text-xs text-[#cbd5e1] hover:text-white underline"
            >
              {t("Unfreeze")}
            </button>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 lg:grid-cols-8">
            <div className="rounded-lg bg-[#0e1019] p-2 border border-[#242738]">
              <span className="text-[10px] font-bold text-[#94a3b8] uppercase">{t("Requests")}</span>
              <div className="font-mono text-base font-bold text-white">{selectedSlice.requests}</div>
            </div>
            <div className="rounded-lg bg-[#0e1019] p-2 border border-[#242738]">
              <span className="text-[10px] font-bold text-[#94a3b8] uppercase">{t("TPS")}</span>
              <div className="font-mono text-base font-bold text-cyan-300">{selectedSlice.rps} tps</div>
            </div>
            <div className="rounded-lg bg-[#0e1019] p-2 border border-[#242738]">
              <span className="text-[10px] font-bold text-[#94a3b8] uppercase">2xx {t("Success", "Thành công")}</span>
              <div className="font-mono text-base font-bold text-emerald-300">{selectedSlice.s_2xx}</div>
            </div>
            <div className="rounded-lg bg-[#0e1019] p-2 border border-[#242738]">
              <span className="text-[10px] font-bold text-[#94a3b8] uppercase">4xx {t("Client Err", "Lỗi khách")}</span>
              <div className="font-mono text-base font-bold text-amber-300">{selectedSlice.s_4xx}</div>
            </div>
            <div className="rounded-lg bg-black/30 p-2 border border-white/10">
              <span className="text-[10px] font-bold text-[#94a3b8] uppercase">5xx {t("Server Err", "Lỗi máy chủ")}</span>
              <div className="font-mono text-base font-bold text-rose-300">{selectedSlice.s_5xx}</div>
            </div>
            <div className="rounded-lg bg-black/30 p-2 border border-white/10">
              <span className="text-[10px] font-bold text-[#94a3b8] uppercase">P50 {t("Latency", "Độ trễ")}</span>
              <div className="font-mono text-base font-bold text-emerald-300">{selectedSlice.latency_p50} ms</div>
            </div>
            <div className="rounded-lg bg-black/30 p-2 border border-white/10">
              <span className="text-[10px] font-bold text-[#94a3b8] uppercase">P95 {t("Latency", "Độ trễ")}</span>
              <div className="font-mono text-base font-bold text-amber-300">{selectedSlice.latency_p95} ms</div>
            </div>
            <div className="rounded-lg bg-black/30 p-2 border border-white/10">
              <span className="text-[10px] font-bold text-[#94a3b8] uppercase">P99 {t("Latency", "Độ trễ")}</span>
              <div className="font-mono text-base font-bold text-rose-300">{selectedSlice.latency_p99} ms</div>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 1: TRAFFIC */}
      <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <Zap size={16} className="text-cyan-400" />
              <h3 className="text-sm font-bold uppercase tracking-wider text-white">
                1. {t("Throughput TPS vs Baseline", "Thông lượng TPS & Baseline Lịch sử")}
              </h3>
            </div>
            <p className="text-xs text-[#cbd5e1]">
              {t("Observed throughput TPS vs historical baseline and burst ratio", "Thông lượng TPS thực tế so với baseline lịch sử và hệ số bùng phát")}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1 text-xs font-mono font-bold text-cyan-200">
              {t("Peak", "Đỉnh")}: {maxRps} TPS
            </div>
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1 text-xs font-mono font-bold text-emerald-200">
              {t("Avg")}: {avgRps} TPS
            </div>
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1 text-xs font-mono font-bold text-amber-200 flex items-center gap-1.5">
              <Flame size={13} className="text-amber-400" />
              <span>{t("Burstiness", "Độ bùng nổ")}: {burstiness}x</span>
            </div>
          </div>
        </div>

        <div className="h-64 w-full cursor-crosshair">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={series}
              onClick={handleChartClick}
              margin={{ top: 5, right: 20, left: -10, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="bucket_start"
                tickFormatter={formatTick}
                stroke="#cbd5e1"
                fontSize={11}
              />
              <YAxis stroke="#cbd5e1" fontSize={11} />
              <Tooltip
                contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                formatter={(val: any, name: any, item: any) => {
                  const key = item?.dataKey || "";
                  const isObserved = key === "rps" || name === "Observed TPS" || name === "Throughput (TPS)" || name === "Throughput (RPS)";
                  if (isObserved) {
                    return [`${Number(val || 0).toFixed(2)} tps`, t("Observed TPS")];
                  }
                  return [`${Number(val || 0).toFixed(2)} tps`, t("Baseline TPS")];
                }}
                labelFormatter={formatTooltip}
              />
              <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
              <Line
                type="monotone"
                dataKey="rps"
                name={t("Observed TPS")}
                stroke="#00f0ff"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 6, fill: "#00f0ff", stroke: "#fff" }}
              />
              <Line
                type="monotone"
                dataKey="baseline_rps"
                name={t("Baseline TPS")}
                stroke="#b388ff"
                strokeWidth={1.8}
                strokeDasharray="4 4"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* SECTION 2: RELIABILITY (Error Dynamics & Stacked Status) */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Error Rate Area Chart */}
        <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
          <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <AlertTriangle size={16} className="text-rose-400" />
                <span>{t("Error Rate Dynamics")}</span>
              </h3>
              <p className="text-xs text-[#cbd5e1]">{t("Ratio of HTTP 4xx, 5xx, and failures to total requests", "Tỷ lệ lỗi HTTP 4xx, 5xx và lỗi mạng trên tổng yêu cầu")}</p>
            </div>
            <div className="font-mono text-xs font-bold text-rose-300">
              {t("Total Failures", "Tổng lỗi")}: {totalErrors.toLocaleString()}
            </div>
          </div>

          <div className="h-60 w-full cursor-crosshair">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={series}
                onClick={handleChartClick}
                margin={{ top: 5, right: 10, left: -15, bottom: 5 }}
              >
                <defs>
                  <linearGradient id="errorRateGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ff1744" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#ff1744" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis
                  dataKey="bucket_start"
                  tickFormatter={formatTick}
                  stroke="#cbd5e1"
                  fontSize={11}
                />
                <YAxis stroke="#cbd5e1" fontSize={11} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                  formatter={(val: any) => [`${(Number(val) * 100).toFixed(2)}%`, t("Error Rate")]}
                  labelFormatter={formatTooltip}
                />
                <Area
                  type="monotone"
                  dataKey="error_rate"
                  name={t("Error Rate")}
                  stroke="#ff1744"
                  strokeWidth={2.5}
                  fillOpacity={1}
                  fill="url(#errorRateGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* 100% Stacked Status Chart (2xx, 4xx, 5xx, timeout) */}
        <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
          <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <Server size={16} className="text-emerald-400" />
                <span>{t("100% Stacked Status Chart")}</span>
              </h3>
              <p className="text-xs text-[#cbd5e1]">{t("Proportion of 2xx Success, 4xx Client Errors, 5xx Server Outages, and Timeouts")}</p>
            </div>
            <div className="flex items-center gap-2 text-[10px] font-mono">
              <span className="text-emerald-400">{total2xx} 2xx</span>
              <span className="text-amber-400">{total4xx} 4xx</span>
              <span className="text-rose-400">{total5xx} 5xx</span>
            </div>
          </div>

          <div className="h-60 w-full cursor-crosshair">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={stackedSeries}
                onClick={handleChartClick}
                margin={{ top: 5, right: 10, left: -15, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis
                  dataKey="bucket_start"
                  tickFormatter={formatTick}
                  stroke="#cbd5e1"
                  fontSize={11}
                />
                <YAxis stroke="#cbd5e1" fontSize={11} tickFormatter={(v) => `${v}%`} domain={[0, 100]} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                  formatter={(val: any, name: any) => [`${val}%`, name]}
                  labelFormatter={formatTooltip}
                />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Bar dataKey="pct_2xx" name={`2xx ${t("Success", "Thành công")}`} stackId="status" fill="#00e676" />
                <Bar dataKey="pct_4xx" name={`4xx ${t("Client Error", "Lỗi khách")}`} stackId="status" fill="#ffab00" />
                <Bar dataKey="pct_5xx" name={`5xx ${t("Server Outage", "Lỗi máy chủ")}`} stackId="status" fill="#ff1744" />
                <Bar dataKey="pct_timeout" name={t("Timeout", "Hết thời gian")} stackId="status" fill="#00b0ff" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* SECTION 3: LATENCY (p50, p95, p99 multi-line time series) */}
      <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <Clock size={16} className="text-amber-400" />
              <h3 className="text-sm font-bold uppercase tracking-wider text-white">
                3. {t("Latency Multi-Percentile Waterfall")}
              </h3>
            </div>
            <p className="text-xs text-[#cbd5e1]">
              {t("Detailed percentile distributions exposing tail-latency spikes and execution degradation")}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs font-mono font-bold text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-[#00e676]" /> {t("p50 (Median)")}
            </span>
            <span className="flex items-center gap-1.5 text-xs font-mono font-bold text-amber-300">
              <span className="h-2 w-2 rounded-full bg-[#ffab00]" /> {t("p95 (Tail)")}
            </span>
            <span className="flex items-center gap-1.5 text-xs font-mono font-bold text-rose-300">
              <span className="h-2 w-2 rounded-full bg-[#ff1744]" /> {t("p99 (Extreme Tail)")}
            </span>
          </div>
        </div>

        <div className="h-64 w-full cursor-crosshair">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={series}
              onClick={handleChartClick}
              margin={{ top: 5, right: 20, left: -10, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="bucket_start"
                tickFormatter={formatTick}
                stroke="#cbd5e1"
                fontSize={11}
              />
              <YAxis stroke="#cbd5e1" fontSize={11} tickFormatter={(v) => `${v}ms`} />
              <Tooltip
                contentStyle={{ backgroundColor: "#18142c", borderColor: "rgba(255,255,255,0.2)", borderRadius: 8 }}
                formatter={(val: any, name: any, item: any) => {
                  const label = name || item?.name || item?.dataKey || t("Latency", "Độ trễ");
                  return [`${Number(val || 0).toFixed(1)} ms`, label];
                }}
                labelFormatter={formatTooltip}
              />
              <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
              <Line
                type="monotone"
                dataKey="latency_p50"
                name={t("p50 (Median)")}
                stroke="#00e676"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5, fill: "#00e676" }}
              />
              <Line
                type="monotone"
                dataKey="latency_p95"
                name={t("p95 (Tail)")}
                stroke="#ffab00"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 6, fill: "#ffab00" }}
              />
              <Line
                type="monotone"
                dataKey="latency_p99"
                name={t("p99 (Extreme Tail)")}
                stroke="#ff1744"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5, fill: "#ff1744" }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
