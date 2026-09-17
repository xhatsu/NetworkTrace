import { api } from "./api";

export type FindingKind = "anomaly_event" | "principal_change_event" | "incident";

export type FindingRef =
  | { kind: "anomaly_event"; anomaly_event_id: string }
  | { kind: "principal_change_event"; principal_change_event_id: string }
  | { kind: "incident"; incident_id: string };

export function getFindingId(ref: FindingRef): string {
  if (ref.kind === "anomaly_event") return ref.anomaly_event_id;
  if (ref.kind === "principal_change_event") return ref.principal_change_event_id;
  return ref.incident_id;
}

export type SourceEligibilityStatus =
  | "eligible"
  | "closed"
  | "stale"
  | "superseded"
  | "insufficient_scope"
  | "invalid_source";

export type SourceEligibility = {
  status: SourceEligibilityStatus;
  reason: string;
};

export type FindingDimensions = {
  caller_service?: string | null;
  target_service?: string | null;
  principal_name?: string | null;
  operation?: string | null;
  source_ip?: string | null;
  environment?: string | null;
};

export type ObservationWindow = {
  start_ms: number;
  end_ms: number;
  basis: "observed" | "inferred_15m_bucket" | "incident_clipped" | string;
};

export type FindingSnapshot = {
  ref: FindingRef;
  source_version: string;
  snapshot_schema_version?: string;
  captured_at_ms: number;
  source_updated_at_ms?: number | null;
  observation_window?: ObservationWindow | null;
  dimensions: FindingDimensions;
  source_facts: Record<string, any>;
  source_status: string;
  successor_ref?: FindingRef | null;
  redacted_fields?: string[];
  limitations?: string[];
};

export type SourceSnapshotResponse = {
  snapshot: FindingSnapshot;
  eligibility: SourceEligibility;
  latest_investigation_id?: string | null;
};

export type InvestigationState =
  | "queued"
  | "assembling"
  | "generating"
  | "validating"
  | "succeeded"
  | "failed"
  | "timed_out"
  | "canceled"
  | "source_changed"
  | "source_closed"
  | "source_superseded"
  | "source_stale";

export const TERMINAL_INVESTIGATION_STATES: ReadonlySet<InvestigationState> = new Set([
  "succeeded",
  "failed",
  "timed_out",
  "canceled",
  "source_changed",
  "source_closed",
  "source_superseded",
  "source_stale",
]);

export function isInvestigationTerminal(state?: InvestigationState): boolean {
  return state ? TERMINAL_INVESTIGATION_STATES.has(state) : false;
}

export type AssessmentConfidence = "low" | "medium" | "high";

export type Hypothesis = {
  id: string;
  statement: string;
  confidence: AssessmentConfidence;
  supporting_evidence_ids: string[];
  alternatives: string[];
  counter_evidence_ids: string[];
};

export type MissingEvidence = {
  code: string;
  explanation: string;
  related_evidence_ids: string[];
};

export type Recommendation = {
  action: string;
  evidence_ids: string[];
  rationale: string;
};

export type InvestigationAssessment =
  | "explained"
  | "partially_explained"
  | "insufficient_evidence";

export type InvestigationResult = {
  schema_version?: string;
  assessment: InvestigationAssessment;
  observed_fact_ids?: string[];
  observed_facts?: Array<Record<string, any>>;
  correlation_ids?: string[];
  derived_correlations?: Array<Record<string, any>>;
  hypotheses: Hypothesis[];
  missing_evidence: MissingEvidence[];
  recommendations: Recommendation[];
};

export type SourceCheck = {
  status: "current" | "changed" | "missing" | "closed" | "superseded" | "stale" | "unknown";
  current_version?: string | null;
  checked_at_ms: number;
};

export type InvestigationRecord = {
  id: string;
  retry_index?: number;
  retry_of?: string | null;
  finding_kind: FindingKind;
  finding_id: string;
  source_version: string;
  snapshot_schema_version?: string;
  prompt_version?: string;
  result_schema_version?: string;
  policy_version?: string;
  provider?: string;
  configured_model?: string;
  reported_model?: string;
  state: InvestigationState;
  state_version?: number;
  cancel_requested?: boolean;
  created_at_ms?: number;
  updated_at_ms?: number;
  started_at_ms?: number | null;
  finished_at_ms?: number | null;
  deadline_ms?: number | null;
  failure_code?: string | null;
  snapshot: FindingSnapshot;
  evidence_manifest?: {
    digest?: string;
    bundle?: Record<string, any>;
  };
  deterministic_summary?: Record<string, any>;
  result?: InvestigationResult | null;
  metadata?: Record<string, any>;
  source_check?: SourceCheck | null;
  effective_status?: string;
};

export type CreateInvestigationPayload = {
  finding: FindingRef;
  source_version: string;
  retry_of?: string | null;
};

export type CreateInvestigationResponse = {
  id: string;
  status: InvestigationState;
  reused: boolean;
  source_version: string;
  status_url: string;
};

export type InvestigationHistoryResponse = {
  items: InvestigationRecord[];
  limit: number;
  finding: { kind: FindingKind; id: string };
};

export async function fetchInvestigationSource(
  kind: FindingKind,
  id: string,
): Promise<SourceSnapshotResponse> {
  const params = new URLSearchParams({ kind, id });
  return api<SourceSnapshotResponse>(`/api/v1/investigations/source?${params.toString()}`);
}

export async function createInvestigation(
  payload: CreateInvestigationPayload,
): Promise<CreateInvestigationResponse> {
  return api<CreateInvestigationResponse>("/api/v1/investigations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getInvestigation(id: string): Promise<InvestigationRecord> {
  return api<InvestigationRecord>(`/api/v1/investigations/${encodeURIComponent(id)}`);
}

export async function cancelInvestigation(
  id: string,
): Promise<{ id: string; status: InvestigationState; cancel_requested: boolean }> {
  return api<{ id: string; status: InvestigationState; cancel_requested: boolean }>(
    `/api/v1/investigations/${encodeURIComponent(id)}/cancel`,
    {
      method: "POST",
    },
  );
}

export async function fetchInvestigationHistory(
  kind: FindingKind,
  id: string,
  limit: number = 5,
): Promise<InvestigationHistoryResponse> {
  const params = new URLSearchParams({ kind, id, limit: String(limit) });
  return api<InvestigationHistoryResponse>(`/api/v1/investigations?${params.toString()}`);
}
