"""Source snapshotting, bounded evidence assembly, and deterministic facts."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from backend.app.models.investigation import (
    EvidenceBundle,
    EvidenceContext,
    EvidenceItem,
    FindingDimensions,
    FindingRef,
    FindingSnapshot,
    ObservationWindow,
    bounded_json,
    finding_id,
    finding_key,
    validate_text,
)

DAY_MS = 86_400_000
MAX_AGE_MS = 30 * DAY_MS
FOCUS_MAX_MS = 60 * 60_000
SURROUNDING_MAX_MS = 90 * 60_000
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:basic|bearer)\s+)[^\s,;]+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(\b(?:password|passwd|token|secret|nonce|digest)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?is)(<(?P<prefix>[a-z_][\w.-]*):(?:password|nonce|digest)\b[^>]*>).*?(</(?P=prefix):(?:password|nonce|digest)\s*>)"),
)
SAFE_METADATA = frozenset({
    "environment", "service_environment", "identity_source", "auth_result", "auth_evidence",
    "caller_resolution_method", "caller_confidence", "original_client_ip_trusted", "operation_key",
    "source_ip_role", "source_ip_confidence", "detector_signal",
})


class SourceError(ValueError):
    def __init__(self, code: str, message: str = "source cannot be investigated"):
        super().__init__(message)
        self.code = code


def canonical_json(value: Any) -> str:
    def reject(_key: str, item: Any) -> tuple[str, Any]:
        return _key, item
    def check(item: Any, depth: int = 0) -> None:
        if depth > 8:
            raise SourceError("invalid_source", "source JSON is too deeply nested")
        if isinstance(item, float) and not math.isfinite(item):
            raise SourceError("invalid_source", "source contains a non-finite number")
        if isinstance(item, str):
            item.encode("utf-8")
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in item):
                raise SourceError("invalid_source", "source contains control characters")
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise SourceError("invalid_source", "source has a non-string key")
                check(key, depth + 1); check(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child, depth + 1)
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_bounded_json(value: Any, name: str, maximum: int = 64 * 1024) -> Any:
    if value is None:
        return {}
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
        raise SourceError("source_too_large", "{} is too large".format(name))
    try:
        parsed = json.loads(value, object_pairs_hook=_reject_duplicate_keys,
                            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except Exception as exc:
        raise SourceError("invalid_source", "malformed {}".format(name)) from exc
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def redact_text(value: Any, redacted: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value[:512]
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        redacted.append("invalid_utf8")
        return "[redacted]"
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            if pattern.groups >= 2 and pattern.pattern.startswith("(?is"):
                value = pattern.sub(lambda match: match.group(1) + "[redacted]" + match.group(3), value)
            else:
                value = pattern.sub(lambda match: match.group(1) + "[redacted]", value)
            redacted.append("credential_shaped_text")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        redacted.append("control_characters")
        return "[redacted]"
    return value


def _safe_json(value: Any, redacted: list[str], depth: int = 0) -> Any:
    if depth > 5:
        raise SourceError("invalid_source", "source evidence is too deeply nested")
    if isinstance(value, str):
        return redact_text(value, redacted)
    if isinstance(value, dict):
        result = {}
        for key, child in list(value.items())[:64]:
            if not isinstance(key, str) or any(ord(ch) < 32 or ord(ch) == 127 for ch in key):
                continue
            result[key[:128]] = _safe_json(child, redacted, depth + 1)
        return result
    if isinstance(value, list):
        return [_safe_json(child, redacted, depth + 1) for child in value[:32]]
    if isinstance(value, float) and not math.isfinite(value):
        raise SourceError("invalid_source", "non-finite source fact")
    return value


def _safe_metadata(value: dict[str, Any], redacted: list[str]) -> dict[str, Any]:
    def metadata_value(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: metadata_value(item[key]) for key in SAFE_METADATA if key in item}
        if isinstance(item, list):
            return [metadata_value(child) for child in item[:16]]
        return _safe_json(item, redacted)
    return {key: metadata_value(value[key]) for key in sorted(SAFE_METADATA) if key in value}


def _safe_reason(value: Any, redacted: list[str]) -> Any:
    allowed = {"type", "contribution", "baseline", "current", "text", "message", "value", "dimension", "metric"}
    if isinstance(value, list):
        return [_safe_reason(child, redacted) for child in value[:32]]
    if isinstance(value, dict):
        return {key: _safe_reason(child, redacted) for key, child in list(value.items())[:32] if key in allowed}
    return _safe_json(value, redacted)


def _json_column(row: dict[str, Any], column: str, default: Any) -> Any:
    raw = row.get(column)
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        canonical_json(raw)
        return raw
    return parse_bounded_json(raw, column)


def _window_for(kind: str, row: dict[str, Any], limitations: list[str]) -> ObservationWindow | None:
    if kind == "anomaly_event":
        start, end = row.get("first_seen"), row.get("last_seen")
        if start is None or end is None:
            return None
        start, end = int(start), int(end)
        if end <= start:
            limitations.append("equal_observation_bounds_expanded_to_1ms")
            end = start + 1
        return ObservationWindow(start_ms=start, end_ms=end, basis="observed")
    if kind == "principal_change_event":
        if row.get("detected_at") is None:
            limitations.append("change_observation_window_unknown")
            return None
        detected = int(row["detected_at"])
        start = detected - (detected % (15 * 60_000))
        limitations.append("change_window_inferred_from_15m_bucket")
        return ObservationWindow(start_ms=start, end_ms=start + 15 * 60_000, basis="inferred_15m_bucket")
    start, end = row.get("started_at"), row.get("last_seen_at")
    if start is None or end is None:
        return None
    start, end = int(start), int(end)
    if end <= start:
        if end == start:
            limitations.append("equal_observation_bounds_expanded_to_1ms")
        end = start + 1
    if end - start > FOCUS_MAX_MS:
        start = end - FOCUS_MAX_MS
        limitations.append("incident_focus_clipped_to_final_60m")
        return ObservationWindow(start_ms=start, end_ms=end, basis="incident_clipped")
    return ObservationWindow(start_ms=start, end_ms=end, basis="observed")


def _eligibility(kind: str, row: dict[str, Any], now_ms: int, window: ObservationWindow | None) -> tuple[str, str]:
    status = str(row.get("status") or "")
    if kind == "anomaly_event":
        active = {"open", "acknowledged", "investigating"}
        observed = row.get("last_seen") or row.get("detected_at")
        if status not in active:
            return "closed", "finding status is inactive"
    elif kind == "principal_change_event":
        active = {"new", "reviewed"}
        observed = row.get("detected_at")
        if status not in active:
            return "closed", "finding status is inactive"
    else:
        observed = row.get("last_seen_at")
        if row.get("successor_id"):
            return "superseded", "incident has a successor"
        if status not in {"open", "investigating"} or row.get("closed_at") is not None:
            return "closed", "incident is closed or inactive"
    if observed is not None and now_ms - int(observed) > MAX_AGE_MS:
        return "stale", "finding was last observed more than 30 days ago"
    if observed is None or window is None:
        return "insufficient_scope", "finding has no bounded temporal scope"
    if not any(row.get(field) for field in ("principal_name", "principal_id", "target_service", "caller_service", "service")):
        return "insufficient_scope", "finding has no investigation entity scope"
    return "eligible", "finding is active and in scope"


def build_snapshot(ref: FindingRef, source_row: dict[str, Any], captured_at_ms: int | None = None) -> tuple[FindingSnapshot, str, str]:
    """Return snapshot, eligibility status, and fixed reason from a raw source row."""
    if not isinstance(source_row, dict):
        raise SourceError("invalid_source", "source row is not an object")
    raw_captured = captured_at_ms if captured_at_ms is not None else int(time.time() * 1000)
    if isinstance(raw_captured, bool) or not isinstance(raw_captured, int):
        raise SourceError("invalid_source", "invalid capture timestamp")
    captured = raw_captured
    if captured < 0 or captured > 2**64 - 1:
        raise SourceError("invalid_source", "invalid capture timestamp")
    kind, _ = finding_key(ref)
    redacted: list[str] = []
    limitations: list[str] = []
    row = dict(source_row)
    for field in ("detected_at", "first_seen", "last_seen", "first_observed", "started_at", "last_seen_at", "closed_at", "updated_at", "reviewed_at"):
        value = row.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2**64 - 1):
            raise SourceError("invalid_source", "invalid source timestamp")
    for field in ("score", "confidence", "baseline_value", "current_value", "delta_percentage"):
        value = row.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))):
            raise SourceError("invalid_source", "invalid protected numeric fact")
    reason_data = _json_column(row, "reason_json", [] if kind == "anomaly_event" else {})
    metadata = _json_column(row, "metadata_json", {})
    if not isinstance(reason_data, (dict, list)) or not isinstance(metadata, dict):
        raise SourceError("invalid_source", "protected source facts have invalid JSON")
    # This also applies the bounded-depth/non-finite checks before any source
    # material is placed into the immutable snapshot.
    canonical_json(reason_data)
    canonical_json(metadata)

    def text(field: str, maximum: int = 256) -> str | None:
        raw = row.get(field)
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise SourceError("invalid_source", "source text field has an invalid type")
        value = redact_text(raw, redacted)
        return None if value is None else validate_text(value, maximum)

    dimensions = FindingDimensions(
        caller_service=text("caller_service"), target_service=text("target_service"),
        principal_name=text("principal_name") or text("principal_id"), operation=text("operation"),
        source_ip=text("source_ip"), environment=text("environment") or text("service_environment"),
    )
    facts: dict[str, Any]
    protected: dict[str, Any]
    if kind == "anomaly_event":
        protected = {"type": text("anomaly_type"), "severity": text("severity", 64), "score": row.get("score"),
                     "confidence": row.get("confidence"), "baseline": row.get("baseline_value"),
                     "current": row.get("current_value"), "delta_percentage": row.get("delta_percentage"),
                     "reasons": _safe_reason(reason_data, redacted), "metadata": _safe_metadata(metadata, redacted),
                     "status": text("status", 64), "acknowledged": row.get("acknowledged", 0),
                     "first_seen": row.get("first_seen"), "last_seen": row.get("last_seen"),
                     "detected_at": row.get("detected_at")}
    elif kind == "principal_change_event":
        protected = {"fingerprint": text("fingerprint", 512), "type": text("change_type"), "category": text("category", 64), "severity": text("severity", 64),
                     "score": row.get("score"), "detected_at": row.get("detected_at"), "caller_service": dimensions.caller_service,
                     "source_ip": dimensions.source_ip, "target_service": dimensions.target_service, "operation": dimensions.operation,
                     "old_value": text("old_value"), "new_value": text("new_value"), "first_observed": row.get("first_observed"),
                     "reason": _safe_reason(reason_data, redacted), "status": text("status", 64), "updated_at": row.get("updated_at"),
                     "incident_id": text("incident_id"), "principal_id": text("principal_id"), "environment": dimensions.environment,
                     "reliability": text("reliability", 64), "family": text("family", 64)}
    else:
        family_raw = _json_column(row, "family_scores_json", {})
        contributing_raw = _json_column(row, "contributing_event_ids_json", [])
        suppressed_raw = _json_column(row, "suppressed_contributions_json", [])
        if not isinstance(family_raw, dict) or not isinstance(contributing_raw, list) or not isinstance(suppressed_raw, list):
            raise SourceError("invalid_source", "incident protected JSON has an invalid shape")
        family = _safe_json(family_raw, redacted)
        contributing = _safe_json(contributing_raw, redacted)
        suppressed = _safe_json(suppressed_raw, redacted)
        protected = {"principal_id": text("principal_id"), "environment": dimensions.environment,
                     "category": text("category", 64), "scope": text("scope"), "score": row.get("score"),
                     "priority": text("priority", 64), "confidence": row.get("confidence"), "family_scores": family,
                     "contributing_event_ids": sorted([str(item) for item in contributing], key=str),
                     "suppressed_contributions": suppressed, "status": text("status", 64), "closed_at": row.get("closed_at"),
                     "started_at": row.get("started_at"), "last_seen_at": row.get("last_seen_at"),
                     "successor_id": text("successor_id"), "reviewed_at": row.get("reviewed_at"), "updated_at": row.get("updated_at")}
    protected = {key: value for key, value in protected.items() if value is not None}
    window = _window_for(kind, row, limitations)
    status, reason = _eligibility(kind, row, captured, window)
    if window is None:
        limitations.append("observation_window_unknown")
    projection = {"kind": kind, "id": finding_id(ref), "dimensions": dimensions.model_dump(),
                  "facts": protected, "status": protected.get("status"), "updated_at": row.get("updated_at")}
    version = hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()
    successor = None
    if kind == "incident" and row.get("successor_id"):
        successor = {"kind": "incident", "incident_id": str(row["successor_id"])}
    try:
        snapshot = FindingSnapshot(ref=ref, source_version=version, captured_at_ms=captured,
            source_updated_at_ms=int(row["updated_at"]) if row.get("updated_at") is not None else None,
            observation_window=window, dimensions=dimensions, source_facts=protected,
            source_status=str(row.get("status") or "unknown"), successor_ref=successor,
            redacted_fields=sorted(set(redacted)), limitations=sorted(set(limitations)))
    except Exception as exc:
        raise SourceError("invalid_source", "source facts exceed investigation constraints") from exc
    if len(canonical_json(snapshot.model_dump()).encode("utf-8")) > 64 * 1024:
        raise SourceError("source_too_large", "finding snapshot exceeds 64 KiB")
    return snapshot, status, reason


@dataclass(frozen=True)
class Calculation:
    calculation_id: str
    inputs: list[dict[str, Any]]
    formula: str
    interval: dict[str, Any]
    result: Any

    def as_dict(self) -> dict[str, Any]:
        return {"calculation_id": self.calculation_id, "inputs": self.inputs, "formula": self.formula,
                "interval": self.interval, "result": self.result}


def safe_rate(requests: int, seconds: float) -> float | None:
    return None if seconds <= 0 else requests / seconds


def safe_fraction(errors: int, requests: int) -> float | None:
    return None if requests == 0 else errors / requests


class EvidenceAssembler:
    def __init__(self, repository: Any, clock: Any = None):
        self.repository = repository
        self.clock = clock or (lambda: int(time.time() * 1000))

    def context(self, snapshot: FindingSnapshot, deadline_ms: int | None = None) -> EvidenceContext:
        if snapshot.observation_window is None:
            raise SourceError("insufficient_scope", "finding has no bounded observation window")
        start, end = snapshot.observation_window.start_ms, snapshot.observation_window.end_ms
        surrounding_start = max(0, start - 15 * 60_000)
        surrounding_end = min(end + 15 * 60_000, surrounding_start + SURROUNDING_MAX_MS)
        context = EvidenceContext(context_id=uuid4(), finding_version=snapshot.source_version,
            finding_kind=finding_key(snapshot.ref)[0], finding_id=finding_id(snapshot.ref),
            caller_service=snapshot.dimensions.caller_service, target_service=snapshot.dimensions.target_service,
            operation=snapshot.dimensions.operation, source_ip=snapshot.dimensions.source_ip,
            principal_name=snapshot.dimensions.principal_name, environment=snapshot.dimensions.environment,
            start_ms=surrounding_start, end_ms=surrounding_end, focus_start_ms=start, focus_end_ms=end,
            deadline_ms=deadline_ms or self.clock() + 15_000)
        self._register_context(context)
        return context

    def _register_context(self, context: EvidenceContext) -> None:
        register = getattr(self.repository, "register_context", None)
        if register is not None:
            register(context)

    @staticmethod
    def _safe_evidence_value(value: Any, redacted: list[str], depth: int = 0) -> Any:
        if depth > 5:
            raise SourceError("invalid_source", "evidence is too deeply nested")
        if isinstance(value, str):
            return redact_text(value, redacted)
        if isinstance(value, dict):
            return {key[:128]: EvidenceAssembler._safe_evidence_value(child, redacted, depth + 1)
                    for key, child in list(value.items())[:64]
                    if isinstance(key, str) and not any(ord(ch) < 32 or ord(ch) == 127 for ch in key)}
        if isinstance(value, list):
            return [EvidenceAssembler._safe_evidence_value(child, redacted, depth + 1) for child in value[:32]]
        if isinstance(value, float) and not math.isfinite(value):
            raise SourceError("invalid_source", "evidence contains a non-finite number")
        return value

    @staticmethod
    def _evidence_fields(tool: str) -> frozenset[str]:
        return {
            "related_changes": frozenset({"id", "fingerprint", "principal_id", "principal_name", "environment",
                "type", "change_type", "score", "severity", "status", "caller_service", "target_service",
                "operation", "source_ip", "old_value", "new_value", "first_observed", "detected_at", "updated_at",
                "reliability", "reason", "correlation_scope"}),
            "related_traces": frozenset({"event_uid", "trace_id", "span_id", "parent_span_id", "timestamp_ms",
                "principal_name", "environment", "caller_service", "target_service", "operation_key", "operation",
                "http_status", "outcome", "duration_ms", "auth_result", "auth_evidence", "caller_resolution_method",
                "caller_confidence", "original_client_ip_trusted", "source_id"}),
            "window_metrics": frozenset({"bucket_start_ms", "bucket_size_sec", "request_count", "error_count",
                "error_rate_fraction", "rps", "latency_avg_ms", "max_bucket_p95_ms", "observed_bucket_count"}),
            "attached_baseline": frozenset({"dimension", "metric", "value", "median", "mad", "sample_count",
                "hour", "day", "provenance", "reference_as_of_read", "source_version"}),
            "principal_history": frozenset({"day_start", "day_start_ms", "observations", "errors", "unique_callers",
                "unique_sources", "unique_targets", "unique_operations", "scope"}),
            "service_context": frozenset({"caller_service", "target_service", "request_count", "error_rate_fraction",
                "operations", "principals", "scope"}),
            "data_quality": frozenset({"start_ms", "end_ms", "total_spans", "counted_requests", "caller_linkage_rate",
                "username_extraction_rate", "is_collection_gap", "sampling_ratio", "created_at", "scope"}),
        }[tool]

    @classmethod
    def _make_item(cls, tool: str, index: int, row: Any, limitation: str | None) -> EvidenceItem:
        if not isinstance(row, dict):
            row = {"value": row}
        fields = cls._evidence_fields(tool)
        redacted: list[str] = []
        data = cls._safe_evidence_value({key: row[key] for key in fields if key in row}, redacted)
        if redacted:
            data["redaction_applied"] = True
        observed = data.get("timestamp_ms", data.get("bucket_start_ms", data.get("day_start_ms", data.get("day_start"))))
        if observed is not None:
            if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
                raise SourceError("invalid_source", "evidence timestamp is invalid")
        evidence_id = "{}-{}".format(tool, index)
        source_id = data.get("event_uid") or data.get("trace_id") or data.get("id") or evidence_id
        source = {"kind": {"related_traces": "trace", "related_changes": "principal_change_event"}.get(tool, tool),
                  "id": str(source_id), "version": hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest(),
                  "timestamp_ms": observed}
        return EvidenceItem(evidence_id=evidence_id,
            kind={"related_traces": "trace", "related_changes": "change", "window_metrics": "metric",
                  "attached_baseline": "baseline", "principal_history": "history", "service_context": "service_context",
                  "data_quality": "quality"}[tool], observed_at_ms=observed, data=data, source=source,
            limitation=limitation)

    @staticmethod
    def build_calculations(items: list[EvidenceItem], snapshot: FindingSnapshot) -> list[dict[str, Any]]:
        calculations: list[dict[str, Any]] = []
        for item in items:
            if item.kind != "metric":
                continue
            data = item.data
            seconds = data.get("bucket_size_sec")
            requests = data.get("request_count")
            errors = data.get("error_count")
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0 and isinstance(requests, int) and requests >= 0:
                calculations.append(Calculation("calc-rate-" + item.evidence_id, [{"evidence_id": item.evidence_id, "field": "request_count"}],
                    "request_count / bucket_size_sec (calculation-v1)", {"start_ms": item.observed_at_ms, "end_ms": (item.observed_at_ms or 0) + int(seconds * 1000)}, safe_rate(requests, float(seconds))).as_dict())
            if isinstance(requests, int) and requests >= 0 and isinstance(errors, int) and errors >= 0:
                calculations.append(Calculation("calc-error-fraction-" + item.evidence_id,
                    [{"evidence_id": item.evidence_id, "field": "error_count"}, {"evidence_id": item.evidence_id, "field": "request_count"}],
                    "error_count / request_count (calculation-v1)", {"start_ms": item.observed_at_ms, "end_ms": (item.observed_at_ms or 0) + int(float(seconds or 0) * 1000)}, safe_fraction(errors, requests)).as_dict())
            if len(calculations) >= 10:
                return calculations[:10]
        source = snapshot.source_facts
        baseline, current = source.get("baseline"), source.get("current")
        if len(calculations) < 10 and isinstance(baseline, (int, float)) and not isinstance(baseline, bool) and isinstance(current, (int, float)) and not isinstance(current, bool) and math.isfinite(float(baseline)) and math.isfinite(float(current)) and baseline != 0:
            calculations.append(Calculation("calc-source-baseline-ratio", [{"evidence_id": "source-0", "field": "baseline"}, {"evidence_id": "source-0", "field": "current"}],
                "current / baseline (calculation-v1; compatible source units only)", {"start_ms": snapshot.observation_window.start_ms if snapshot.observation_window else None, "end_ms": snapshot.observation_window.end_ms if snapshot.observation_window else None}, current / baseline).as_dict())
        return calculations[:10]

    def assemble(self, snapshot: FindingSnapshot, context: EvidenceContext) -> EvidenceBundle:
        if context.finding_version != snapshot.source_version:
            raise SourceError("source_changed", "evidence context version differs from source")
        self._register_context(context)
        items: list[EvidenceItem] = []
        omissions: list[str] = []
        manifest: list[dict[str, Any]] = []
        related_changes = getattr(self.repository, "related_changes", None)
        calls = (("related_changes", lambda: related_changes(context, snapshot, "focus", 20)) if related_changes else None,
                 ("related_traces", lambda: self.repository.related_traces(context, "focus", 20)),
                 ("window_metrics", lambda: self.repository.window_metrics(context, "focus", 60)),
                 ("attached_baseline", lambda: self.repository.attached_baseline(context, snapshot)),
                 ("principal_history", lambda: self.repository.principal_history(context, 24)),
                 ("service_context", lambda: self.repository.service_context(context, 10)),
                 ("data_quality", lambda: self.repository.data_quality(context, 60)))
        for call_entry in calls:
            if call_entry is None:
                continue
            tool, call = call_entry
            if len(manifest) >= 12:
                omissions.append(tool + ":query_budget")
                continue
            started = self.clock()
            try:
                result = call()
                if isinstance(result, tuple):
                    result, limitation = result
                else:
                    limitation = None
                rows = result if isinstance(result, list) else []
                for index, row in enumerate(rows):
                    if len(items) >= 200:
                        omissions.append(tool + ":item_cap")
                        break
                    items.append(self._make_item(tool, index, row, limitation))
                manifest.append({"tool": tool, "returned": len(rows), "duration_ms": max(0, self.clock() - started), "limitation": limitation})
            except Exception:
                omissions.append(tool + ":unavailable")
                manifest.append({"tool": tool, "returned": 0, "duration_ms": max(0, self.clock() - started), "limitation": "unavailable"})
        if snapshot.source_facts:
            items.insert(0, EvidenceItem(evidence_id="source-0", kind="source", data=snapshot.source_facts, limitation="immutable_source_snapshot"))
        # Fixed pruning order: history, optional context, surrounding samples.
        calculations = self.build_calculations(items, snapshot)
        evidence = {"schema_version": "evidence-v1", "finding_version": snapshot.source_version,
                    "backend": self.repository.backend, "items": [item.model_dump() for item in items],
                    "omissions": omissions, "query_manifest": manifest, "calculations": calculations}
        while len(canonical_json(evidence).encode("utf-8")) > 128 * 1024 and items:
            remove_kind = next((kind for kind in ("history", "service_context", "trace") if any(item.kind == kind for item in items)), None)
            if remove_kind is None:
                break
            for pos in range(len(items) - 1, -1, -1):
                if items[pos].kind == remove_kind:
                    omissions.append(remove_kind + ":pruned"); items.pop(pos); break
            evidence["items"] = [item.model_dump() for item in items]
            evidence["omissions"] = omissions
            evidence["calculations"] = self.build_calculations(items, snapshot)
        if len(canonical_json(evidence).encode("utf-8")) > 128 * 1024:
            raise SourceError("evidence_budget_exceeded", "evidence exceeds the investigation limit")
        digest = hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()
        return EvidenceBundle(finding_version=snapshot.source_version, backend=self.repository.backend,
                              items=items, omissions=omissions, query_manifest=manifest, calculations=evidence["calculations"], digest=digest)

    @staticmethod
    def deterministic_summary(snapshot: FindingSnapshot, bundle: EvidenceBundle, failure_code: str | None = None) -> dict[str, Any]:
        facts = [{"fact_id": item.evidence_id, "kind": item.kind, "data": item.data} for item in bundle.items if item.kind == "source"]
        summary = {"finding": snapshot.ref.model_dump(), "source_version": snapshot.source_version,
                   "source_facts": snapshot.source_facts, "evidence_count": len(bundle.items),
                   "evidence_digest": bundle.digest, "omissions": bundle.omissions, "assessment": "insufficient_evidence" if failure_code else "partially_explained",
                   "observed_facts": facts, "derived_correlations": [], "failure_code": failure_code}
        return bounded_json(summary, 32 * 1024)
