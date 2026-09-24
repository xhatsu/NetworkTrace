import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  UserX,
  ShieldAlert,
  Radio,
  Layers,
  Clock,
  ArrowRight,
  Globe,
  Server,
  AlertTriangle,
  CheckCircle2,
  Lock,
  Search,
  Activity,
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import { api, queryString } from "../api";
import { useFilters } from "../App";
import { useI18n } from "../i18n";

export function UnknownUsersPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedTab, setSelectedTab] = useState<"all" | "auth_fails" | "errors">("all");

  const { data, isLoading, error } = useQuery({
    queryKey: ["unknown-users", filters],
    queryFn: () => api<any>(`/api/v1/unknown-users?${queryString(filters)}`),
  });

  const kpis = data?.kpis || {
    total_requests: 0,
    estate_requests: 0,
    traffic_percentage: 0,
    s_2xx: 0,
    s_auth_fail: 0,
    s_4xx_other: 0,
    s_5xx: 0,
    auth_fail_rate: 0,
    error_rate: 0,
    avg_latency: 0,
    p95_latency: 0,
    p99_latency: 0,
    unique_targets: 0,
    unique_operations: 0,
    unique_sources: 0,
  };

  const series = data?.series || [];
  const topTargets: any[] = data?.top_targets || [];
  const topOperations: any[] = data?.top_operations || [];
  const topSources: any[] = data?.top_sources || [];
  const recentRollups: any[] = data?.recent_rollups || [];

  // These rows summarize five-minute worker rollups; they are not individual traces.
  const filteredRollups = recentRollups.filter((row) => {
    if (selectedTab === "auth_fails" && !row.auth_failure_count) return false;
    if (selectedTab === "errors" && !row.errors) return false;
    if (searchTerm) {
      const s = searchTerm.toLowerCase();
      return (
        row.target_service?.toLowerCase().includes(s) ||
        row.operation?.toLowerCase().includes(s) ||
        row.source_ip?.toLowerCase().includes(s) ||
        row.caller_service?.toLowerCase().includes(s)
      );
    }
    return true;
  });

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
      {/* HEADER BANNER */}
      <div className="relative overflow-hidden rounded-2xl border border-[#262838] bg-gradient-to-r from-[#141624] via-[#10121e] to-[#171329] p-6 shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <div className="grid h-12 w-12 place-items-center rounded-2xl border border-amber-500/40 bg-amber-500/15 text-amber-300 shadow-md">
              <UserX size={24} strokeWidth={2.4} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-extrabold tracking-tight text-white">
                  {t("Unattributed Request Monitor", "Giám Sát Lưu Lượng Chưa Định Danh")}
                </h1>
                <span className="rounded-md border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[10px] font-mono font-bold uppercase text-amber-300">
                  {t("Identity Attribution", "Định Danh Nguồn Gọi")}
                </span>
              </div>
              <p className="text-xs text-[#94a3b8] mt-1 max-w-3xl leading-relaxed">
                {t(
                  "Analytics for requests without a resolved caller identity, including public traffic and authentication failures (401/403).",
                  "Phân tích các giao dịch chưa xác định được danh tính nguồn gọi, gồm lưu lượng công cộng và lỗi xác thực (401/403)."
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <Link
              to="/users"
              className="flex items-center gap-2 rounded-xl border border-cyan-500/40 bg-cyan-500/15 px-3.5 py-2 text-xs font-bold text-cyan-300 transition-all hover:bg-cyan-500/25 hover:text-white"
            >
              <span>{t("View Authenticated Users", "Xem Người Dùng Đã Xác Thực")}</span>
              <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      </div>

      {/* KPI METRIC CARDS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Traffic Volume */}
        <div className="rounded-xl border border-[#262838] bg-[#141624] p-4 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-[#94a3b8] mb-2 font-mono uppercase">
            <span>{t("Unattributed Volume", "Tổng Lưu Lượng Chưa Định Danh")}</span>
            <Radio size={16} className="text-cyan-400" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black font-mono text-white">
              {kpis.total_requests.toLocaleString()}
            </span>
            <span className="text-xs font-mono font-bold text-cyan-300">
              {kpis.traffic_percentage}% {t("of total", "toàn hệ thống")}
            </span>
          </div>
          <div className="mt-2 text-[11px] text-[#64748b] font-mono">
            {kpis.estate_requests.toLocaleString()} {t("total estate transactions", "tổng giao dịch toàn hệ thống")}
          </div>
        </div>

        {/* Card 2: Auth Failure Rate */}
        <div className="rounded-xl border border-[#262838] bg-[#141624] p-4 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-[#94a3b8] mb-2 font-mono uppercase">
            <span>{t("Auth Failure Rate", "Tỷ Lệ Thất Bại Xác Thực")}</span>
            <ShieldAlert size={16} className="text-rose-400" />
          </div>
          <div className="flex items-baseline justify-between">
            <span
              className={`text-2xl font-black font-mono ${
                kpis.auth_fail_rate > 5 ? "text-rose-400" : "text-white"
              }`}
            >
              {kpis.auth_fail_rate}%
            </span>
            <span className="text-xs font-mono text-rose-300 font-bold">
              {kpis.s_auth_fail.toLocaleString()} {t("401/403 fails", "lỗi 401/403")}
            </span>
          </div>
          <div className="mt-2 text-[11px] text-[#64748b] font-mono flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
            <span>{t("Potential probing / invalid tokens", "Dấu hiệu quét dò / token không hợp lệ")}</span>
          </div>
        </div>

        {/* Card 3: Latency */}
        <div className="rounded-xl border border-[#262838] bg-[#141624] p-4 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-[#94a3b8] mb-2 font-mono uppercase">
            <span>{t("Avg / P95 Latency", "Độ Trễ Trung Bình / P95")}</span>
            <Clock size={16} className="text-emerald-400" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black font-mono text-emerald-300">
              {kpis.p95_latency} <span className="text-xs font-normal text-[#94a3b8]">ms</span>
            </span>
            <span className="text-xs font-mono text-[#94a3b8]">
              {t("Avg:", "TB:")} {kpis.avg_latency} ms
            </span>
          </div>
          <div className="mt-2 text-[11px] text-[#64748b] font-mono">
            {t("P99 Latency:", "Độ trễ P99:")} {kpis.p99_latency} ms
          </div>
        </div>

        {/* Card 4: Surface */}
        <div className="rounded-xl border border-[#262838] bg-[#141624] p-4 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-[#94a3b8] mb-2 font-mono uppercase">
            <span>{t("Explored Surface", "Bề Mặt Tiếp Xúc")}</span>
            <Layers size={16} className="text-amber-400" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black font-mono text-amber-300">
              {kpis.unique_targets} <span className="text-xs font-normal text-[#94a3b8]">{t("Services", "Dịch vụ")}</span>
            </span>
            <span className="text-xs font-mono text-amber-200">
              {kpis.unique_sources} {t("Source IPs", "IP Nguồn")}
            </span>
          </div>
          <div className="mt-2 text-[11px] text-[#64748b] font-mono">
            {kpis.unique_operations} {t("Distinct operations probed", "Thao tác / APIs riêng biệt")}
          </div>
        </div>
      </div>

      {/* SECTION 2: TIME-SERIES TRAFFIC & ERROR DYNAMICS */}
      <div className="rounded-2xl border border-[#262838] bg-[#141624] p-5 shadow-lg space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 pb-3">
          <div>
            <h2 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <Activity size={16} className="text-cyan-400" />
              <span>{t("Unattributed Traffic & Error Dynamics", "Biến Động Lưu Lượng Chưa Định Danh & Tỷ Lệ Lỗi")}</span>
            </h2>
            <p className="text-xs text-[#cbd5e1] mt-0.5">
              {t("Requests without errors and failed requests from worker metrics", "Yêu cầu không lỗi và yêu cầu thất bại từ số liệu tổng hợp của worker")}
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs font-mono text-[#94a3b8]">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-cyan-400" />
              <span>{t("Non-error requests", "Yêu cầu không lỗi")}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-rose-400" />
              <span>{t("Failed requests", "Yêu cầu thất bại")}</span>
            </span>
          </div>
        </div>

        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 10, right: 15, left: -20, bottom: 5 }}>
              <defs>
                <linearGradient id="anonSuccessGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00f0ff" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#00f0ff" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="anonAuthFailGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.0} />
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
              <YAxis stroke="#cbd5e1" fontSize={11} allowDecimals={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#18142c",
                  borderColor: "rgba(255,255,255,0.2)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelFormatter={(ts: any) => (ts ? new Date(Number(ts)).toLocaleString() : "")}
              />
              <Area
                type="linear"
                dataKey="non_error_requests"
                name={t("Non-error requests", "Yêu cầu không lỗi")}
                stroke="#00f0ff"
                fill="url(#anonSuccessGrad)"
                strokeWidth={1.25}
              />
              <Area
                type="linear"
                dataKey="error_requests"
                name={t("Failed requests", "Yêu cầu thất bại")}
                stroke="#f43f5e"
                fill="url(#anonAuthFailGrad)"
                strokeWidth={1.25}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* SECTION 3: THREE-COLUMN ATTRIBUTION BREAKDOWN */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Column 1: Top Target Services */}
        <div className="rounded-2xl border border-[#262838] bg-[#141624] p-4 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-white/5 pb-2.5 mb-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-1.5">
                <Server size={14} className="text-indigo-400" />
                <span>{t("Top Target Services", "Top Dịch Vụ Đích")}</span>
              </h3>
              <span className="text-[10px] font-mono text-[#94a3b8]">{topTargets.length} {t("services")}</span>
            </div>

            <div className="space-y-2.5">
              {topTargets.length === 0 ? (
                <div className="py-8 text-center text-xs text-[#94a3b8]">{t("No target services recorded")}</div>
              ) : (
                topTargets.slice(0, 6).map((svc) => (
                  <div key={svc.target_service} className="rounded-lg border border-[#262838] bg-[#10121e] p-2.5 space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold text-white font-mono truncate max-w-[170px]" title={svc.target_service}>
                        {svc.target_service}
                      </span>
                      <span className="font-mono text-cyan-300 font-bold">
                        {svc.requests.toLocaleString()} {t("reqs")}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[10px] font-mono text-[#94a3b8]">
                      <span>{t("Share:")} {Math.round(svc.share * 100)}%</span>
                      {svc.auth_failures > 0 ? (
                        <span className="text-rose-400 font-bold">{svc.auth_failures} {t("auth fails")}</span>
                      ) : (
                        <span className="text-emerald-400">{t("0 auth fails")}</span>
                      )}
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                      <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${Math.max(3, svc.share * 100)}%` }} />
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Column 2: Top Operations / APIs */}
        <div className="rounded-2xl border border-[#262838] bg-[#141624] p-4 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-white/5 pb-2.5 mb-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-1.5">
                <Layers size={14} className="text-cyan-400" />
                <span>{t("Top Operations & APIs", "Top Thao Tác & APIs")}</span>
              </h3>
              <span className="text-[10px] font-mono text-[#94a3b8]">{topOperations.length} {t("endpoints")}</span>
            </div>

            <div className="space-y-2.5">
              {topOperations.length === 0 ? (
                <div className="py-8 text-center text-xs text-[#94a3b8]">{t("No operations recorded")}</div>
              ) : (
                topOperations.slice(0, 6).map((op) => (
                  <div key={`${op.target_service}-${op.operation}`} className="rounded-lg border border-[#262838] bg-[#10121e] p-2.5 space-y-1.5">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="font-bold text-white truncate max-w-[170px]" title={op.operation}>
                        {op.operation}
                      </span>
                      <span className="text-cyan-300 font-bold">
                        {op.requests.toLocaleString()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[10px] font-mono text-[#94a3b8]">
                      <span className="truncate max-w-[120px] text-[#64748b]">{op.target_service}</span>
                      <span>{Math.round(op.share * 100)}% {t("share")}</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                      <div className="h-full bg-cyan-400 rounded-full" style={{ width: `${Math.max(3, op.share * 100)}%` }} />
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Column 3: Top Source IPs */}
        <div className="rounded-2xl border border-[#262838] bg-[#141624] p-4 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-white/5 pb-2.5 mb-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-1.5">
                <Globe size={14} className="text-amber-400" />
                <span>{t("Top Source IPs & Infrastructure Role", "Top Địa Chỉ IP Nguồn")}</span>
              </h3>
              <span className="text-[10px] font-mono text-[#94a3b8]">{topSources.length} {t("addresses")}</span>
            </div>

            <div className="space-y-2.5">
              {topSources.length === 0 ? (
                <div className="py-8 text-center text-xs text-[#94a3b8]">{t("No source IPs recorded")}</div>
              ) : (
                topSources.slice(0, 6).map((src) => (
                  <div key={src.source_ip} className="rounded-lg border border-[#262838] bg-[#10121e] p-2.5 space-y-1.5">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="font-bold text-white truncate max-w-[140px]" title={src.source_ip}>
                        {src.source_ip}
                      </span>
                      <span
                        className={`text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase ${
                          src.is_load_balancer
                            ? "bg-amber-500/15 border-amber-500/30 text-amber-300"
                            : "bg-cyan-500/15 border-cyan-500/30 text-cyan-300"
                        }`}
                      >
                        {src.role_label || (src.is_load_balancer ? "Load Balancer" : "Client IP")}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[10px] font-mono text-[#94a3b8]">
                      <span>{src.requests.toLocaleString()} {t("reqs")} ({Math.round(src.share * 100)}%)</span>
                      {src.auth_failures > 0 ? (
                        <span className="text-rose-400 font-bold">{src.auth_failures} {t("fails")}</span>
                      ) : (
                        <span className="text-emerald-400">{t("clean")}</span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 4: RECENT UNIDENTIFIED TRACES TABLE */}
      <div className="rounded-2xl border border-[#262838] bg-[#141624] p-5 shadow-lg space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 pb-3">
          <div>
            <h2 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <Lock size={16} className="text-amber-400" />
              <span>{t("Recent Unattributed Traces", "Danh Sách Giao Dịch Chưa Định Danh Gần Nhất")}</span>
            </h2>
            <p className="text-xs text-[#cbd5e1] mt-0.5">
              {t("Inspect raw unattributed requests, verify response statuses, and jump directly to trace waterfall", "Xem chi tiết các giao dịch chưa định danh, kiểm tra mã phản hồi và xem waterfall span")}
            </p>
          </div>

          <div className="flex items-center gap-3">
            {/* Filter Tabs */}
            <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 p-1 text-xs">
              <button
                onClick={() => setSelectedTab("all")}
                className={`rounded px-2.5 py-1 transition-all ${
                  selectedTab === "all" ? "bg-cyan-500 text-black font-bold" : "text-[#94a3b8] hover:text-white"
                }`}
              >
                {t("All", "Tất cả")}
              </button>
              <button
                onClick={() => setSelectedTab("auth_fails")}
                className={`rounded px-2.5 py-1 transition-all ${
                  selectedTab === "auth_fails" ? "bg-rose-500 text-white font-bold" : "text-[#94a3b8] hover:text-white"
                }`}
              >
                {t("Auth Fails (401/403)", "Lỗi Xác thực (401/403)")}
              </button>
              <button
                onClick={() => setSelectedTab("errors")}
                className={`rounded px-2.5 py-1 transition-all ${
                  selectedTab === "errors" ? "bg-amber-500 text-black font-bold" : "text-[#94a3b8] hover:text-white"
                }`}
              >
                {t("5xx Errors", "Lỗi Máy chủ 5xx")}
              </button>
            </div>

            {/* Search Input */}
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#64748b]" />
              <input
                type="text"
                placeholder={t("Filter by service, API, IP...", "Lọc theo service, API, IP...")}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="h-8 rounded-lg border border-white/10 bg-[#10121e] pl-8 pr-3 text-xs text-white placeholder-[#64748b] focus:border-cyan-400 focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/10 text-[11px] font-mono uppercase text-[#94a3b8]">
                <th className="py-2.5 px-3">{t("Timestamp", "Thời gian")}</th>
                <th className="py-2.5 px-3">{t("Target Service", "Dịch vụ Đích")}</th>
                <th className="py-2.5 px-3">{t("Operation / Endpoint", "Thao tác / API")}</th>
                <th className="py-2.5 px-3">{t("Source IP", "Địa chỉ IP")}</th>
                <th className="py-2.5 px-3 text-right">{t("Requests", "Yêu cầu")}</th>
                <th className="py-2.5 px-3 text-right">{t("Errors", "Lỗi")}</th>
                <th className="py-2.5 px-3 text-right">{t("Auth failures", "Lỗi xác thực")}</th>
                <th className="py-2.5 px-3 text-right">{t("P95 latency", "Độ trễ P95")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 font-mono">
              {filteredRollups.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-10 text-center text-xs text-[#94a3b8]">
                    {t("No matching unattributed activity found", "Không tìm thấy hoạt động chưa định danh phù hợp")}
                  </td>
                </tr>
              ) : (
                filteredRollups.map((row) => {
                  return (
                    <tr key={[row.timestamp_ms, row.caller_service, row.target_service, row.operation, row.source_ip].join("|")} className="hover:bg-white/5 transition-colors">
                      <td className="py-2.5 px-3 text-[#94a3b8]">
                        {new Date(row.timestamp_ms).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </td>
                      <td className="py-2.5 px-3 font-bold text-white">{row.target_service}</td>
                      <td className="py-2.5 px-3 text-cyan-300 max-w-[240px] truncate" title={row.operation}>
                        {row.operation}
                      </td>
                      <td className="py-2.5 px-3 text-[#94a3b8]">{row.source_ip || "—"}</td>
                      <td className="py-2.5 px-3 text-right text-white">{Number(row.requests || 0).toLocaleString()}</td>
                      <td className={"py-2.5 px-3 text-right " + (row.errors ? "text-rose-300" : "text-[#94a3b8]")}>{Number(row.errors || 0).toLocaleString()}</td>
                      <td className={"py-2.5 px-3 text-right " + (row.auth_failure_count ? "text-amber-300" : "text-[#94a3b8]")}>{Number(row.auth_failure_count || 0).toLocaleString()}</td>
                      <td className="py-2.5 px-3 text-right text-[#94a3b8]">{Number(row.duration_ms || 0).toLocaleString()} ms</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
