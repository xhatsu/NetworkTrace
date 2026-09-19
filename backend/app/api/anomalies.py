"""Expose explainable anomaly lifecycle views without coupling clients to storage details."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.app.security import require_api_key
from backend.app.repositories.anomaly_repository import AnomalyRepository
from backend.app.services.blast_radius import calculate_blast_radius
from backend.app.services.root_cause import determine_probable_origin
from backend.app.repositories.topology_repository import TopologyRepository
from backend.app.repositories.db_context import get_connection

router = APIRouter(prefix="/api/v1", tags=["anomalies"])

class AnomalyStatusUpdate(BaseModel):
    status: Literal["open", "acknowledged", "investigating", "resolved", "suppressed", "ignored"]


def _observed_bounds(item: Dict[str, Any]) -> tuple[int, int, bool]:
    known = item.get("first_seen") is not None and item.get("last_seen") is not None
    start = int(item.get("first_seen") or item.get("detected_at") or 0)
    end = int(item.get("last_seen") or (start + 60_000))
    return start, max(start + 1, end), known


def _enrich_evidence(item: Dict[str, Any], include_traces: bool = False) -> None:
    start_ms, end_ms, window_known = _observed_bounds(item)
    service = item.get("target_service") or item.get("caller_service")
    anomaly_type = (item.get("anomaly_type") or "").lower()
    baseline = None
    current_samples = 0
    persistence = 1 if window_known else 0
    trace_ids: list[str] = []
    if service and window_known:
        dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        with get_connection() as db:
            row = db.execute("""SELECT * FROM baseline_metrics
              WHERE dimension_type='service' AND dimension_key=? AND hour_of_day=? AND day_of_week=?""",
              (service, dt.hour, dt.weekday())).fetchone()
            baseline = dict(row) if row else None
            current_samples = int(db.execute("""SELECT COUNT(DISTINCT bucket_start) FROM metric_buckets
              WHERE bucket_size=300 AND target_service=? AND bucket_start*1000<?
                AND (bucket_start+300)*1000>?""", (service, end_ms, start_ms)).fetchone()[0] or 0)
            rows = db.execute("""SELECT first_seen,last_seen FROM anomaly_events
              WHERE anomaly_type=? AND COALESCE(target_service, '') = COALESCE(?, '')
                AND COALESCE(caller_service, '') = COALESCE(?, '')
                AND COALESCE(principal_name, '') = COALESCE(?, '')
                AND COALESCE(operation, '') = COALESCE(?, '') AND first_seen IS NOT NULL
                AND last_seen IS NOT NULL AND last_seen<=? ORDER BY last_seen DESC LIMIT 50""",
              (item.get("anomaly_type"), item.get("target_service"), item.get("caller_service"),
               item.get("principal_name"), item.get("operation"), end_ms)).fetchall()
            persistence = 0
            cursor = end_ms
            for observed in rows:
                if cursor - int(observed["last_seen"]) > 300_000:
                    break
                persistence += 1
                cursor = int(observed["first_seen"])
            if include_traces:
                trace_ids = [trace[0] for trace in db.execute("""SELECT trace_id FROM traces
                  WHERE target_service=? AND timestamp_ms>=? AND timestamp_ms<?
                  GROUP BY trace_id ORDER BY MAX(timestamp_ms) DESC LIMIT 20""",
                  (service, start_ms, end_ms))]
    baseline_samples = int(baseline.get("sample_count") or 0) if baseline else 0
    mad = 0.0
    if baseline:
        if "latency" in anomaly_type:
            mad = float(baseline.get("latency_p95_mad") or 0)
        elif "error" in anomaly_type:
            mad = float(baseline.get("error_rate_mad") or 0) * 100
        else:
            mad = float(baseline.get("rps_mad") or 0)
    center = item.get("baseline_value")
    item["current_samples"] = current_samples
    item["baseline_samples"] = baseline_samples
    item["persistence_buckets"] = persistence
    item["normal_low"] = max(0.0, round(float(center) - 3 * mad, 2)) if center is not None else None
    item["normal_high"] = round(float(center) + 3 * mad, 2) if center is not None else None
    item["window_source"] = "telemetry" if window_known else "legacy_detection_time"
    if include_traces:
        item["trace_ids"] = trace_ids

def format_anomaly(r: Dict[str, Any]) -> Dict[str, Any]:
    svc = r.get("target_service") or r.get("caller_service") or r.get("principal_name") or r.get("operation") or "Unknown"
    b_val = r.get("baseline_value")
    c_val = r.get("current_value") if r.get("current_value") is not None else 0.0
    anom_type = r.get("anomaly_type") or "anomaly"
    unit = "ms" if "latency" in anom_type.lower() else ("%" if "error" in anom_type.lower() else "tps")
    abs_diff = round(abs(c_val - b_val), 2) if b_val is not None else round(float(c_val), 2)
    pct_change = r.get("delta_percentage")
    if pct_change is None and b_val and b_val > 0:
        pct_change = round(((c_val - b_val) / b_val) * 100, 1)
    elif pct_change is None:
        pct_change = 0.0

    r["entity_id"] = svc
    r["entity_type"] = "service" if r.get("target_service") else ("principal" if r.get("principal_name") else "operation")
    det_ms = r.get("last_seen") or r.get("detected_at") or int(time.time() * 1000)
    r["last_detected_ms"] = det_ms
    r["first_detected_ms"] = r.get("first_seen") or r.get("detected_at") or det_ms
    r["window_start_ms"] = r.get("window_start_ms") or (det_ms - 60000)
    r["window_end_ms"] = r.get("window_end_ms") or det_ms
    r.pop("instance", None)
    r.pop("contributors", None)
    r["trace_ids"] = r.get("trace_ids") or []
    r["percent_change"] = pct_change
    r["absolute_difference"] = abs_diff
    r["unit"] = unit
    meta = r.get("metadata") or {}
    r["occurrences"] = int(meta.get("occurrences", 1)) if isinstance(meta, dict) else 1
    r["duration_mins"] = float(meta.get("duration_mins", 0)) if isinstance(meta, dict) else 0.0
    _enrich_evidence(r)
    r["explanation"] = r["reasons"][0]["text"] if r.get("reasons") and len(r["reasons"]) > 0 and isinstance(r["reasons"][0], dict) and "text" in r["reasons"][0] else anom_type
    return r


def _parse_time_ms(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return int(val) if val > 10_000_000_000 else int(val * 1000)
    if isinstance(val, str):
        val_str = val.strip()
        try:
            num = float(val_str)
            return int(num) if num > 10_000_000_000 else int(num * 1000)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            pass
    return None


@router.get("/anomalies")
async def list_anomalies(
    from_time: Optional[Any] = Query(None, alias="from"),
    to_time: Optional[Any] = Query(None, alias="to"),
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    principal: Optional[str] = None,
    source_ip: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    start_ms = _parse_time_ms(from_time) or _parse_time_ms(start)
    end_ms = _parse_time_ms(to_time) or _parse_time_ms(end)

    repo = AnomalyRepository()
    rows = repo.list_anomalies(start_ms=start_ms, end_ms=end_ms, status=status, severity=severity, service=service, principal=principal, source_ip=source_ip, limit=limit)
    items = [format_anomaly(r) for r in rows]
    return {"items": items, "count": len(items)}

@router.get("/anomalies/{anomaly_id}")
async def get_anomaly_detail(
    anomaly_id: int,
    from_time: Optional[Any] = Query(None, alias="from"),
    to_time: Optional[Any] = Query(None, alias="to"),
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    window: Optional[str] = None,
) -> Dict[str, Any]:
    repo = AnomalyRepository()
    top_repo = TopologyRepository()
    item = repo.get_anomaly(anomaly_id)
    if not item:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    svc = item.get("target_service") or item.get("caller_service")
    observed_start_ms, observed_end_ms, window_known = _observed_bounds(item)

    # Determine query time range: default to 24h horizon to clearly show baseline & trends
    horizon_sec = 86400  # Default 24h
    if window == "1h":
        horizon_sec = 3600
    elif window == "6h":
        horizon_sec = 21600
    elif window == "24h":
        horizon_sec = 86400
    elif window == "7d":
        horizon_sec = 7 * 86400
    elif window is None:
        q_start_ms = _parse_time_ms(from_time) or _parse_time_ms(start)
        q_end_ms = _parse_time_ms(to_time) or _parse_time_ms(end)
        if q_start_ms is not None and q_end_ms is not None and (q_end_ms - q_start_ms) >= 86400_000:
            horizon_sec = max(3600, int((q_end_ms - q_start_ms) / 1000))

    anom_mid_sec = int((observed_start_ms + observed_end_ms) / 2000)
    start_sec = max(0, anom_mid_sec - horizon_sec)
    end_sec = max(start_sec + 60, anom_mid_sec + min(7200, max(1800, int(horizon_sec * 0.1))))

    # Select bucket size: 300s for wide horizons (> 12h), 60s for narrower windows
    chosen_b_size = 300 if (end_sec - start_sec) > 43200 else 60

    from backend.app.repositories.aggregate_repository import AggregateRepository
    agg_repo = AggregateRepository()
    raw_series = agg_repo.query_series(
        start_sec=start_sec,
        end_sec=end_sec,
        bucket_size=chosen_b_size,
        service=svc,
    ) if svc else []

    if not raw_series and svc:
        fallback_b_size = 60 if chosen_b_size == 300 else 300
        raw_series = agg_repo.query_series(
            start_sec=start_sec,
            end_sec=end_sec,
            bucket_size=fallback_b_size,
            service=svc,
        )
        if raw_series:
            chosen_b_size = fallback_b_size

    # Blast-radius and origin calculation
    blast = {}
    origin = {}
    if svc:
        observed_start_sec = int(observed_start_ms / 1000)
        observed_end_sec = max(observed_start_sec + 1, int((observed_end_ms + 999) / 1000))
        blast = calculate_blast_radius(svc, start_sec=max(0, observed_start_sec - 1800), end_sec=observed_end_sec + 1800)
        deps = top_repo.get_service_dependencies(svc, start_sec=max(0, observed_start_sec - 1800), end_sec=observed_end_sec + 1800)
        recent_anomalies = repo.list_anomalies(start_ms=(observed_start_sec - 1800)*1000, end_ms=(observed_end_sec + 1800)*1000, limit=20)
        origin = determine_probable_origin(svc, recent_anomalies, deps)

    b_val = item.get("baseline_value")
    c_val = item.get("current_value") if item.get("current_value") is not None else 0.0
    anom_type = item.get("anomaly_type") or "anomaly"
    unit = "ms" if "latency" in anom_type.lower() else ("%" if "error" in anom_type.lower() else "tps")
    abs_diff = round(abs(c_val - b_val), 2) if b_val is not None else round(float(c_val), 2)
    pct_change = item.get("delta_percentage")
    if pct_change is None and b_val and b_val > 0:
        pct_change = round(((c_val - b_val) / b_val) * 100, 1)

    series = []
    for pt in raw_series:
        b_start = pt.get("bucket_start") or 0
        ts_ms = b_start * 1000 if b_start < 10_000_000_000 else b_start
        reqs = pt.get("requests") or 0
        rps_val = round(reqs / float(chosen_b_size), 3)
        series.append({
            **pt,
            "timestamp_ms": ts_ms,
            "rps": rps_val,
            "tps": rps_val,
            "actual": pt.get("latency_p95") if "latency" in anom_type.lower() else (pt.get("error_rate") * 100 if "error" in anom_type.lower() else rps_val),
            "expected": b_val if b_val is not None else 0.0,
        })

    item["series"] = series
    item["entity_type"] = "service" if svc else "operation"
    item["entity_id"] = svc or item.get("operation") or "Unknown"
    det_ms = item.get("last_seen") or item.get("detected_at") or int(time.time() * 1000)
    item["last_detected_ms"] = det_ms
    item["first_detected_ms"] = item.get("first_seen") or item.get("detected_at") or det_ms
    item["window_start_ms"] = item.get("window_start_ms") or (det_ms - 60000)
    item["window_end_ms"] = item.get("window_end_ms") or det_ms
    item["training_start_ms"] = item.get("training_start_ms") or (det_ms - 86400000)
    item["training_end_ms"] = item.get("training_end_ms") or (det_ms - 60000)
    item.pop("instance", None)
    item.pop("contributors", None)
    item["trace_ids"] = item.get("trace_ids") or []
    item["percent_change"] = pct_change
    item["absolute_difference"] = abs_diff
    item["unit"] = unit
    _enrich_evidence(item, include_traces=True)
    item["rule"] = f"Baseline MAD & rolling statistics ({item.get('anomaly_type')})"
    item["limitations"] = item.get("limitations") or [
        "Inference relies on observed transaction spans and 60s metric bucket rollups.",
        "Baselines update dynamically across rolling 24h & 7d matching minute windows."
    ]
    import json
    reason = item.get("reason_json") or {}
    if isinstance(reason, str):
        try:
            reason = json.loads(reason)
        except Exception:
            reason = {"explanation": reason}
    item["reason_json"] = reason
    if isinstance(reason, list) and len(reason) > 0 and isinstance(reason[0], dict):
        explanation = reason[0].get("text") or reason[0].get("explanation")
    elif isinstance(reason, dict):
        explanation = reason.get("text") or reason.get("explanation")
    else:
        explanation = None
    item["explanation"] = explanation or f"Detected {item.get('anomaly_type')} on {item['entity_id']} with current value {item.get('current_value')} vs baseline {item.get('baseline_value')}."
    if not window_known:
        item["limitations"] = ["Historical record predates telemetry observation-window tracking.", *item["limitations"]]
    item["blast_radius"] = blast
    item["root_cause"] = origin
    return item

@router.patch("/anomalies/{anomaly_id}", dependencies=[Depends(require_api_key)])
async def update_anomaly(anomaly_id: int, body: AnomalyStatusUpdate) -> Dict[str, Any]:
    repo = AnomalyRepository()
    ok = repo.update_status(anomaly_id, body.status)
    if not ok:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return {"id": anomaly_id, "status": body.status}
