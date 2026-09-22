import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Ban,
  RefreshCw,
  HelpCircle,
  FileSearch,
  ArrowRight,
  ShieldAlert,
  ListFilter,
  Check,
  ExternalLink,
} from "lucide-react";
import {
  type FindingRef,
  type FindingKind,
  type InvestigationState,
  type AssessmentConfidence,
  getFindingId,
  isInvestigationTerminal,
  fetchInvestigationSource,
  createInvestigation,
  getInvestigation,
  cancelInvestigation,
  fetchInvestigationHistory,
} from "../investigations";
import { useI18n } from "../i18n";

/**
 * Props for InvestigationPanel.
 * Supports any finding reference (`anomaly_event`, `principal_change_event`, or `incident`).
 * Other finding types are supported as future call sites.
 */
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

  // 1. Fetch Source Snapshot & Eligibility
  const sourceQuery = useQuery({
    queryKey: ["investigation-source", findingRef.kind, findingId],
    queryFn: () => fetchInvestigationSource(findingRef.kind, findingId),
    staleTime: 10_000,
  });

  // Auto-select latest investigation ID if known and none currently active
  useEffect(() => {
    if (!activeInvestigationId && sourceQuery.data?.latest_investigation_id) {
      setActiveInvestigationId(sourceQuery.data.latest_investigation_id);
    }
  }, [activeInvestigationId, sourceQuery.data?.latest_investigation_id]);

  // 2. Fetch Investigation History
  const historyQuery = useQuery({
    queryKey: ["investigation-history", findingRef.kind, findingId],
    queryFn: () => fetchInvestigationHistory(findingRef.kind, findingId, 5),
    staleTime: 5_000,
  });

  // 3. Poll Active Investigation (bounded to 1.5s while non-terminal)
  const investigationQuery = useQuery({
    queryKey: ["investigation", activeInvestigationId],
    queryFn: () => getInvestigation(activeInvestigationId!),
    enabled: Boolean(activeInvestigationId),
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state && !isInvestigationTerminal(state) ? 1500 : false;
    },
  });

  // 4. Start Investigation Mutation
  const startMutation = useMutation({
    mutationFn: async () => {
      const source = sourceQuery.data;
      if (!source?.snapshot?.source_version) {
        throw new Error("Source version is missing. Cannot start investigation.");
      }
      if (source.eligibility?.status !== "eligible") {
        throw new Error(source.eligibility?.reason || "Finding is not eligible for investigation.");
      }
      return createInvestigation({
        finding: findingRef,
        source_version: source.snapshot.source_version,
      });
    },
    onSuccess: (data) => {
      setActiveInvestigationId(data.id);
      queryClient.invalidateQueries({ queryKey: ["investigation", data.id] });
      queryClient.invalidateQueries({ queryKey: ["investigation-history", findingRef.kind, findingId] });
      queryClient.invalidateQueries({ queryKey: ["investigation-source", findingRef.kind, findingId] });
    },
  });

  // 5. Cancel Investigation Mutation
  const cancelMutation = useMutation({
    mutationFn: async () => {
      if (!activeInvestigationId) return;
      return cancelInvestigation(activeInvestigationId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investigation", activeInvestigationId] });
      queryClient.invalidateQueries({ queryKey: ["investigation-history", findingRef.kind, findingId] });
    },
  });

  const sourceData = sourceQuery.data;
  const eligibility = sourceData?.eligibility;
  const sourceSnapshot = sourceData?.snapshot;
  const sourceVersion = sourceSnapshot?.source_version || "";

  const inv = investigationQuery.data;
  const currentState: InvestigationState | undefined = inv?.state;
  const isTerminal = isInvestigationTerminal(currentState);
  const isActive = Boolean(currentState && !isTerminal);

  // Deterministic values: prioritize source_facts / initial props
  const scoreVal = initialScore ?? sourceSnapshot?.source_facts?.score ?? sourceSnapshot?.source_facts?.current_value ?? null;
  const severityVal = (initialSeverity || sourceSnapshot?.source_facts?.severity || "info").toLowerCase();
  const entityVal = initialEntityId || sourceSnapshot?.dimensions?.target_service || sourceSnapshot?.dimensions?.principal_name || findingId;
  const explanationVal = initialExplanation || sourceSnapshot?.source_facts?.explanation || "Deterministic detection trigger on service estate.";

  const isEligible = eligibility?.status === "eligible" && Boolean(sourceVersion);

  return (
    <div
      className={`rounded-xl border border-violet-500/30 bg-[#141624] p-5 shadow-sm ${className}`}
      data-testid="investigation-panel"
    >
      {/* HEADER */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/[0.08] pb-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md border border-violet-500/40 bg-violet-500/20 text-violet-300">
              <Sparkles size={16} />
            </div>
            <h3 className="text-sm font-semibold tracking-wide text-white">
              {t("AI Diagnostic Investigation")}
            </h3>
            <span className="rounded border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-violet-300">
              {t("Existing Finding Only")}
            </span>
          </div>
          <p className="text-xs text-[#c4bdd9] max-w-3xl">
            {t(
              "Investigates an already-detected abnormal finding using attached telemetry evidence. Original finding scores and severity are deterministic and immutable.",
              "Investigates an already-detected abnormal finding using attached telemetry evidence. Original finding scores and severity are deterministic and immutable.",
            )}
          </p>
        </div>

        {/* TOP STATUS & SOURCE VERSION */}
        <div className="flex flex-wrap items-center gap-2">
          {sourceQuery.isLoading ? (
            <span className="inline-flex items-center gap-1.5 rounded border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[11px] text-[#9e96b8]">
              <RefreshCw size={12} className="animate-spin text-violet-400" />
              <span>{t("Checking finding eligibility...")}</span>
            </span>
          ) : sourceQuery.isError ? (
            <span className="inline-flex items-center gap-1 rounded border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[11px] font-medium text-rose-300">
              <XCircle size={12} />
              <span>{sourceQuery.error instanceof Error ? sourceQuery.error.message : t("Error loading finding source")}</span>
            </span>
          ) : eligibility ? (
            <div className="flex items-center gap-2">
              <EligibilityBadge status={eligibility.status} label={t(getEligibilityLabel(eligibility.status))} />
              {sourceVersion && (
                <span
                  className="rounded border border-white/[0.08] bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-[#9e96b8]"
                  title={`Source SHA256: ${sourceVersion}`}
                >
                  {t("Source Version")}: {sourceVersion.slice(0, 10)}…
                </span>
              )}
            </div>
          ) : null}
        </div>
      </div>

      {/* DETERMINISTIC FINDING BASELINE (IMMUTABLE) */}
      <div className="mt-4 rounded-lg border border-[rgba(255,255,255,0.08)] bg-black/20 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-1.5">
            <ShieldAlert size={14} className="text-amber-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[#c4bdd9]">
              {t("Deterministic Finding Baseline (Immutable)")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {scoreVal !== null && (
              <span className="font-mono text-xs font-bold text-white">
                Score: <span className="text-amber-300">{scoreVal}</span>
              </span>
            )}
            <SeverityPill severity={severityVal} />
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs pt-2 border-t border-white/[0.05]">
          <div>
            <span className="text-[10px] uppercase tracking-wider text-[#8b949e]">{t("Target Entity")}:</span>
            <div className="font-mono text-white truncate mt-0.5">{entityVal}</div>
          </div>
          <div className="md:col-span-2">
            <span className="text-[10px] uppercase tracking-wider text-[#8b949e]">{t("Detection Reason")}:</span>
            <div className="text-[#f5f3fa] mt-0.5 line-clamp-2">{explanationVal}</div>
          </div>
        </div>
        <p className="mt-2.5 text-[10px] text-[#8b949e] italic">
          {t(
            "Notice: Scores and rules are computed deterministically. The AI investigator does not recalculate scores or discover new anomalies.",
            "Notice: Scores and rules are computed deterministically. The AI investigator does not recalculate scores or discover new anomalies.",
          )}
        </p>
      </div>

      {/* CONTROLS BAR */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-white/[0.06]">
        <div className="flex flex-wrap items-center gap-2">
          {/* Main Investigate Action */}
          <button
            type="button"
            aria-label={t("Start AI Investigation")}
            disabled={!isEligible || startMutation.isPending || isActive}
            onClick={() => startMutation.mutate()}
            className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-violet-400 ${
              isEligible && !isActive && !startMutation.isPending
                ? "border border-violet-500/60 bg-violet-600/30 text-violet-200 hover:bg-violet-600/50 hover:text-white"
                : "cursor-not-allowed border border-white/10 bg-white/[0.02] text-[#6b6585]"
            }`}
          >
            {startMutation.isPending ? (
              <RefreshCw size={13} className="animate-spin text-violet-300" />
            ) : (
              <Sparkles size={13} className="text-violet-300" />
            )}
            <span>
              {startMutation.isPending
                ? t("Submitting...")
                : inv
                  ? t("Rerun Investigation")
                  : t("Start AI Investigation")}
            </span>
          </button>

          {/* Cancel button while active */}
          {isActive && (
            <button
              type="button"
              aria-label={t("Cancel Investigation")}
              disabled={cancelMutation.isPending || Boolean(inv?.cancel_requested)}
              onClick={() => cancelMutation.mutate()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-1.5 text-xs font-semibold text-rose-300 hover:bg-rose-500/25 focus:outline-none focus:ring-2 focus:ring-rose-400 transition"
            >
              <Ban size={13} />
              <span>
                {cancelMutation.isPending || inv?.cancel_requested
                  ? t("Canceling...")
                  : t("Cancel Investigation")}
              </span>
            </button>
          )}

          {/* Ineligible Explanation */}
          {!isEligible && eligibility && (
            <span className="text-[11px] text-amber-300/90 flex items-center gap-1">
              <AlertTriangle size={12} />
              <span>{eligibility.reason}</span>
            </span>
          )}
        </div>

        {/* History Run Selector */}
        {historyQuery.data?.items && historyQuery.data.items.length > 1 && (
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-[10px] uppercase tracking-wider text-[#8b949e]">
              {t("Past Runs")}:
            </span>
            <select
              aria-label={t("Select past investigation run")}
              value={activeInvestigationId || ""}
              onChange={(e) => setActiveInvestigationId(e.target.value)}
              className="rounded border border-white/10 bg-[#0c0d14] px-2 py-1 font-mono text-[11px] text-[#c4bdd9] focus:outline-none focus:border-violet-400"
            >
              {historyQuery.data.items.map((item, idx) => (
                <option key={item.id} value={item.id}>
                  #{historyQuery.data!.items.length - idx} · {item.state} (
                  {new Date(item.created_at_ms || Date.now()).toLocaleTimeString()})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* START MUTATION ERROR NOTIFICATION */}
      {startMutation.isError && (
        <div className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200">
          <div className="flex items-center gap-2 font-semibold">
            <XCircle size={14} className="text-rose-400" />
            <span>{t("Failed to start investigation")}</span>
          </div>
          <p className="mt-1 font-mono text-[11px]">
            {startMutation.error instanceof Error
              ? startMutation.error.message
              : String(startMutation.error)}
          </p>
        </div>
      )}

      {/* LIVE PROGRESS & STATE (aria-live) */}
      <div aria-live="polite" className="mt-4">
        {isActive && (
          <div className="rounded-lg border border-violet-500/30 bg-violet-950/20 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <RefreshCw size={15} className="animate-spin text-violet-400" />
                <span className="text-xs font-semibold text-violet-200">
                  {t("Investigation In Progress")}:{" "}
                  <span className="font-mono text-violet-300">{currentState}</span>
                </span>
              </div>
              <span className="text-[11px] font-mono text-violet-400/80">
                {t("Polling 1.5s")}
              </span>
            </div>
            <div className="mt-3 grid grid-cols-4 gap-2 text-[10px] font-medium text-[#c4bdd9]">
              <ProgressStep
                step={1}
                label="Queued"
                active={currentState === "queued"}
                done={["assembling", "generating", "validating", "succeeded"].includes(currentState || "")}
              />
              <ProgressStep
                step={2}
                label="Assembling"
                active={currentState === "assembling"}
                done={["generating", "validating", "succeeded"].includes(currentState || "")}
              />
              <ProgressStep
                step={3}
                label="Generating"
                active={currentState === "generating"}
                done={["validating", "succeeded"].includes(currentState || "")}
              />
              <ProgressStep
                step={4}
                label="Validating"
                active={currentState === "validating"}
                done={currentState === "succeeded"}
              />
            </div>
          </div>
        )}

        {/* TERMINAL STATE BANNER (Non-success or Warnings) */}
        {currentState && currentState !== "succeeded" && isTerminal && (
          <div
            className={`rounded-lg border p-4 text-xs ${
              currentState === "canceled"
                ? "border-slate-500/40 bg-slate-800/20 text-slate-300"
                : currentState === "timed_out"
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                  : currentState.startsWith("source_")
                    ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                    : "border-rose-500/40 bg-rose-500/10 text-rose-200"
            }`}
          >
            <div className="flex items-center gap-2 font-bold">
              {currentState === "canceled" ? (
                <Ban size={15} />
              ) : currentState === "timed_out" ? (
                <Clock size={15} />
              ) : (
                <AlertTriangle size={15} />
              )}
              <span className="uppercase tracking-wider">
                {currentState === "canceled"
                  ? t("Investigation Canceled")
                  : currentState === "timed_out"
                    ? t("Investigation Timed Out")
                    : currentState.startsWith("source_")
                      ? t("Finding Outdated / Changed")
                      : t("Investigation Failed")}
              </span>
            </div>
            <p className="mt-1.5 text-[11px] text-[#c4bdd9]">
              {inv?.failure_code ? (
                <span>
                  Reason: <code className="font-mono text-rose-300">{inv.failure_code}</code>
                </span>
              ) : currentState === "canceled" ? (
                t("Investigation was canceled by operator request.")
              ) : currentState.startsWith("source_") ? (
                t("The source finding has changed or closed since the investigation was requested.")
              ) : (
                t("Investigation failed during execution. Check provider configuration or try again.")
              )}
            </p>
          </div>
        )}

        {/* SOURCE CHECK STALE BANNER */}
        {inv?.source_check && inv.source_check.status !== "current" && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-200">
            <AlertTriangle size={14} className="text-amber-400 shrink-0" />
            <span>
              {t("Notice: Finding was")} <strong>{inv.source_check.status}</strong>{" "}
              {t("after this investigation run. Version:")}{" "}
              <code className="font-mono text-[10px]">
                {inv.source_check.current_version?.slice(0, 12)}…
              </code>
            </span>
          </div>
        )}
      </div>

      {/* STRUCTURED INVESTIGATION RESULTS */}
      {inv?.result && (
        <div className="mt-5 space-y-4 border-t border-white/[0.08] pt-4">
          {/* Assessment Banner */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/[0.08] bg-black/30 p-3.5">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-[#8b949e]">
                {t("Investigation Assessment")}
              </div>
              <div className="mt-1 flex items-center gap-2">
                <AssessmentPill assessment={inv.result.assessment} />
                <span className="text-xs text-[#c4bdd9]">
                  {inv.result.assessment === "explained"
                    ? t("Root cause is sufficiently explained by attached evidence.")
                    : inv.result.assessment === "partially_explained"
                      ? t("Evidence partially supports the hypothesis, but gaps remain.")
                      : t("Insufficient evidence to reliably explain this baseline shift.")}
                </span>
              </div>
            </div>
            {inv.configured_model && (
              <div className="text-right text-[10px] font-mono text-[#8b949e]">
                Model: <span className="text-violet-300">{inv.configured_model}</span>
              </div>
            )}
          </div>

          {/* Hypotheses List */}
          {inv.result.hypotheses && inv.result.hypotheses.length > 0 && (
            <div className="space-y-2.5">
              <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-violet-300">
                <FileSearch size={14} />
                <span>{t("Hypotheses")}</span>
              </div>
              <div className="space-y-2">
                {inv.result.hypotheses.map((hyp) => (
                  <div
                    key={hyp.id}
                    className="rounded-lg border border-violet-500/20 bg-white/[0.02] p-3 text-xs"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium text-[#f5f3fa] leading-relaxed">
                        {hyp.statement}
                      </p>
                      <ConfidenceBadge confidence={hyp.confidence} />
                    </div>

                    {/* Citations & Evidence */}
                    <div className="mt-2.5 flex flex-wrap items-center gap-2 pt-2 border-t border-white/[0.04] text-[11px]">
                      {hyp.supporting_evidence_ids?.length > 0 && (
                        <div className="flex items-center gap-1 flex-wrap">
                          <span className="text-[10px] uppercase font-semibold text-[#8b949e]">
                            {t("Supporting Evidence")}:
                          </span>
                          {hyp.supporting_evidence_ids.map((id) => (
                            <span
                              key={id}
                              className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.2 font-mono text-[10px] text-emerald-300"
                            >
                              {id}
                            </span>
                          ))}
                        </div>
                      )}

                      {hyp.counter_evidence_ids?.length > 0 && (
                        <div className="flex items-center gap-1 flex-wrap">
                          <span className="text-[10px] uppercase font-semibold text-[#8b949e]">
                            {t("Counter Evidence")}:
                          </span>
                          {hyp.counter_evidence_ids.map((id) => (
                            <span
                              key={id}
                              className="rounded border border-rose-500/30 bg-rose-500/10 px-1.5 py-0.2 font-mono text-[10px] text-rose-300"
                            >
                              {id}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Alternative explanations */}
                    {hyp.alternatives?.length > 0 && (
                      <div className="mt-2 text-[11px] text-[#9e96b8]">
                        <span className="font-medium text-[#c4bdd9]">{t("Alternatives")}: </span>
                        {hyp.alternatives.join("; ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Observed Facts & Correlations Citations */}
          {((inv.result.observed_fact_ids && inv.result.observed_fact_ids.length > 0) ||
            (inv.result.correlation_ids && inv.result.correlation_ids.length > 0)) && (
            <div className="rounded-lg border border-white/[0.06] bg-black/20 p-3 text-xs">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-1.5">
                {t("Observed Facts & Correlations")}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {(inv.result.observed_fact_ids || []).map((id) => (
                  <span
                    key={id}
                    className="rounded border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 font-mono text-[10px] text-cyan-300"
                  >
                    Fact: {id}
                  </span>
                ))}
                {(inv.result.correlation_ids || []).map((id) => (
                  <span
                    key={id}
                    className="rounded border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 font-mono text-[10px] text-indigo-300"
                  >
                    Corr: {id}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Missing Evidence & Limitations */}
          {inv.result.missing_evidence && inv.result.missing_evidence.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e]">
                {t("Missing Evidence & Limitations")}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {inv.result.missing_evidence.map((me, idx) => (
                  <div
                    key={idx}
                    className="rounded border border-amber-500/20 bg-amber-500/5 p-2.5 text-xs text-amber-200/90"
                  >
                    <div className="font-mono text-[10px] uppercase font-bold text-amber-400">
                      [{me.code}]
                    </div>
                    <p className="mt-0.5">{me.explanation}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Actionable Recommendations */}
          {inv.result.recommendations && inv.result.recommendations.length > 0 && (
            <div className="space-y-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e]">
                {t("Actionable Recommendations")}
              </div>
              <div className="space-y-1.5">
                {inv.result.recommendations.map((rec, idx) => (
                  <div
                    key={idx}
                    className="flex items-start gap-2.5 rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs"
                  >
                    <span className="mt-0.5 rounded border border-emerald-500/40 bg-emerald-500/20 px-2 py-0.5 font-mono text-[10px] font-bold uppercase text-emerald-300">
                      {rec.action.replaceAll("_", " ")}
                    </span>
                    <div className="space-y-1 flex-1">
                      <p className="text-[#f5f3fa]">{rec.rationale}</p>
                      {rec.evidence_ids?.length > 0 && (
                        <div className="flex items-center gap-1 font-mono text-[10px] text-emerald-400/80">
                          <span>{t("Evidence")}</span>
                          {rec.evidence_ids.join(", ")}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EligibilityBadge({ status, label }: { status: string; label: string }) {
  const isEligible = status === "eligible";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-semibold tracking-wide ${
        isEligible
          ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
          : status === "closed"
            ? "border-slate-500/40 bg-slate-800/30 text-slate-300"
            : status === "stale"
              ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
              : status === "superseded"
                ? "border-purple-500/40 bg-purple-500/15 text-purple-300"
                : "border-rose-500/40 bg-rose-500/15 text-rose-300"
      }`}
    >
      {isEligible ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
      <span>{label}</span>
    </span>
  );
}

function getEligibilityLabel(status: string): string {
  switch (status) {
    case "eligible":
      return "Eligible for Analysis";
    case "closed":
      return "Finding Closed";
    case "stale":
      return "Finding Stale";
    case "superseded":
      return "Finding Superseded";
    case "insufficient_scope":
      return "Insufficient Telemetry Scope";
    case "invalid_source":
      return "Invalid Source";
    default:
      return status;
  }
}

function SeverityPill({ severity }: { severity: string }) {
  const s = severity.toLowerCase();
  const color =
    s === "critical"
      ? "border-rose-500/50 bg-rose-500/20 text-rose-300"
      : s === "high"
        ? "border-amber-500/50 bg-amber-500/20 text-amber-300"
        : s === "medium"
          ? "border-yellow-500/50 bg-yellow-500/20 text-yellow-300"
          : "border-slate-500/50 bg-slate-500/20 text-slate-300";

  return (
    <span className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${color}`}>
      {severity}
    </span>
  );
}

function ProgressStep({
  step,
  label,
  active,
  done,
}: {
  step: number;
  label: string;
  active: boolean;
  done: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-1 rounded border px-2 py-1 transition ${
        active
          ? "border-violet-500 bg-violet-500/20 text-white font-bold"
          : done
            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
            : "border-white/5 bg-white/[0.02] text-[#6b6585]"
      }`}
    >
      <span>{step}.</span>
      <span>{label}</span>
      {done && <Check size={10} className="text-emerald-400 ml-auto" />}
      {active && <RefreshCw size={10} className="animate-spin text-violet-400 ml-auto" />}
    </div>
  );
}

function AssessmentPill({ assessment }: { assessment: string }) {
  const { t } = useI18n();
  if (assessment === "explained") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-emerald-500/50 bg-emerald-500/20 px-2.5 py-0.5 text-xs font-bold uppercase text-emerald-300">
        <CheckCircle2 size={12} />
        <span>{t("Explained")}</span>
      </span>
    );
  }
  if (assessment === "partially_explained") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-amber-500/50 bg-amber-500/20 px-2.5 py-0.5 text-xs font-bold uppercase text-amber-300">
        <AlertTriangle size={12} />
        <span>{t("Partially Explained")}</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded border border-slate-500/50 bg-slate-500/20 px-2.5 py-0.5 text-xs font-bold uppercase text-slate-300">
      <HelpCircle size={12} />
      <span>{t("Insufficient Evidence")}</span>
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: AssessmentConfidence }) {
  const color =
    confidence === "high"
      ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
      : confidence === "medium"
        ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
        : "border-slate-500/40 bg-slate-500/15 text-slate-300";

  return (
    <span
      className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${color}`}
    >
      {confidence} conf
    </span>
  );
}
