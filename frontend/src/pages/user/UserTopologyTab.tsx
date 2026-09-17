import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Clock,
  Filter,
  Layers,
  Network,
  Radio,
  Server,
  ShieldAlert,
  Sparkles,
  User,
  X,
  Zap,
} from "lucide-react";
import { api, queryString } from "../../api";
import { useFilters } from "../../App";
import { useI18n } from "../../i18n";

export function UserTopologyTab() {
  const { principal } = useOutletContext<{ principal: string; profile: any }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const [timeFilter, setTimeFilter] = useState<"5m" | "1h" | "24h" | "all">("1h");
  const [statusFilter, setStatusFilter] = useState<"all" | "normal" | "changed" | "new" | "errors">("all");
  const [showNetworkPath, setShowNetworkPath] = useState<boolean>(false);
  const [expandedTarget, setExpandedTarget] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<any | null>(null);

  // Fetch topology data
  const { data: topoData, isLoading } = useQuery({
    queryKey: ["user-topology", principal, timeFilter],
    queryFn: () => {
      const extra: Record<string, string> = {};
      const now = Date.now();
      if (timeFilter === "5m") {
        extra.start = String(now - 300_000);
        extra.end = String(now);
      } else if (timeFilter === "1h") {
        extra.start = String(now - 3600_000);
        extra.end = String(now);
      } else if (timeFilter === "24h") {
        extra.start = String(now - 86400_000);
        extra.end = String(now);
      }
      return api<any>(`/api/v1/users/${encodeURIComponent(principal)}/topology?${queryString(filters, extra)}`);
    },
    enabled: !!principal,
  });

  const callers: any[] = topoData?.callers || [];
  const targets: any[] = topoData?.targets || [];
  const rawEdges: any[] = topoData?.edges || [];
  const targetOperations: Record<string, any[]> = topoData?.target_operations || {};
  const networkHops: any[] = topoData?.network_hops || [];

  // Filter edges based on status filter
  const filteredEdges = rawEdges.filter((e) => {
    if (statusFilter === "normal") return !e.is_changed && (e.error_rate || 0) === 0;
    if (statusFilter === "changed") return e.is_changed;
    if (statusFilter === "new") return e.is_changed || e.is_new;
    if (statusFilter === "errors") return (e.error_rate || 0) > 0;
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Question Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-violet-500/20 text-violet-300">
            <Network size={16} />
          </div>
          <div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-white">
              {t("User Access Topology & Call Paths")}
            </h2>
            <p className="text-[11px] text-[#cbd5e1]">
              {t("Primary Question:")} <strong className="text-violet-300">“{t("What systems is this user touching?")}”</strong>
            </p>
          </div>
        </div>

        {/* Filters and Network Path Toggle */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Show Network Path Toggle Checkbox */}
          <label className="flex items-center gap-2 cursor-pointer select-none rounded-lg border border-[#383b52] bg-[#141624] px-2.5 py-1 text-xs text-[#cbd5e1] hover:text-white transition">
            <input
              type="checkbox"
              checked={showNetworkPath}
              onChange={(e) => setShowNetworkPath(e.target.checked)}
              className="rounded border-[#383b52] bg-black text-cyan-500 focus:ring-0 focus:ring-offset-0 cursor-pointer"
            />
            <span className="font-medium text-[11px]">{t("Show network path (IPs / Proxies)")}</span>
          </label>

          {/* Time Filter */}
          <div className="flex items-center rounded-lg border border-white/10 bg-black/40 p-0.5 text-xs">
            {(["5m", "1h", "24h", "all"] as const).map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeFilter(tf)}
                className={`rounded px-2.5 py-1 font-semibold transition ${
                  timeFilter === tf
                    ? "bg-cyan-500 text-black font-bold shadow-sm"
                    : "text-[#cbd5e1] hover:text-white"
                }`}
              >
                {tf === "5m" ? t("Last 5m", "5 phút qua") : tf === "1h" ? t("Last 1h", "1 giờ qua") : tf === "24h" ? t("Last 24h", "24 giờ qua") : t("All Time", "Tất cả")}
              </button>
            ))}
          </div>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as any)}
            className="rounded-lg border border-white/20 bg-[#1e1938] px-2.5 py-1 text-xs font-semibold text-white focus:outline-none cursor-pointer"
          >
            <option value="all">{t("All Relationships", "Tất cả Mối Quan Hệ")}</option>
            <option value="normal">{t("Normal Only", "Chỉ Bình Thường")}</option>
            <option value="changed">{t("Changed Only", "Chỉ Thay Đổi")}</option>
            <option value="new">{t("New Relationships Only", "Chỉ Quan Hệ Mới")}</option>
            <option value="errors">{t("Errors Only", "Chỉ Bị Lỗi")}</option>
          </select>
        </div>
      </div>

      {/* Main Interactive Graph & Edge Inspector */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Graph Canvas Panel (2 Columns width) */}
        <div className="lg:col-span-2 rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
          <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                {t("User")} → {showNetworkPath ? `${t("Network Ingress (IP/Proxy)", "Ingress Mạng (IP/Proxy)")} → ` : ""}{t("Caller Services")} → {t("Target Services")}
              </h3>
              <p className="text-[11px] text-[#cbd5e1]">
                {showNetworkPath
                  ? t("Showing intermediate network ingress IPs/load balancers before caller services.", "Hiển thị các IP ingress/bộ cân bằng tải trung gian trước dịch vụ gọi.")
                  : t("Pure behavioral path without intermediary network hops. Toggle 'Show network path' to view LB hops.", "Tuyến hành vi trực tiếp không qua các bước mạng trung gian. Bật 'Hiển thị đường đi mạng' để xem các chặng LB.")}
              </p>
            </div>
            <span className="text-xs font-mono text-cyan-300 font-bold">
              {filteredEdges.length} {t("Active Paths", "Tuyến hoạt động")}
            </span>
          </div>

          {isLoading ? (
            <div className="grid h-80 place-items-center">
              <span className="text-xs text-cyan-300 animate-pulse">{t("Loading...", "Đang xây dựng sơ đồ tô-pô...")}</span>
            </div>
          ) : callers.length === 0 && targets.length === 0 ? (
            <div className="py-16 text-center text-xs text-[#cbd5e1]">
              {t("No topology edges detected for this user in the selected time range.", "Không tìm thấy liên kết tô-pô nào cho người dùng này trong khoảng thời gian đã chọn.")}
            </div>
          ) : (
            <div className={`grid grid-cols-1 ${showNetworkPath ? "md:grid-cols-4" : "md:grid-cols-3"} gap-6 relative`}>
              {/* Column 1: USER NODE */}
              <div className="flex flex-col items-center justify-center space-y-4">
                <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("Origin Identity", "Định danh Nguồn")}</span>
                <div className="w-full max-w-[200px] rounded-xl border-2 border-cyan-500 bg-[#161a28] p-4 text-center">
                  <div className="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-cyan-500 text-black font-bold mb-2">
                    <User size={20} />
                  </div>
                  <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-300">{t("Principal", "Định danh")}</div>
                  <div className="truncate font-mono text-sm font-bold text-white" title={principal}>
                    {principal}
                  </div>
                </div>
              </div>

              {/* Optional Column 2: NETWORK HOPS (IPs / PROXIES / LBs) */}
              {showNetworkPath && (
                <div className="space-y-3">
                  <div className="text-center">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-amber-300">
                      {t("Network Ingress", "Ingress Mạng")} ({networkHops.length})
                    </span>
                  </div>
                  <div className="space-y-2.5 max-h-[500px] overflow-y-auto scrollbar pr-1">
                    {networkHops.length === 0 ? (
                      <div className="rounded-xl border border-dashed border-[#383b52] p-3 text-center text-xs text-[#94a3b8]">
                        {t("Direct / No proxy hop observed", "Trực tiếp / Không qua proxy trung gian")}
                      </div>
                    ) : (
                      networkHops.map((hop: any, hIdx: number) => (
                        <div
                          key={hIdx}
                          className="rounded-xl border border-dashed border-amber-500/40 bg-[#151624] p-3 transition hover:border-amber-400"
                        >
                          <div className="flex items-center justify-between gap-1.5">
                            <span className="truncate font-mono text-xs font-bold text-amber-200" title={hop.source_ip}>
                              {hop.source_ip}
                            </span>
                            <span
                              className={`rounded px-1.5 py-0.5 text-[9px] font-mono uppercase font-bold border ${
                                hop.attribution_confidence === "low"
                                  ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                                  : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                              }`}
                            >
                              {hop.role_label}
                            </span>
                          </div>
                          <div className="mt-1.5 flex items-center justify-between text-[10px] font-mono text-[#94a3b8]">
                            <span>{t("Conf", "Độ tin cậy")}: {hop.attribution_confidence}</span>
                            <span>→ {hop.caller}</span>
                          </div>
                          <div className="mt-1 text-[10px] font-mono text-[#cbd5e1]">
                            {(hop.requests || 0).toLocaleString()} {t("reqs", "yêu cầu")}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* Column: CALLER SERVICES */}
              <div className="space-y-3">
                <div className="text-center">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">
                    {t("Caller Services")} ({callers.length})
                  </span>
                </div>
                <div className="space-y-2.5 max-h-[500px] overflow-y-auto scrollbar pr-1">
                  {callers.map((c) => (
                    <div
                      key={c.id}
                      className={`rounded-xl border p-3 transition ${
                        c.is_new
                          ? "border-amber-500 bg-amber-500/15"
                          : "border-[#262838] bg-[#161826] hover:border-violet-400"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 truncate">
                          <Server size={14} className="text-violet-400 shrink-0" />
                          <span className="truncate font-mono text-xs font-bold text-white" title={c.name}>
                            {c.name}
                          </span>
                        </div>
                        {c.is_new && (
                          <span className="rounded bg-amber-400 px-1 py-0.5 text-[9px] font-black text-black uppercase">
                            NEW
                          </span>
                        )}
                      </div>
                      <div className="mt-2 flex items-center justify-between text-[11px] font-mono text-[#cbd5e1]">
                        <span>{(c.requests || 0).toLocaleString()} {t("reqs", "yêu cầu")}</span>
                        <span className={c.errors > 0 ? "text-rose-400 font-bold" : "text-emerald-400"}>
                          {c.errors > 0 ? `${c.errors} ${t("err", "lỗi")}` : `0 ${t("err", "lỗi")}`}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Column 3: TARGET SERVICES & EXPANDABLE OPERATIONS */}
              <div className="space-y-3">
                <div className="text-center">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">
                    {t("Target Services")} & {t("Operations")} ({targets.length})
                  </span>
                </div>
                <div className="space-y-2.5 max-h-[500px] overflow-y-auto scrollbar pr-1">
                  {targets.map((tItem) => {
                    const isExpanded = expandedTarget === tItem.name;
                    const ops = targetOperations[tItem.name] || [];
                    return (
                      <div key={tItem.id} className="space-y-1">
                        <div
                          onClick={() => setExpandedTarget(isExpanded ? null : tItem.name)}
                          className={`cursor-pointer rounded-xl border p-3 transition ${
                            tItem.is_new
                              ? "border-rose-500 bg-rose-500/15"
                              : isExpanded
                              ? "border-cyan-500 bg-cyan-500/15"
                              : "border-[#262838] bg-[#161826] hover:border-cyan-400"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 truncate">
                              {isExpanded ? (
                                <ChevronDown size={14} className="text-cyan-300 shrink-0" />
                              ) : (
                                <ChevronRight size={14} className="text-cyan-300 shrink-0" />
                              )}
                              <span className="truncate font-mono text-xs font-bold text-white" title={tItem.name}>
                                {tItem.name}
                              </span>
                            </div>
                            {tItem.is_new && (
                              <span className="rounded bg-rose-400 px-1 py-0.5 text-[9px] font-black text-white uppercase">
                                NEW
                              </span>
                            )}
                          </div>
                          <div className="mt-2 flex items-center justify-between text-[11px] font-mono text-[#cbd5e1]">
                            <span>{(tItem.requests || 0).toLocaleString()} {t("reqs", "yêu cầu")}</span>
                            <span className="text-cyan-300 font-bold">{ops.length} {t("ops", "thao tác")}</span>
                          </div>
                        </div>

                        {/* Expanded Operations Tree */}
                        {isExpanded && (
                          <div className="ml-4 space-y-1 border-l-2 border-cyan-400/40 pl-3 pt-1">
                            {ops.length === 0 ? (
                              <div className="text-[11px] text-[#cbd5e1] italic py-1">{t("No operations recorded", "Không có thao tác nào")}</div>
                            ) : (
                              ops.map((op, idx) => (
                                <div
                                  key={idx}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSelectedEdge({
                                      caller: "direct/gateway",
                                      target: tItem.name,
                                      operation: op.operation,
                                      requests: op.requests,
                                      errors: op.errors,
                                      error_rate: op.error_rate,
                                      p95: op.p95,
                                      first_seen: op.first_seen,
                                      last_seen: op.last_seen,
                                      is_changed: op.is_new,
                                    });
                                  }}
                                  className="group flex cursor-pointer items-center justify-between rounded-lg border border-white/10 bg-black/40 px-2.5 py-1.5 text-xs transition hover:border-cyan-400 hover:bg-cyan-500/10"
                                >
                                  <span className="font-mono text-[11px] text-[#cbd5e1] group-hover:text-white truncate">
                                    {op.operation}
                                  </span>
                                  <div className="flex items-center gap-1.5 shrink-0">
                                    {op.is_new && (
                                      <span className="rounded bg-amber-400/20 text-amber-300 px-1 text-[8px] font-bold border border-amber-400/40">
                                        NEW
                                      </span>
                                    )}
                                    <span className="font-mono text-[10px] text-cyan-300">{op.requests}</span>
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Edge Inspector Drawer (1 Column width) */}
        <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg flex flex-col justify-between">
          <div>
            <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <Layers size={16} className="text-cyan-400" />
                <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                  {t("Edge Inspector")}
                </h3>
              </div>
              {selectedEdge && (
                <button
                  onClick={() => setSelectedEdge(null)}
                  className="text-xs text-[#cbd5e1] hover:text-white"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {selectedEdge ? (
              <div className="space-y-4 animate-in fade-in duration-150">
                <div className="rounded-xl border border-cyan-400/50 bg-cyan-500/10 p-3.5">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-cyan-300">{t("Inspecting Relationship", "Kiểm tra Mối quan hệ")}</div>
                  <div className="mt-1 flex items-center gap-2 font-mono text-xs font-bold text-white">
                    <span className="text-violet-300 truncate">{selectedEdge.caller}</span>
                    <ArrowRight size={13} className="text-cyan-400 shrink-0" />
                    <span className="text-cyan-300 truncate">{selectedEdge.target}</span>
                  </div>
                  {selectedEdge.operation && (
                    <div className="mt-1.5 font-mono text-[11px] text-emerald-300 truncate">
                      └ {selectedEdge.operation}
                    </div>
                  )}
                </div>

                {/* Edge Metric Badges */}
                <div className="grid grid-cols-2 gap-2.5">
                  <div className="rounded-xl border border-white/10 bg-black/40 p-3">
                    <span className="text-[10px] font-bold uppercase text-[#94a3b8]">{t("Throughput (TPS)")}</span>
                    <div className="font-mono text-base font-bold text-cyan-300">
                      {selectedEdge.rps ?? "—"} tps
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/40 p-3">
                    <span className="text-[10px] font-bold uppercase text-[#94a3b8]">{t("Request Count", "Số Lượt Yêu Cầu")}</span>
                    <div className="font-mono text-base font-bold text-white">
                      {(selectedEdge.requests || 0).toLocaleString()}
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/40 p-3">
                    <span className="text-[10px] font-bold uppercase text-[#94a3b8]">{t("Error Rate")}</span>
                    <div className="font-mono text-base font-bold text-rose-300">
                      {((selectedEdge.error_rate || 0) * 100).toFixed(2)}%
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/40 p-3">
                    <span className="text-[10px] font-bold uppercase text-[#94a3b8]">{t("P95 Latency")}</span>
                    <div className="font-mono text-base font-bold text-amber-300">
                      {selectedEdge.p95 ? `${selectedEdge.p95} ms` : "—"}
                    </div>
                  </div>
                </div>

                {/* Timestamps */}
                <div className="rounded-xl border border-white/10 bg-black/40 p-3 text-xs space-y-1 font-mono">
                  <div className="flex justify-between">
                    <span className="text-[#94a3b8]">{t("First Seen", "Lần đầu thấy")}:</span>
                    <span className="text-[#cbd5e1]">{selectedEdge.first_seen ? new Date(selectedEdge.first_seen).toLocaleString() : t("Unknown", "Không rõ")}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#94a3b8]">{t("Last Seen", "Lần cuối thấy")}:</span>
                    <span className="text-[#cbd5e1]">{selectedEdge.last_seen ? new Date(selectedEdge.last_seen).toLocaleString() : t("Unknown", "Không rõ")}</span>
                  </div>
                  <div className="flex justify-between pt-1 border-t border-white/10">
                    <span className="text-[#94a3b8]">{t("Classification", "Phân loại")}:</span>
                    <span className={`font-bold ${selectedEdge.is_changed ? "text-amber-300" : "text-emerald-300"}`}>
                      {selectedEdge.is_changed ? t("NEW / Changed Path", "Tuyến MỚI / Bị Thay Đổi") : t("Normal Baseline Path", "Tuyến Baseline Chuẩn")}
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-16 text-center text-xs text-[#cbd5e1] space-y-2">
                <Network size={28} className="mx-auto text-white/30" />
                <p>{t("Click on any node or edge to inspect detailed operational metrics")}</p>
              </div>
            )}
          </div>

          <div className="border-t border-white/10 pt-3 text-[11px] text-[#94a3b8]">
            <span>{t("Edges reflect real transactional calls derived from OpenTelemetry spans and APM transaction traces.", "Các liên kết phản ánh dữ liệu giao dịch thực tế từ OpenTelemetry spans và APM traces.")}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
