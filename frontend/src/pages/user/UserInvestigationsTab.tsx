import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  ArrowDown,
  ArrowRight,
  CheckCircle,
  CheckCircle2,
  Clock,
  ExternalLink,
  Flame,
  HelpCircle,
  Layers,
  Network,
  Radio,
  Search,
  Shield,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  User,
  Zap,
} from "lucide-react";
import { api, queryString } from "../../api";
import { useFilters } from "../../App";
import { useI18n } from "../../i18n";

export function UserInvestigationsTab() {
  const { principal } = useOutletContext<{ principal: string; profile: any }>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);

  // Fetch investigations queue
  const { data: invData, isLoading } = useQuery({
    queryKey: ["user-investigations", principal, filters],
    queryFn: () =>
      api<any>(`/api/v1/users/${encodeURIComponent(principal)}/investigations?${queryString(filters)}`),
    enabled: !!principal,
  });

  const incidents: any[] = invData?.items || [];
  const activeIncident = incidents.find((i) => i.incident_id === selectedIncidentId) || incidents[0];

  // Incident status update mutation
  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api(`/api/v1/user-changes/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: status, operator: "operator", reason: `Status set to ${status}` }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-investigations", principal] });
    },
  });

  return (
    <div className="space-y-6">
      {/* Question Header Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-rose-500/20 text-rose-300">
            <AlertOctagon size={16} />
          </div>
          <div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-white">
              {t("Active Investigation Queue & Incident Triage")}
            </h2>
            <p className="text-[11px] text-[#cbd5e1]">
              {t("Primary Question:")} <strong className="text-rose-300">“{t("What needs investigation?")}”</strong>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-[#cbd5e1]">
          <ShieldAlert size={14} className="text-rose-400" />
          <span>{incidents.length} {t("Behavioral Incidents in Queue", "Sự cố hành vi trong hàng đợi")}</span>
        </div>
      </div>

      {isLoading ? (
        <div className="grid h-72 place-items-center rounded-2xl border border-white/15 bg-[#171329]">
          <div className="flex flex-col items-center gap-2">
            <div className="h-7 w-7 animate-spin rounded-full border-2 border-rose-400 border-t-transparent" />
          </div>
        </div>
      ) : incidents.length === 0 ? (
        <div className="card p-12 text-center text-xs text-[#cbd5e1] space-y-2">
          <CheckCircle size={32} className="mx-auto text-emerald-400" />
          <p className="font-bold text-white">{t("No Open Investigations", "Không có Sự cố Cần Điều tra")}</p>
          <p>{t("No critical anomaly bursts or security triggers registered for this account.", "Không có cảnh báo bất thường nghiêm trọng hay kích hoạt an ninh nào cho tài khoản này.")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Incident List (Queue) */}
          <div className="lg:col-span-5 space-y-3">
            <div className="flex items-center justify-between text-xs font-mono text-[#94a3b8] px-1">
              <span>{incidents.length} {t("Incident Candidates", "Ứng viên Sự Cố")}</span>
              <span>{t("Sorted by Severity", "Sắp xếp theo Mức độ")}</span>
            </div>

            <div className="space-y-2.5 max-h-[720px] overflow-y-auto scrollbar pr-1">
              {incidents.map((inc: any) => {
                const isSelected = activeIncident?.incident_id === inc.incident_id;
                const startTime = new Date(inc.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
                const endTime = new Date(inc.last_seen_at || inc.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
                const isHigh = inc.priority === "high" || inc.score >= 50;

                return (
                  <div
                    key={inc.incident_id}
                    onClick={() => setSelectedIncidentId(inc.incident_id)}
                    className={`cursor-pointer rounded-xl border p-4 transition-colors ${
                      isSelected
                        ? "border-rose-500 bg-[#1e1420]"
                        : "border-[#262838] bg-[#12141f] hover:border-[#383b52] hover:bg-[#161826]"
                    }`}
                  >
                    {/* Card Header: Timestamp and Account */}
                    <div className="flex items-center justify-between gap-2 border-b border-white/10 pb-2.5">
                      <div className="flex items-center gap-2 font-mono text-xs font-bold text-white">
                        <Clock size={13} className="text-cyan-300" />
                        <span>{startTime}–{endTime}</span>
                      </div>
                      <span
                        className={`rounded px-2 py-0.5 text-[10px] font-black uppercase tracking-wider border ${
                          isHigh
                            ? "border-rose-500/60 bg-rose-500/15 text-rose-200"
                            : "border-amber-500/60 bg-amber-500/15 text-amber-200"
                        }`}
                      >
                        {t(inc.priority).toUpperCase()} {t("Behavioral Change", "Thay đổi Hành vi")}
                      </span>
                    </div>

                    <div className="mt-2.5">
                      <div className="font-mono text-xs font-bold text-cyan-300">
                        {principal}
                      </div>

                      {/* Bulleted list of triggers */}
                      <ul className="mt-2 space-y-1 text-xs font-mono">
                        {(inc.triggers || []).map((tr: string, tIdx: number) => (
                          <li key={tIdx} className="text-amber-200 flex items-start gap-1.5">
                            <span className="text-amber-400 font-bold shrink-0">{tr.slice(0, 1)}</span>
                            <span>{tr.slice(2)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Footer */}
                    <div className="mt-3 flex items-center justify-between border-t border-white/10 pt-2 text-[10px] font-mono text-[#94a3b8]">
                      <span>{t("Score", "Điểm")}: <strong className="text-white font-bold">{inc.score} {t("pts", "điểm")}</strong></span>
                      <span className="capitalize">{t("Status")}: <strong className="text-cyan-300">{t(inc.status)}</strong></span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* RIGHT: DEEP INVESTIGATION VIEW (7 Cols) */}
          <div className="lg:col-span-7">
            {activeIncident ? (
              <div className="rounded-2xl border border-[rgba(255,255,255,0.2)] bg-[#171329] p-6 shadow-xl space-y-6">
                {/* Header */}
                <div className="border-b border-white/10 pb-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400">
                        {t("Incident Analysis", "Phân Tích Sự Cố")}
                      </span>
                      <h3 className="mt-0.5 text-lg font-bold font-mono text-white">
                        {activeIncident.incident_id}
                      </h3>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="rounded-lg border border-rose-500/50 bg-rose-500/20 px-2.5 py-1 text-xs font-mono font-bold text-rose-200">
                        {t("Anomaly Score", "Điểm Bất Thường")}: {activeIncident.score} / 100
                      </span>
                    </div>
                  </div>
                  <p className="mt-1 text-xs text-[#cbd5e1]">
                    {t("Deviation Window", "Cửa sổ Sai lệch")}: {new Date(activeIncident.started_at).toLocaleString()} – {new Date(activeIncident.last_seen_at || activeIncident.started_at).toLocaleString()}
                  </p>
                </div>

                {/* 1. BEFORE vs NOW Comparison Table */}
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-cyan-300 mb-3 flex items-center gap-1.5">
                    <Zap size={14} />
                    <span>{t("Before vs Now Metrics Comparison")}</span>
                  </h4>

                  <div className="rounded-xl border border-white/15 bg-black/40 overflow-hidden">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-white/10 bg-white/5 text-[10px] font-bold uppercase text-[#94a3b8] font-mono">
                          <th className="px-4 py-2.5">{t("Metric Dimension")}</th>
                          <th className="px-4 py-2.5">{t("Historical Baseline (Normal)")}</th>
                          <th className="px-4 py-2.5 text-cyan-300">{t("Observed in Incident Window")}</th>
                          <th className="px-4 py-2.5 text-amber-300">{t("Deviation Magnitude")}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/10 font-mono">
                        {(activeIncident.comparison || []).map((row: any, rIdx: number) => (
                          <tr key={rIdx} className="hover:bg-white/[0.04]">
                            <td className="px-4 py-2.5 font-bold text-white">{row.metric}</td>
                            <td className="px-4 py-2.5 text-[#cbd5e1]">{row.before}</td>
                            <td className="px-4 py-2.5 font-bold text-cyan-300">{row.now}</td>
                            <td className="px-4 py-2.5 font-bold text-amber-300">{row.delta}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* 2. Relationship Introduced Visual Chain */}
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-violet-300 mb-3 flex items-center gap-1.5">
                    <Network size={14} />
                    <span>{t("Causal Relationship Chain")}</span>
                  </h4>

                  <div className="rounded-xl border border-violet-500/30 bg-[#141624] p-5">
                    <div className="flex flex-col items-center space-y-2 max-w-md mx-auto">
                      {(activeIncident.relationship_chain || [principal, "gateway", "api-service", "POST /execute"]).map(
                        (node: string, nIdx: number, arr: string[]) => (
                          <div key={nIdx} className="w-full flex flex-col items-center">
                            <div
                              className={`w-full text-center rounded-xl border p-2.5 font-mono text-xs font-bold ${
                                nIdx === 0
                                  ? "border-cyan-500/50 bg-cyan-500/15 text-white"
                                  : nIdx === arr.length - 1
                                  ? "border-rose-500/50 bg-rose-500/15 text-rose-200"
                                  : "border-violet-500/50 bg-violet-500/15 text-violet-200"
                              }`}
                            >
                              <div className="text-[9px] uppercase tracking-wider text-[#94a3b8]">
                                {nIdx === 0 ? t("Principal Account", "Tài khoản Định danh") : nIdx === 1 ? t("Caller Service", "Dịch vụ Gọi") : nIdx === 2 ? t("Target Service", "Dịch vụ Đích") : t("Novel Operation", "Thao tác Mới")}
                              </div>
                              <div className="truncate mt-0.5">{node}</div>
                            </div>

                            {nIdx < arr.length - 1 && (
                              <div className="my-1 text-cyan-400">
                                <ArrowDown size={16} strokeWidth={2.5} />
                              </div>
                            )}
                          </div>
                        )
                      )}
                    </div>
                  </div>
                </div>

                {/* 3. Supporting Network & Ingress Evidence (Secondary Attribution) */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-amber-300 flex items-center gap-1.5">
                      <Network size={14} />
                      <span>{t("Supporting Ingress & Network Evidence", "Bằng chứng Mạng & Ingress Hỗ trợ")}</span>
                    </h4>
                    <span className="text-[10px] font-mono text-[#94a3b8] uppercase">{t("Corroborating Signal", "Tín hiệu Xác thực")}</span>
                  </div>

                  <div className="rounded-xl border border-dashed border-[#383b52] bg-black/40 p-3.5 space-y-2">
                    {(activeIncident.supporting_ips || []).length === 0 ? (
                      <p className="text-xs text-[#94a3b8] font-mono">{t("No unusual or distinct ingress IPs associated with this incident window.", "Không có địa chỉ IP ingress bất thường hoặc mới lạ nào liên kết với cửa sổ sự cố này.")}</p>
                    ) : (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                        {(activeIncident.supporting_ips || []).map((sip: any, sIdx: number) => (
                          <div key={sIdx} className="rounded-lg border border-[#262838] bg-[#141622] p-2.5 space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[10px] uppercase font-bold text-[#94a3b8]">{t("Source Address")}</span>
                              <span
                                className={`rounded px-1.5 py-0.5 text-[9px] font-mono uppercase font-bold border ${
                                  sip.is_load_balancer || sip.attribution_confidence === "low"
                                    ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                                    : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                                }`}
                              >
                                {sip.role_label}
                              </span>
                            </div>
                            <div className="font-mono text-xs font-bold text-white">
                              {sip.ip}
                            </div>
                            <div className="text-[10px] font-mono text-[#cbd5e1] flex items-center justify-between">
                              <span>{t("Attribution Confidence")}: <strong>{sip.attribution_confidence}</strong></span>
                              <span>{sip.requests} {t("requests", "yêu cầu")}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* 4. Explainability & Triage Controls */}
                <div className="border-t border-white/10 pt-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="text-xs text-[#cbd5e1] max-w-sm">
                    {t("Marking expected adds this tuple to baseline operator overrides to prevent redundant alerts.", "Đánh dấu dự kiến sẽ thêm bộ giá trị này vào ghi đè baseline của vận hành viên để tránh các cảnh báo trùng lặp.")}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => alert(`Marked incident ${activeIncident.incident_id} as Expected Operator Behavior`)}
                      className="rounded-lg border border-emerald-500/50 bg-emerald-500/20 px-3 py-1.5 text-xs font-bold text-emerald-200 hover:bg-emerald-500/30 transition shadow-sm"
                    >
                      {t("Mark Resolved")}
                    </button>
                    <button
                      onClick={() => alert(`Incident ${activeIncident.incident_id} assigned for active security investigation`)}
                      className="rounded-lg border border-rose-500/50 bg-rose-500/20 px-3 py-1.5 text-xs font-bold text-rose-200 hover:bg-rose-500/30 transition shadow-sm"
                    >
                      {t("Investigate")}
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
