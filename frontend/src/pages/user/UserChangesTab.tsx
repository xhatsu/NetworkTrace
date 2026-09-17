import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  ArrowRight,
  CheckCircle,
  Clock,
  ExternalLink,
  Eye,
  FileQuestion,
  Filter,
  GitCompareArrows,
  Layers,
  Network,
  Shield,
  ShieldAlert,
  Sparkles,
  TrendingDown,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";
import {
  ResponsiveContainer,
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

export function UserChangesTab() {
  const { principal, profile } = useOutletContext<{ principal: string; profile: any }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState<
    "all" | "behavioral" | "network_ip" | "distribution" | "resource" | "relationship"
  >("all");
  const [selectedChange, setSelectedChange] = useState<any | null>(null);

  // Fetch changes list
  const { data: changesData, isLoading } = useQuery({
    queryKey: ["user-changes-tab", principal, filters],
    queryFn: () =>
      api<any>(`/api/v1/user-changes?principal=${encodeURIComponent(principal)}&${queryString(filters)}`),
    enabled: !!principal,
  });

  const rawChanges: any[] = changesData?.items || profile?.changes || [];
  const seenFp = new Set<string>();
  const changes = rawChanges.filter((c) => {
    const key = c.fingerprint || `${c.change_type}|${c.target_service || ""}|${c.operation || ""}|${c.source_ip || ""}|${c.id}`;
    if (seenFp.has(key)) return false;
    seenFp.add(key);
    return true;
  });

  // Review mutation
  const reviewMutation = useMutation({
    mutationFn: ({ changeId, action }: { changeId: number; action: string }) =>
      api(`/api/v1/user-changes/${changeId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, operator: "operator", reason: `Marked as ${action} from dashboard` }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-changes-tab", principal] });
      queryClient.invalidateQueries({ queryKey: ["user-detail", principal] });
    },
  });

  // Calculate Normal vs Current Target Distribution
  const normalTargets: any[] = profile?.normal?.targets || [];
  const currentTargets: any[] = profile?.current?.targets || [];

  const normalMap = new Map<string, number>();
  normalTargets.forEach((t) => normalMap.set(t.value, Math.round(t.share * 100)));

  const currentMap = new Map<string, number>();
  currentTargets.forEach((t) => currentMap.set(t.value, Math.round(t.share * 100)));

  // Combine unique targets
  const allTargetNames = Array.from(new Set([...normalTargets.map((t) => t.value), ...currentTargets.map((t) => t.value)]));

  const distributionComparison = allTargetNames.map((name) => {
    const normalPct = normalMap.get(name) ?? 0;
    const currentPct = currentMap.get(name) ?? 0;
    const isNew = !normalMap.has(name) || normalPct === 0;
    const deltaPct = currentPct - normalPct;
    return {
      name,
      normalPct,
      currentPct,
      isNew,
      deltaPct,
    };
  }).sort((a, b) => b.currentPct - a.currentPct);

  // Filter changes by category and prioritize high-value behavioral novelties over supporting IP
  const filteredChanges = changes
    .filter((c) => {
      const type = c.change_type || "";
      if (categoryFilter === "behavioral") {
        return (
          type.includes("CALLER") ||
          type.includes("TARGET") ||
          type.includes("OPERATION") ||
          type.includes("RELATIONSHIP")
        ) && !type.includes("SOURCE_IP") && !type.includes("IP_CALLER");
      }
      if (categoryFilter === "network_ip") {
        return type.includes("SOURCE_IP") || type.includes("IP_CALLER") || type.includes("DISTRIBUTION_SHIFT");
      }
      if (categoryFilter === "resource") {
        return type.includes("TARGET") || type.includes("OPERATION");
      }
      if (categoryFilter === "relationship") {
        return type.includes("RELATIONSHIP") || type.includes("CALLER") || type.includes("TARGET");
      }
      return true;
    })
    .sort((a, b) => {
      // High-value behavioral novelties remain primary
      const isBehavioralA = ["NEW_CALLER", "NEW_TARGET", "NEW_OPERATION", "NEW_RELATIONSHIP"].includes(a.change_type);
      const isBehavioralB = ["NEW_CALLER", "NEW_TARGET", "NEW_OPERATION", "NEW_RELATIONSHIP"].includes(b.change_type);
      if (isBehavioralA && !isBehavioralB) return -1;
      if (!isBehavioralA && isBehavioralB) return 1;
      return (b.detected_at || 0) - (a.detected_at || 0);
    });

  return (
    <div className="space-y-6">
      {/* Question Header Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-cyan-500/20 text-cyan-300">
            <GitCompareArrows size={16} />
          </div>
          <div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-white">
              {t("Behavioral Drift & Deviation Analysis")}
            </h2>
            <p className="text-[11px] text-[#cbd5e1]">
              {t("Primary Question:")} <strong className="text-cyan-300">“{t("What is different from normal behavior?")}”</strong>
            </p>
          </div>
        </div>

        {/* Category Filter Pills */}
        <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-white/10 bg-black/40 p-0.5 text-xs">
          {[
            { id: "all", label: t("All Changes") },
            { id: "behavioral", label: t("Behavioral Novelties (Caller, Target, Op)", "Sai lệch Hành vi (Nguồn gọi, Đích, Thao tác)") },
            { id: "network_ip", label: t("Supporting Network & IP") },
            { id: "distribution", label: t("Distribution Shifts", "Dịch chuyển Tỷ trọng") },
          ].map((cat) => (
            <button
              key={cat.id}
              onClick={() => setCategoryFilter(cat.id as any)}
              className={`rounded px-2.5 py-1 font-semibold transition ${
                categoryFilter === cat.id
                  ? "bg-cyan-500 text-black font-bold shadow-sm"
                  : "text-[#cbd5e1] hover:text-white"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </div>

      {/* SECTION 1: DISTRIBUTION CHANGES (BEFORE VS AFTER HORIZONTAL BARS) */}
      {(categoryFilter === "all" || categoryFilter === "distribution") && (
        <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-5 shadow-lg">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <Layers size={16} className="text-cyan-400" />
                <span>{t("Before vs Now Distribution")} ({t("Baseline Normal")} vs {t("Current Observed")})</span>
              </h3>
              <p className="text-xs text-[#cbd5e1]">
                {t("Comparison of normal historical target service share vs current distribution share", "So sánh tỷ trọng dịch vụ đích chuẩn lịch sử với tỷ trọng quan sát hiện tại")}
              </p>
            </div>
            <span className="text-xs font-mono font-bold text-cyan-300">
              {distributionComparison.length} {t("Target Services Tracked", "Dịch vụ đích theo dõi")}
            </span>
          </div>

          <div className="space-y-3">
            {distributionComparison.slice(0, 8).map((item) => (
              <div key={item.name} className="rounded-xl border border-white/10 bg-black/30 p-3.5 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-white">{item.name}</span>
                    {item.isNew && (
                      <span className="rounded bg-rose-500 px-1.5 py-0.5 text-[9px] font-black text-white uppercase">
                        {t("NEW TARGET", "ĐÍCH MỚI")}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-xs font-mono">
                    <span className="text-[#94a3b8]">
                      {t("Normal", "Chuẩn")}: <strong className="text-white">{item.normalPct}%</strong>
                    </span>
                    <span className="text-cyan-300">
                      {t("Current", "Hiện tại")}: <strong className="text-cyan-300 font-bold">{item.currentPct}%</strong>
                    </span>
                    <span
                      className={`font-bold ${
                        item.deltaPct > 0 ? "text-amber-400" : item.deltaPct < 0 ? "text-slate-400" : "text-[#cbd5e1]"
                      }`}
                    >
                      {item.deltaPct > 0 ? `+${item.deltaPct}%` : `${item.deltaPct}%`}
                    </span>
                  </div>
                </div>

                {/* Side by side horizontal bars */}
                <div className="grid grid-cols-2 gap-3 pt-1">
                  {/* Normal Bar */}
                  <div>
                    <div className="flex justify-between text-[10px] font-mono text-[#94a3b8] mb-1">
                      <span>{t("Baseline Normal")}</span>
                      <span>{item.normalPct}%</span>
                    </div>
                    <div className="h-2.5 w-full rounded-full bg-white/10 overflow-hidden">
                      <div
                        className="h-full bg-violet-400 rounded-full"
                        style={{ width: `${Math.min(100, item.normalPct)}%` }}
                      />
                    </div>
                  </div>

                  {/* Current Bar */}
                  <div>
                    <div className="flex justify-between text-[10px] font-mono text-cyan-300 mb-1">
                      <span>{t("Current Observed")}</span>
                      <span>{item.currentPct}%</span>
                    </div>
                    <div className="h-2.5 w-full rounded-full bg-white/10 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${item.isNew ? "bg-rose-500" : "bg-cyan-500"}`}
                        style={{ width: `${Math.min(100, item.currentPct)}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Changes Timeline by Category */}
      <div className="card p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-white">{t("Explainable Change Timeline")}</h3>
            <p className="text-xs text-[#94a3b8]">{t("Chronological behavioral changes with baseline comparison", "Các sự kiện thay đổi hành vi theo thời gian kèm so sánh với baseline")}</p>
          </div>
        </div>

        {/* Change List */}
        {filteredChanges.length === 0 ? (
          <div className="py-12 text-center text-xs text-[#cbd5e1]">
            {t("No behavioral deviations detected. User operating strictly within baseline.")}
          </div>
        ) : (
          <div className="space-y-3">
            {filteredChanges.map((change) => {
              const isSelected = selectedChange?.id === change.id;
              const reason = change.reason || {};
              return (
                <div
                  key={change.id}
                  className={`rounded-xl border p-4 transition ${
                    isSelected
                      ? "border-cyan-500 bg-[#161a28]"
                      : "border-[#262838] bg-[#10121a] hover:border-[#383b52]"
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        {/* Change Type badge */}
                        <span
                          className={`rounded px-2 py-0.5 text-[10px] font-black uppercase tracking-wider border ${
                            change.change_type === "NEW_CALLER"
                              ? "border-violet-400 bg-violet-500/20 text-violet-200"
                              : change.change_type === "NEW_TARGET"
                              ? "border-cyan-400 bg-cyan-500/20 text-cyan-200"
                              : change.change_type === "NEW_SOURCE_IP"
                              ? "border-amber-400 bg-amber-500/20 text-amber-200"
                              : "border-rose-400 bg-rose-500/20 text-rose-200"
                          }`}
                        >
                          {change.change_type}
                        </span>

                        {/* Severity */}
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase border ${
                            change.severity === "high"
                              ? "border-rose-500/60 bg-rose-500/20 text-rose-300"
                              : change.severity === "medium"
                              ? "border-amber-500/60 bg-amber-500/20 text-amber-300"
                              : "border-emerald-500/60 bg-emerald-500/20 text-emerald-300"
                          }`}
                        >
                          {t(change.severity)} {t("Severity", "mức độ")} (+{change.score} {t("pts", "điểm")})
                        </span>

                        {/* Attribution Confidence Pill for IP changes */}
                        {(change.change_type?.includes("IP") || change.source_ip) && (
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-mono border ${
                              (reason.attribution_confidence === "low" || reason.source_ip_role === "load_balancer")
                                ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                                : "border-cyan-500/40 bg-cyan-500/15 text-cyan-300 font-bold"
                            }`}
                          >
                            {reason.role_label || (reason.source_ip_role === "load_balancer" ? t("Likely load balancer · Low attribution confidence") : t("Source IP", "IP Nguồn"))}
                            {reason.attribution_confidence ? ` · ${reason.attribution_confidence} ${t("conf", "tin cậy")}` : ""}
                          </span>
                        )}

                        {/* Status */}
                        <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-mono text-[#cbd5e1]">
                          {t("Status")}: {t(change.status)}
                        </span>
                      </div>

                      {/* Main summary text */}
                      <div className="font-mono text-sm font-bold text-white">
                        {reason.what_changed || `${change.change_type}: ${change.new_value || change.target_service || ""}`}
                      </div>

                      <p className="text-xs text-[#cbd5e1] max-w-3xl">
                        {reason.compared_with || t("Deviates from established historical behavior")}
                      </p>
                    </div>

                    {/* Right: Timestamp and review action buttons */}
                    <div className="flex flex-col items-end gap-2">
                      <div className="flex items-center gap-1.5 text-xs font-mono text-[#94a3b8]">
                        <Clock size={13} />
                        <span>{new Date(change.detected_at).toLocaleString()}</span>
                      </div>

                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => setSelectedChange(isSelected ? null : change)}
                          className="rounded-lg border border-white/20 bg-white/5 px-2.5 py-1 text-xs font-semibold text-white hover:border-cyan-400 hover:bg-cyan-500/20 transition flex items-center gap-1"
                        >
                          <Eye size={12} />
                          <span>{isSelected ? t("Hide details", "Ẩn chi tiết") : t("Explain", "Giải thích")}</span>
                        </button>
                        <button
                          onClick={() => reviewMutation.mutate({ changeId: change.id, action: "expected" })}
                          className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-1 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/25 transition"
                          title={t("Mark this change as expected behavior", "Đánh dấu thay đổi này là hành vi dự kiến")}
                        >
                          {t("Accept Change")}
                        </button>
                        <button
                          onClick={() => reviewMutation.mutate({ changeId: change.id, action: "investigate" })}
                          className="rounded-lg border border-rose-500/40 bg-rose-500/15 px-2.5 py-1 text-xs font-semibold text-rose-300 hover:bg-rose-500/25 transition"
                          title={t("Flag for security investigation", "Gắn cờ để điều tra an ninh")}
                        >
                          {t("Investigate")}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Expanded 7-Question Explainability Card */}
                  {isSelected && (
                    <div className="mt-4 border-t border-white/10 pt-3.5 space-y-3 animate-in fade-in duration-150">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                        <div className="rounded-lg bg-black/40 p-3 border border-white/10 space-y-1">
                          <span className="text-[10px] font-bold uppercase text-cyan-300">1. {t("What changed compared with normal?")}</span>
                          <p className="text-white font-medium">{reason.what_changed || t("Entity introduced for first time.", "Thực thể xuất hiện lần đầu tiên.")}</p>
                        </div>
                        <div className="rounded-lg bg-black/40 p-3 border border-white/10 space-y-1">
                          <span className="text-[10px] font-bold uppercase text-violet-300">2. {t("Why was this flagged?")}</span>
                          <p className="text-white font-medium">{reason.compared_with || t("Zero historical observations in baseline.", "Không có quan sát nào trong baseline lịch sử.")}</p>
                        </div>
                        <div className="rounded-lg bg-black/40 p-3 border border-white/10 space-y-1">
                          <span className="text-[10px] font-bold uppercase text-emerald-300">3. {t("Where In Estate?", "Xảy ra ở đâu?")}</span>
                          <div className="font-mono text-[11px] text-[#cbd5e1] space-y-0.5">
                            <div>{t("Principal", "Định danh")}: {reason.where?.principal || principal}</div>
                            <div>{t("Callers")}: {reason.where?.caller || change.caller_service || "direct"}</div>
                            <div>{t("Targets")}: {reason.where?.target || change.target_service}</div>
                            <div>{t("Operations")}: {reason.where?.operation || change.operation}</div>
                          </div>
                        </div>
                        <div className="rounded-lg bg-black/40 p-3 border border-white/10 space-y-1">
                          <span className="text-[10px] font-bold uppercase text-amber-300">4. {t("How confident is the detection?")}</span>
                          <div className="font-mono text-[11px] text-[#cbd5e1] space-y-0.5">
                            <div>{t("Method", "Phương pháp")}: {reason.how_reliable?.attribution_method || "trace_linked"}</div>
                            <div>{t("Quality", "Chất lượng")}: {reason.how_reliable?.collection_quality || "healthy"}</div>
                            <div>{t("Readiness", "Độ sẵn sàng")}: {reason.how_reliable?.baseline_readiness || "ready"}</div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
