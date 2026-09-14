"""Build time-aware median/MAD expectations that resist outliers in live telemetry."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from backend.app.models.baseline import BaselineMetric
from backend.app.repositories.db_context import get_connection
from backend.app.repositories.baseline_repository import BaselineRepository

def median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0

def mad(vals: List[float], med: Optional[float] = None) -> float:
    if not vals:
        return 0.0
    if med is None:
        med = median(vals)
    devs = [abs(x - med) for x in vals]
    return median(devs)

def rebuild_baselines(
    db_path: Optional[str] = None,
    target_services: Optional[List[str]] = None,
) -> int:
    base_repo = BaselineRepository(db_path)

    if target_services is not None and not target_services:
        return 0
    clauses = ["bucket_size = 300"]
    args: List[Any] = []
    if target_services is not None:
        placeholders = ",".join("?" for _ in target_services)
        clauses.append(f"target_service IN ({placeholders})")
        args.extend(target_services)

    with get_connection(db_path) as db:
        # We compute baselines over 5-minute buckets (bucket_size = 300)
        rows = db.execute("""
            SELECT
              bucket_start,
              target_service,
              caller_service,
              principal_name,
              operation,
              request_count,
              error_count,
              latency_p50,
              latency_p95
            FROM metric_buckets FINAL
            WHERE """ + " AND ".join(clauses), args).fetchall()

    # Dimensions to track:
    # 1. 'service': target_service
    # 2. 'caller_target': caller_service + '->' + target_service
    # 3. 'target_operation': target_service + '->' + operation
    # 4. 'principal_target': principal_name + '->' + target_service

    groups: Dict[tuple, Dict[str, List[float]]] = {}

    # Service detectors compare one service-wide aggregate per 5-minute window.
    # Build historical samples at that same grain before computing medians/MAD.
    service_windows: Dict[tuple[str, int], Dict[str, float]] = {}
    for r in rows:
        key = (r["target_service"], r["bucket_start"])
        sample = service_windows.setdefault(key, {"requests": 0.0, "errors": 0.0, "p50": 0.0, "p95": 0.0})
        sample["requests"] += r["request_count"] or 0
        sample["errors"] += r["error_count"] or 0
        sample["p50"] = max(sample["p50"], r["latency_p50"] or 0.0)
        sample["p95"] = max(sample["p95"], r["latency_p95"] or 0.0)

    for (service, bucket_start), sample in service_windows.items():
        dt = datetime.fromtimestamp(bucket_start, tz=timezone.utc)
        key = ("service", service, dt.hour, dt.weekday())
        vals = groups.setdefault(key, {"rps": [], "p50": [], "p95": [], "error_rate": []})
        vals["rps"].append(sample["requests"] / 300.0)
        vals["p50"].append(sample["p50"])
        vals["p95"].append(sample["p95"])
        vals["error_rate"].append(sample["errors"] / max(1.0, sample["requests"]))

    for r in rows:
        dt = datetime.fromtimestamp(r["bucket_start"], tz=timezone.utc)
        hod = dt.hour
        dow = dt.weekday()

        rps = (r["request_count"] or 0) / 300.0
        err_rate = (r["error_count"] or 0) * 1.0 / max(1, r["request_count"] or 0)
        p50 = r["latency_p50"] or 0.0
        p95 = r["latency_p95"] or 0.0

        dims = [
            ("caller_target", f"{r['caller_service']}->{r['target_service']}" if r["caller_service"] else None),
            ("target_operation", f"{r['target_service']}->{r['operation']}"),
            ("principal_target", f"{r['principal_name']}->{r['target_service']}" if r["principal_name"] else None)
        ]

        for dtype, dkey in dims:
            if not dkey:
                continue
            key = (dtype, dkey, hod, dow)
            if key not in groups:
                groups[key] = {"rps": [], "p50": [], "p95": [], "error_rate": []}
            groups[key]["rps"].append(rps)
            groups[key]["p50"].append(p50)
            groups[key]["p95"].append(p95)
            groups[key]["error_rate"].append(err_rate)

    baselines: List[BaselineMetric] = []
    for (dtype, dkey, hod, dow), vals in groups.items():
        rps_med = median(vals["rps"])
        rps_m = mad(vals["rps"], rps_med)
        p50_med = median(vals["p50"])
        p95_med = median(vals["p95"])
        p95_m = mad(vals["p95"], p95_med)
        err_med = median(vals["error_rate"])
        err_m = mad(vals["error_rate"], err_med)

        baselines.append(BaselineMetric(
            dimension_type=dtype,
            dimension_key=dkey,
            hour_of_day=hod,
            day_of_week=dow,
            sample_count=len(vals["rps"]),
            rps_median=round(rps_med, 4),
            rps_mad=round(rps_m, 4),
            latency_p50_median=round(p50_med, 2),
            latency_p95_median=round(p95_med, 2),
            latency_p95_mad=round(p95_m, 2),
            error_rate_median=round(err_med, 4),
            error_rate_mad=round(err_m, 4)
        ))

    base_repo.save_baselines(baselines)
    return len(baselines)
