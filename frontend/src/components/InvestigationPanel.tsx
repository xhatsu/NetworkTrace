import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, ExternalLink, RefreshCw, Sparkles, XCircle } from "lucide-react";
import { useI18n } from "../i18n";
import {
  cancelInvestigation,
  createInvestigation,
  fetchInvestigationHistory,
  fetchInvestigationSource,
  getFindingId,
  getInvestigation,
  isInvestigationTerminal,
  type FindingRef,
  type InvestigationRecord,
  type InvestigationState,
} from "../investigations";
import { toInvestigationView } from "../investigationView";
import { EntityLink } from "./EntityLink";
import type { EntityRef } from "../entityRoutes";

export interface InvestigationPanelProps {
  findingRef: FindingRef;
  initialScore?: number | null;
  initialSeverity?: string | null;
  initialExplanation?: string | null;
  initialEntityId?: string | null;
  className?: string;
}

export function InvestigationPanel({
  findingRef,
  initialScore,
  initialSeverity,
  initialExplanation,
  initialEntityId,
  className = "",
}: InvestigationPanelProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const findingId = getFindingId(findingRef);
  const [activeInvestigationId, setActiveInvestigationId] = useState<string | null>(null);

  const sourceQuery = useQuery({
    queryKey: ["investigation-source", findingRef.kind, findingId],
    queryFn: () => fetchInvestigationSource(findingRef.kind, findingId),
    staleTime: 10_000,
  });
  useEffect(() => {
    if (!activeInvestigationId && sourceQuery.data?.latest_investigation_id) {
      setActiveInvestigationId(sourceQuery.data.latest_investigation_id);
    }
  }, [activeInvestigationId, sourceQuery.data?.latest_investigation_id]);

  const historyQuery = useQuery({
    queryKey: ["investigation-history", findingRef.kind, findingId],
    queryFn: () => fetchInvestigationHistory(findingRef.kind, findingId, 5),
    staleTime: 5_000,
  });
  const investigationQuery = useQuery({
    queryKey: ["investigation", activeInvestigationId],
    queryFn: () => getInvestigation(activeInvestigationId!),
    enabled: Boolean(activeInvestigationId),
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state && !isInvestigationTerminal(state) ? 1500 : false;
    },
  });

  const startMutation = useMutation({
    mutationFn: async () => {
      const source = sourceQuery.data;
      if (!source?.snapshot?.source_version) throw new Error("Source version is missing.");
      if (source.eligibility?.status !== "eligible") {
        throw new Error(source.eligibility?.reason || "Finding is not eligible for investigation.");
      }
      return createInvestigation({ finding: findingRef, source_version: source.snapshot.source_version });
    },
    onSuccess: (data) => {
      setActiveInvestigationId(data.id);
      queryClient.invalidateQueries({ queryKey: ["investigation", data.id] });
      queryClient.invalidateQueries({ queryKey: ["investigation-history", findingRef.kind, findingId] });
      queryClient.invalidateQueries({ queryKey: ["investigation-source", findingRef.kind, findingId] });
    },
  });
  const cancelMutation = useMutation({
    mutationFn: () => activeInvestigationId ? cancelInvestigation(activeInvestigationId) : Promise.resolve(undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investigation", activeInvestigationId] });
      queryClient.invalidateQueries({ queryKey: ["investigation-history", findingRef.kind, findingId] });
    },
  });

  const source = sourceQuery.data;
  const snapshot = source?.snapshot;
  const eligibility = source?.eligibility;
  const sourceVersion = snapshot?.source_version || "";
  const investigation = investigationQuery.data;
  const currentState: InvestigationState | undefined = investigation?.state;
  const isActive = Boolean(currentState && !isInvestigationTerminal(currentState));
  const eligible = eligibility?.status === "eligible" && Boolean(sourceVersion);
  const view = investigation?.operator_view || (investigation ? toInvestigationView(investigation, initialExplanation) : undefined);
  const score = initialScore ?? snapshot?.source_facts?.score ?? snapshot?.source_facts?.current_value;
  const severity = (initialSeverity || snapshot?.source_facts?.severity || "info").toLowerCase();
  const target = initialEntityId || snapshot?.dimensions?.target_service || snapshot?.dimensions?.principal_name || findingId;

  return (
    <section className={`border border-[#2a2d30] bg-[#111217] p-4 ${className}`} data-testid="investigation-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[#d8d9da]">
            <Sparkles size={15} className="text-[#b877d9]" />
            {t("Investigation", "Điều tra")}
          </h3>
          {isActive ? (
            <p aria-live="polite" className="mt-1 inline-flex items-center gap-1.5 text-xs text-[#b877d9]">
              <RefreshCw size={12} className="animate-spin" />{t("Analyzing…", "Đang phân tích…")}
            </p>
          ) : currentState === "succeeded" ? (
            <p className="mt-1 text-xs text-[#73bf69]">{t("Analysis complete", "Đã phân tích xong")}</p>
          ) : currentState && isInvestigationTerminal(currentState) ? (
            <p className="mt-1 inline-flex items-center gap-1.5 text-xs text-[#ff9830]">
              <AlertTriangle size={12} />{t("Investigation failed", "Điều tra thất bại")}
            </p>
          ) : sourceQuery.isLoading ? (
            <p className="mt-1 text-xs text-[#7b7d80]">{t("Checking investigation availability…", "Đang kiểm tra khả năng điều tra…")}</p>
          ) : (
            <p className="mt-1 text-xs text-[#7b7d80]">{t("Use the attached telemetry evidence to explain this finding.", "Dùng telemetry đã đính kèm để giải thích finding này.")}</p>
          )}
        </div>
        <button
          type="button"
          disabled={!eligible || startMutation.isPending || isActive || sourceQuery.isLoading}
          onClick={() => startMutation.mutate()}
          className="btn h-8 px-3 text-xs disabled:cursor-not-allowed disabled:opacity-50"
        >
          {startMutation.isPending ? <RefreshCw size={12} className="animate-spin" /> : <Sparkles size={12} />}
          {investigation ? t("Run again", "Chạy lại") : t("Investigate", "Điều tra")}
        </button>
      </div>

      {sourceQuery.isError && (
        <p role="alert" className="mt-3 text-xs text-[#f2495c]">
          {sourceQuery.error instanceof Error ? sourceQuery.error.message : t("Could not load investigation source", "Không thể tải nguồn điều tra")}
        </p>
      )}
      {startMutation.isError && (
        <p role="alert" className="mt-3 flex items-start gap-1.5 text-xs text-[#f2495c]">
          <XCircle size={13} className="mt-0.5 shrink-0" />
          {startMutation.error instanceof Error ? startMutation.error.message : t("Failed to start investigation", "Không thể bắt đầu điều tra")}
        </p>
      )}
      {investigationQuery.isError && (
        <p role="alert" className="mt-3 text-xs text-[#f2495c]">{t("Could not load this investigation run.", "Không thể tải lần điều tra này.")}</p>
      )}
      {eligibility && !eligible && (
        <p className="mt-2 text-[11px] text-[#ff9830]">{t("Investigation unavailable", "Không thể điều tra")}: {eligibility.reason}</p>
      )}

      {view?.status === "done" && investigation?.result && (
        <div className="mt-4 grid gap-3">
          <section className="border-l-2 border-[#b877d9] bg-[#181b1f] px-3 py-2.5">
            <h4 className="text-[10px] font-semibold uppercase tracking-wide text-[#a7a9ab]">{t("Likely explanation", "Giải thích có khả năng nhất")}</h4>
            <p className="mt-1 text-sm leading-5 text-[#d8d9da]">{view.summary}</p>
            {view.confidence && <p className="mt-1.5 text-[11px] text-[#7b7d80]">{t("Confidence", "Độ tin cậy")}: <span className="font-semibold capitalize text-[#ff9830]">{t(view.confidence, view.confidence)}</span></p>}
          </section>

          <section>
            <h4 className="text-[10px] font-semibold uppercase tracking-wide text-[#a7a9ab]">{t("Evidence", "Bằng chứng")}</h4>
            {view.evidence.length ? (
              <div className="mt-1 divide-y divide-[#2a2d30] border-y border-[#2a2d30]">
                {view.evidence.map((item, index) => (
                  <div key={`${item.label}-${index}`} className="flex flex-wrap items-center gap-x-2 gap-y-1 py-2 text-xs">
                    <span className="text-[#7b7d80]">{t(item.label, item.label)}:</span>
                    {item.relationship?.map((part, partIndex) => (
                      <span key={`${part.text}-${partIndex}`} className="inline-flex items-center gap-2">
                        {partIndex > 0 && <span aria-hidden="true" className="text-[#7b7d80]">→</span>}
                        {part.entity
                          ? <InvestigationEntity entity={part.entity}>{part.text}</InvestigationEntity>
                          : <span className="font-mono text-[#d8d9da]">{part.text}</span>}
                      </span>
                    ))}
                    {item.value && <span className="font-mono text-[#d8d9da]">{item.value}</span>}
                    {item.timestamp_ms && <span className="font-mono text-[#d8d9da]">{new Date(item.timestamp_ms).toLocaleString()}</span>}
                    {item.entities?.filter((entity) => entity.kind === "user").map((entity) => (
                      <span key={`user-${entity.kind === "user" ? entity.principal : ""}`} className="inline-flex items-center gap-1">
                        <span className="text-[#7b7d80]">{t("User", "User")}:</span>
                        <InvestigationEntity entity={entity}>{entity.kind === "user" ? entity.principal : ""}</InvestigationEntity>
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-1 text-xs text-[#7b7d80]">{t("No structured evidence is available for this run.", "Lần chạy này không có bằng chứng có cấu trúc.")}</p>
            )}
            {view.limitations.length > 0 && (
              <p className="mt-2 text-[11px] text-[#a7a9ab]">{t("Limitations", "Giới hạn")}: {view.limitations.join(" · ")}</p>
            )}
          </section>

          <section>
            <h4 className="text-[10px] font-semibold uppercase tracking-wide text-[#a7a9ab]">{t("Next steps", "Bước tiếp theo")}</h4>
            {view.next_actions.length ? (
              <div className="mt-1 flex flex-wrap gap-2">
                {view.next_actions.map((action, index) => action.entity ? (
                  <EntityLink key={`${action.label}-${index}`} entity={action.entity} className="btn h-7 px-2.5 text-[11px]">
                    {t(action.label, action.label)} <ExternalLink size={11} />
                  </EntityLink>
                ) : action.href ? (
                  <Link key={`${action.label}-${index}`} to={action.href} className="btn h-7 px-2.5 text-[11px]">
                    {t(action.label, action.label)} <ExternalLink size={11} />
                  </Link>
                ) : null)}
              </div>
            ) : (
              <p className="mt-1 text-xs text-[#7b7d80]">{t("No entity destinations are available from this finding.", "Không có entity đích từ finding này.")}</p>
            )}
          </section>
        </div>
      )}

      <details className="mt-4 border-t border-[#2a2d30] pt-3 text-xs">
        <summary className="cursor-pointer select-none text-[#7b7d80] hover:text-[#d8d9da]">{t("Technical details", "Chi tiết kỹ thuật")}</summary>
        <div className="mt-3 space-y-4">
          <TechnicalSource
            findingRef={findingRef}
            findingId={findingId}
            target={target}
            score={score}
            severity={severity}
            initialExplanation={initialExplanation}
            sourceVersion={sourceVersion}
            eligibility={eligibility}
            investigation={investigation}
            currentState={currentState}
            history={historyQuery.data?.items || []}
            activeInvestigationId={activeInvestigationId}
            onSelectRun={setActiveInvestigationId}
            onCancel={() => cancelMutation.mutate()}
            canCancel={isActive}
            cancelPending={cancelMutation.isPending || Boolean(investigation?.cancel_requested)}
            t={t}
          />
        </div>
      </details>
    </section>
  );
}

function TechnicalSource({
  findingRef,
  findingId,
  target,
  score,
  severity,
  initialExplanation,
  sourceVersion,
  eligibility,
  investigation,
  currentState,
  history,
  activeInvestigationId,
  onSelectRun,
  onCancel,
  canCancel,
  cancelPending,
  t,
}: {
  findingRef: FindingRef;
  findingId: string;
  target: string;
  score: unknown;
  severity: string;
  initialExplanation?: string | null;
  sourceVersion: string;
  eligibility?: { status: string; reason: string };
  investigation?: InvestigationRecord;
  currentState?: InvestigationState;
  history: InvestigationRecord[];
  activeInvestigationId: string | null;
  onSelectRun: (id: string) => void;
  onCancel: () => void;
  canCancel: boolean;
  cancelPending: boolean;
  t: (key: string, fallback?: string) => string;
}) {
  const result = investigation?.result;
  return (
    <>
      <div className="grid gap-2 sm:grid-cols-2">
        <TechnicalValue label={t("Finding", "Finding")} value={`${findingRef.kind} · ${findingId}`} />
        <TechnicalValue label={t("Investigation ID", "ID điều tra")} value={investigation?.id || "—"} />
        <TechnicalValue label={t("Internal state", "Trạng thái nội bộ")} value={currentState || "—"} />
        <TechnicalValue label={t("Source version", "Phiên bản nguồn")} value={investigation?.source_version || sourceVersion || "—"} />
        <TechnicalValue label={t("Model", "Model")} value={investigation?.reported_model || investigation?.configured_model || "—"} />
        <TechnicalValue label={t("Provider", "Provider")} value={investigation?.provider || "—"} />
        <TechnicalValue label={t("Target entity", "Entity đích")} value={target} />
        <TechnicalValue label={t("Original score / severity", "Điểm / mức độ gốc")} value={`${score ?? "—"} / ${severity}`} />
        <TechnicalValue label={t("Eligibility", "Điều kiện")} value={`${eligibility?.status || "checking"}${eligibility?.reason ? ` · ${eligibility.reason}` : ""}`} />
        {investigation?.failure_code && <TechnicalValue label={t("Failure code", "Mã lỗi")} value={investigation.failure_code} />}
        {investigation?.source_check && <TechnicalValue label={t("Source check", "Kiểm tra nguồn")} value={`${investigation.source_check.status}${investigation.source_check.current_version ? ` · ${investigation.source_check.current_version}` : ""}`} />}
        {initialExplanation && <TechnicalValue label={t("Deterministic detection reason", "Lý do phát hiện xác định")} value={initialExplanation} />}
      </div>

      {history.length > 1 && (
        <label className="flex flex-wrap items-center gap-2 text-[11px] text-[#a7a9ab]">
          <span>{t("Investigation history", "Lịch sử điều tra")}</span>
          <select
            aria-label={t("Select past investigation run", "Chọn lần điều tra trước")}
            value={activeInvestigationId || ""}
            onChange={(event) => onSelectRun(event.target.value)}
            className="border border-[#34373b] bg-[#0b0c0e] px-2 py-1 font-mono text-[10px] text-[#d8d9da]"
          >
            {history.map((item, index) => (
              <option key={item.id} value={item.id}>{`#${history.length - index} · ${item.state} · ${item.id}`}</option>
            ))}
          </select>
        </label>
      )}
      {canCancel && <button type="button" disabled={cancelPending} onClick={onCancel} className="btn h-7 px-2 text-[10px] disabled:opacity-50">{cancelPending ? t("Cancel requested", "Đã yêu cầu hủy") : t("Cancel investigation", "Hủy điều tra")}</button>}

      {result && (
        <div className="space-y-3 border-t border-[#2a2d30] pt-3">
          <TechnicalValue label={t("Assessment", "Đánh giá")} value={result.assessment} />
          {investigation?.evidence_manifest?.digest && <TechnicalValue label={t("Evidence digest", "Digest bằng chứng")} value={investigation.evidence_manifest.digest} />}
          {result.hypotheses.map((hypothesis) => (
            <div key={hypothesis.id} className="border border-[#2a2d30] p-2.5">
              <div className="font-semibold text-[#d8d9da]">{hypothesis.id} · {hypothesis.confidence}</div>
              <p className="mt-1 text-[#a7a9ab]">{hypothesis.statement}</p>
              <TechnicalList label={t("Supporting evidence IDs", "ID bằng chứng hỗ trợ")} values={hypothesis.supporting_evidence_ids} />
              <TechnicalList label={t("Counter-evidence IDs", "ID bằng chứng đối chiếu")} values={hypothesis.counter_evidence_ids} />
              <TechnicalList label={t("Alternatives", "Giải thích thay thế")} values={hypothesis.alternatives} />
            </div>
          ))}
          <TechnicalList label={t("Observed fact IDs", "ID dữ kiện quan sát")} values={result.observed_fact_ids} />
          <TechnicalList label={t("Correlation IDs", "ID tương quan")} values={result.correlation_ids} />
          {result.missing_evidence.map((item, index) => (
            <div key={`${item.code}-${index}`} className="border border-[#ff9830]/25 bg-[#ff9830]/5 p-2.5 text-[#d8d9da]">
              <span className="font-mono text-[#ff9830]">{item.code}</span> · {item.explanation}
              <TechnicalList label={t("Related evidence IDs", "ID bằng chứng liên quan")} values={item.related_evidence_ids} />
            </div>
          ))}
          {result.recommendations.map((item, index) => (
            <div key={`${item.action}-${index}`} className="border border-[#2a2d30] p-2.5">
              <div className="font-semibold text-[#d8d9da]">{item.action}</div>
              <p className="mt-1 text-[#a7a9ab]">{item.rationale}</p>
              <TechnicalList label={t("Evidence IDs", "ID bằng chứng")} values={item.evidence_ids} />
            </div>
          ))}
        </div>
      )}

      {investigation && (
        <details className="border-t border-[#2a2d30] pt-2">
          <summary className="cursor-pointer text-[10px] text-[#7b7d80]">{t("Snapshot and audit payload", "Snapshot và dữ liệu kiểm toán")}</summary>
          <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all bg-[#0b0c0e] p-2 font-mono text-[9px] leading-4 text-[#a7a9ab]">{JSON.stringify({
            snapshot: investigation.snapshot,
            source_check: investigation.source_check,
            deterministic_summary: investigation.deterministic_summary,
            evidence_manifest: investigation.evidence_manifest,
            metadata: investigation.metadata,
          }, null, 2)}</pre>
        </details>
      )}
    </>
  );
}

function TechnicalValue({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 border border-[#2a2d30] bg-[#0b0c0e] px-2.5 py-2"><div className="text-[9px] uppercase tracking-wide text-[#7b7d80]">{label}</div><div className="mt-1 break-all font-mono text-[10px] text-[#a7a9ab]">{value}</div></div>;
}

function TechnicalList({ label, values }: { label: string; values?: string[] }) {
  if (!values?.length) return null;
  return <div className="mt-2 text-[10px] text-[#7b7d80]"><span className="font-semibold">{label}: </span><span className="break-all font-mono">{values.join(", ")}</span></div>;
}

function InvestigationEntity({ entity, children }: { entity: EntityRef; children: string }) {
  const color = entity.kind === "service" ? "text-[#8db7fa]"
    : entity.kind === "api" ? "text-[#82d5c4]"
      : entity.kind === "user" ? "text-[#d9b4ea]"
        : "text-[#ff9830]";
  return <EntityLink entity={entity} className={`font-mono underline decoration-transparent underline-offset-2 hover:decoration-current ${color}`}>{children}</EntityLink>;
}
