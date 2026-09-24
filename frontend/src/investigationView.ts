import type { EntityRef } from "./entityRoutes";
import type { InvestigationRecord, OperatorInvestigationView } from "./investigations";

export type InvestigationView = OperatorInvestigationView;
type InvestigationViewEvidence = OperatorInvestigationView["evidence"][number];

const nonEmpty = (value?: string | null): value is string => Boolean(value?.trim());
type ServiceRef = Extract<EntityRef, { kind: "service" }>;

function serviceEntity(name?: string | null): ServiceRef | undefined {
  return nonEmpty(name) ? { kind: "service", name } : undefined;
}

function formatFact(value: unknown, percent = false): string | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
  if (percent) return `${(value * 100).toFixed(1)}%`;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function observedAt(record: InvestigationRecord): number | undefined {
  const facts = record.snapshot.source_facts;
  const value = facts.detected_at ?? facts.first_seen ?? facts.first_observed ?? facts.started_at;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}

function relationshipEvidence(record: InvestigationRecord): InvestigationViewEvidence | undefined {
  const dimensions = record.snapshot.dimensions;
  const caller = serviceEntity(dimensions.caller_service);
  const target = serviceEntity(dimensions.target_service);
  const user = nonEmpty(dimensions.principal_name)
    ? { kind: "user" as const, principal: dimensions.principal_name }
    : undefined;
  const operation = nonEmpty(dimensions.operation) && target
    ? { kind: "api" as const, service: target.name, operation: dimensions.operation }
    : undefined;
  const relationship: Array<{ text: string; entity: EntityRef }> = [];
  if (caller) relationship.push({ text: dimensions.caller_service!, entity: caller });
  if (target) relationship.push({ text: dimensions.target_service!, entity: target });
  if (operation) relationship.push({ text: dimensions.operation!, entity: operation });

  if (!relationship.length && !user) return undefined;
  const entities: EntityRef[] = [];
  if (caller) entities.push(caller);
  if (target) entities.push(target);
  if (operation) entities.push(operation);
  if (user) entities.push(user);
  return {
    label: user ? "Observed relationship and identity" : "Observed relationship",
    entities,
    relationship,
  };
}

function metricEvidence(record: InvestigationRecord): InvestigationViewEvidence | undefined {
  const facts = record.snapshot.source_facts;
  const baseline = facts.baseline;
  const current = facts.current;
  if (typeof baseline !== "number" || typeof current !== "number") return undefined;
  const type = String(facts.type || "").toLowerCase();
  const isRate = type.includes("error") || type.includes("rate");
  const label = type.includes("latency") ? "P95 latency"
    : type.includes("error") ? "Error rate"
      : type.includes("traffic") || type.includes("spike") || type.includes("drop") ? "TPS"
        : "Observed metric";
  const unit = label === "P95 latency" ? " ms" : "";
  const before = formatFact(baseline, isRate);
  const after = formatFact(current, isRate);
  if (!before || !after) return undefined;
  return { label, value: `${before}${unit} → ${after}${unit}` };
}

function relatedTraceHref(record: InvestigationRecord): string | undefined {
  const dimensions = record.snapshot.dimensions;
  const params = new URLSearchParams();
  if (nonEmpty(dimensions.principal_name)) params.set("principal", dimensions.principal_name);
  if (nonEmpty(dimensions.target_service)) params.set("service", dimensions.target_service);
  if (nonEmpty(dimensions.operation)) params.set("operation", dimensions.operation);
  return params.size ? `/traces?${params.toString()}` : undefined;
}

export function toInvestigationView(
  record: InvestigationRecord,
  fallbackSummary?: string | null,
): InvestigationView {
  const firstHypothesis = record.result?.hypotheses?.[0];
  const dimensions = record.snapshot.dimensions;
  const target = serviceEntity(dimensions.target_service);
  const caller = serviceEntity(dimensions.caller_service);
  const user = nonEmpty(dimensions.principal_name)
    ? { kind: "user" as const, principal: dimensions.principal_name }
    : undefined;
  const api = target && nonEmpty(dimensions.operation)
    ? { kind: "api" as const, service: target.name, operation: dimensions.operation }
    : undefined;
  const evidence = [relationshipEvidence(record), metricEvidence(record)].filter(
    (item): item is InvestigationViewEvidence => Boolean(item),
  );
  const firstSeen = observedAt(record);
  if (firstSeen) evidence.push({
    label: "First observed",
    timestamp_ms: firstSeen,
  });

  const nextActions: InvestigationView["next_actions"] = [];
  if (api) nextActions.push({ label: "View API", entity: api });
  if (target || caller) nextActions.push({ label: "View Service", entity: target || caller });
  if (user) nextActions.push({ label: "View User", entity: user });
  const traces = relatedTraceHref(record);
  if (traces) nextActions.push({ label: "View related traces", href: traces });

  const state = record.state;
  const status: InvestigationView["status"] = state === "succeeded"
    ? "done"
    : state === "failed" || state === "timed_out" || state === "canceled" || state.startsWith("source_")
      ? "failed"
      : "running";
  const fallback = record.result?.assessment === "insufficient_evidence"
    ? "There is not enough evidence to produce a reliable explanation."
    : fallbackSummary || "Investigation completed using the attached telemetry evidence.";
  const limitations = [
    ...(record.snapshot.limitations || []),
    ...(record.result?.missing_evidence || []).map((item) => item.explanation),
  ].filter((item, index, all) => nonEmpty(item) && all.indexOf(item) === index);

  return {
    status,
    summary: firstHypothesis?.statement || fallback,
    confidence: firstHypothesis?.confidence,
    evidence,
    next_actions: nextActions,
    limitations,
  };
}
