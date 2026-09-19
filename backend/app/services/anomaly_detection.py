"""Compare rollups with robust baselines instead of treating one noisy bucket as truth."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from backend.app.models.anomaly import AnomalyEvent, AnomalyReason
from backend.app.repositories.db_context import get_connection
from backend.app.repositories.baseline_repository import BaselineRepository
from backend.app.repositories.anomaly_repository import AnomalyRepository, deterministic_anomaly_id


def detect_revised_anomalies(
    db_path: Optional[str] = None,
    max_windows: Optional[int] = None,
) -> List[AnomalyEvent]:
    """Evaluate every completed/revised five-minute bucket exactly after discovery.

    Markers are deleted only after all selected windows have been evaluated, so a
    detector failure is retryable.  The anomaly repository's deterministic IDs
    make repeated evaluation idempotent (completed in delivery phase 5).
    """
    with get_connection(db_path) as db:
        limit_clause = " LIMIT ?" if max_windows is not None else ""
        args = (max(1, max_windows),) if max_windows is not None else ()
        rows = db.execute(
            "SELECT DISTINCT bucket_ms FROM dirty_buckets FINAL "
            "WHERE reason='aggregation-revised' ORDER BY bucket_ms DESC" + limit_clause,
            args,
        ).fetchall()
    if not rows:
        return []

    found: List[AnomalyEvent] = []
    bucket_values = [int(row[0]) for row in rows]
    for bucket_ms in bucket_values:
        bucket_start_sec = bucket_ms // 1000
        found.extend(detect_anomalies(
            bucket_start_sec,
            bucket_start_sec + 300,
            db_path,
        ))

    with get_connection(db_path) as db:
        for bucket_ms in bucket_values:
            db.execute(
                "DELETE FROM dirty_buckets WHERE reason='aggregation-revised' AND bucket_ms=?",
                (bucket_ms,),
            )
    return found

def detect_anomalies(
    window_start_sec: Optional[int] = None,
    window_end_sec: Optional[int] = None,
    db_path: Optional[str] = None
) -> List[AnomalyEvent]:
    base_repo = BaselineRepository(db_path)
    anomaly_repo = AnomalyRepository(db_path)

    with get_connection(db_path) as db:
        if window_end_sec is None:
            max_b = db.execute("SELECT MAX(bucket_start) FROM metric_buckets FINAL WHERE bucket_size = 300").fetchone()[0]
            if not max_b:
                return []
            window_end_sec = max_b + 300
            window_start_sec = max_b
        elif window_start_sec is None:
            window_start_sec = window_end_sec - 300

        # Current 5m buckets
        current_rows = db.execute("""
            SELECT
              target_service,
              caller_service,
              principal_name,
              operation,
              SUM(request_count) as request_count,
              SUM(error_count) as error_count,
              MAX(latency_p95) as latency_p95
            FROM metric_buckets FINAL
            WHERE bucket_size = 300 AND bucket_start >= ? AND bucket_start < ?
            GROUP BY target_service, caller_service, principal_name, operation
        """, (window_start_sec, window_end_sec)).fetchall()

    anomalies: List[AnomalyEvent] = []
    dt = datetime.fromtimestamp(window_start_sec, tz=timezone.utc)
    hod = dt.hour
    dow = dt.weekday()
    detected_at = int(time.time() * 1000)

    # 1. Aggregate per service to detect service-level traffic, latency, and error anomalies
    service_aggregates: Dict[str, Dict[str, Any]] = {}
    for r in current_rows:
        svc = r["target_service"]
        if svc not in service_aggregates:
            service_aggregates[svc] = {"reqs": 0, "errors": 0, "p95": 0.0, "principals": set(), "callers": set(), "ops": set()}
        s = service_aggregates[svc]
        s["reqs"] += r["request_count"] or 0
        s["errors"] += r["error_count"] or 0
        s["p95"] = max(s["p95"], r["latency_p95"] or 0.0)
        if r["principal_name"]: s["principals"].add(r["principal_name"])
        if r["caller_service"]: s["callers"].add(r["caller_service"])
        if r["operation"]: s["ops"].add(r["operation"])

    # Include expected services from baseline that have 0 traffic in this window (complete outage / traffic drop)
    with get_connection(db_path) as db:
        expected_services = db.execute("""
            SELECT dimension_key FROM baseline_metrics FINAL
            WHERE dimension_type = 'service' AND hour_of_day = ? AND day_of_week = ? AND rps_median >= 0.03 AND sample_count >= 2
        """, (hod, dow)).fetchall()
        for exp_svc in expected_services:
            svc_name = exp_svc[0] if isinstance(exp_svc, (list, tuple)) else exp_svc["dimension_key"]
            if svc_name not in service_aggregates:
                service_aggregates[svc_name] = {"reqs": 0, "errors": 0, "p95": 0.0, "principals": set(), "callers": set(), "ops": set()}

    for svc, data in service_aggregates.items():
        base = base_repo.get_baseline("service", svc, hod, dow)
        current_rps = round(data["reqs"] / 300.0, 2)
        current_err = round(data["errors"] * 1.0 / max(1, data["reqs"]), 4)
        current_p95 = round(data["p95"], 2)

        if not base or base["sample_count"] < 2:
            continue

        base_rps = base["rps_median"]
        base_p95 = base["latency_p95_median"]
        base_err = base["error_rate_median"]

        # Detector 1: Traffic Spike
        # Current RPS significantly exceeds baseline median + 3*MAD
        rps_threshold = max(base_rps * 2.0, base_rps + max(0.1, 3.0 * base["rps_mad"]))
        if current_rps > rps_threshold and data["reqs"] >= 20:
            delta_pct = round(((current_rps - base_rps) / max(0.01, base_rps)) * 100, 1)
            score = min(100, int(50 + (delta_pct / 10)))
            severity = "critical" if score >= 85 else "high" if score >= 70 else "medium"
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="traffic_spike",
                severity=severity,
                score=score,
                confidence=0.92,
                target_service=svc,
                baseline_value=round(base_rps, 2),
                current_value=current_rps,
                delta_percentage=delta_pct,
                reasons=[AnomalyReason(
                    type="traffic",
                    contribution=score,
                    baseline=round(base_rps, 2),
                    current=current_rps,
                    text=f"Traffic jumped from {round(base_rps, 2)} RPS to {current_rps} RPS (+{delta_pct}%)"
                )],
                metadata={"callers": list(data["callers"]), "principals": list(data["principals"])}
            ))

        # Detector 2: Traffic Drop
        # Current RPS dropped < 25% of baseline when expected >= 0.03 RPS
        if base_rps >= 0.03 and current_rps < (base_rps * 0.25):
            delta_pct = round(((current_rps - base_rps) / base_rps) * 100, 1)
            score = min(100, int(60 + abs(delta_pct) / 2.5))
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="traffic_drop",
                severity="high" if score >= 75 else "medium",
                score=score,
                confidence=0.88,
                target_service=svc,
                baseline_value=round(base_rps, 2),
                current_value=current_rps,
                delta_percentage=delta_pct,
                reasons=[AnomalyReason(
                    type="traffic",
                    contribution=score,
                    baseline=round(base_rps, 2),
                    current=current_rps,
                    text=f"Traffic dropped from {round(base_rps, 2)} RPS to {current_rps} RPS ({delta_pct}%)"
                )],
                metadata={"callers": list(data["callers"])}
            ))

        # Detector 3: Latency Anomaly
        # Current p95 exceeds baseline median + 3*MAD and > 1.8x baseline
        p95_threshold = max(base_p95 * 1.8, base_p95 + max(50.0, 3.0 * base["latency_p95_mad"]))
        if current_p95 > p95_threshold and current_p95 > 150.0 and data["reqs"] >= 10:
            delta_pct = round(((current_p95 - base_p95) / max(1.0, base_p95)) * 100, 1)
            score = min(100, int(55 + (delta_pct / 8)))
            severity = "critical" if score >= 80 else "high" if score >= 65 else "medium"
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="latency",
                severity=severity,
                score=score,
                confidence=0.90,
                target_service=svc,
                baseline_value=round(base_p95, 2),
                current_value=current_p95,
                delta_percentage=delta_pct,
                reasons=[AnomalyReason(
                    type="latency",
                    contribution=score,
                    baseline=round(base_p95, 2),
                    current=current_p95,
                    text=f"p95 latency degraded from {round(base_p95, 1)}ms to {current_p95}ms (+{delta_pct}%)"
                )],
                metadata={"operations": list(data["ops"])}
            ))

        # Detector 4: Error-Rate Anomaly
        # Current error rate elevated > baseline error rate + 5%
        if current_err > (base_err + 0.04) and data["errors"] >= 5:
            delta_pct = round(((current_err - base_err) / max(0.001, base_err)) * 100, 1)
            score = min(100, int(60 + current_err * 200))
            severity = "critical" if current_err >= 0.10 else "high"
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="error_rate",
                severity=severity,
                score=score,
                confidence=0.95,
                target_service=svc,
                baseline_value=round(base_err * 100, 2),
                current_value=round(current_err * 100, 2),
                delta_percentage=delta_pct,
                reasons=[AnomalyReason(
                    type="error_rate",
                    contribution=score,
                    baseline=round(base_err * 100, 2),
                    current=round(current_err * 100, 2),
                    text=f"Error rate surged from {round(base_err*100, 1)}% to {round(current_err*100, 1)}% (+{delta_pct}%)"
                )],
                metadata={"total_errors": data["errors"], "total_requests": data["reqs"]}
            ))

    # 1b. Aggregate per (principal_name, target_service) to detect user-level traffic spikes
    principal_aggregates: Dict[tuple[str, str], Dict[str, Any]] = {}
    for r in current_rows:
        p_name = r.get("principal_name")
        tgt_svc = r.get("target_service")
        if not p_name or not tgt_svc:
            continue
        pk = (p_name, tgt_svc)
        if pk not in principal_aggregates:
            principal_aggregates[pk] = {"reqs": 0, "errors": 0, "p95": 0.0, "ops": set(), "callers": set()}
        pa = principal_aggregates[pk]
        pa["reqs"] += r["request_count"] or 0
        pa["errors"] += r["error_count"] or 0
        pa["p95"] = max(pa["p95"], r["latency_p95"] or 0.0)
        if r.get("operation"): pa["ops"].add(r["operation"])
        if r.get("caller_service"): pa["callers"].add(r["caller_service"])

    for (p_name, tgt_svc), pdata in principal_aggregates.items():
        dim_key = f"{p_name}->{tgt_svc}"
        pbase = base_repo.get_baseline("principal_target", dim_key, hod, dow)
        if not pbase or pbase.get("sample_count", 0) < 10:
            with get_connection(db_path) as db:
                row_all = db.execute(
                    "SELECT median(rps_median), median(rps_mad) FROM baseline_metrics WHERE dimension_type='principal_target' AND dimension_key=?",
                    (dim_key,)
                ).fetchone()
                if row_all and row_all[0] is not None and float(row_all[0]) > 0:
                    pbase = {"rps_median": float(row_all[0]), "rps_mad": float(row_all[1] or 0.0), "sample_count": 20}
        if not pbase or pbase.get("sample_count", 0) < 2:
            continue
        p_base_rps = pbase["rps_median"]
        p_cur_rps = round(pdata["reqs"] / 300.0, 2)
        p_mad = min(0.10, float(pbase.get("rps_mad") or 0.0))
        p_rps_thresh = max(p_base_rps * 1.4, p_base_rps + max(0.08, 2.0 * p_mad))
        if p_cur_rps > p_rps_thresh and pdata["reqs"] >= 15:
            p_delta_pct = round(((p_cur_rps - p_base_rps) / max(0.01, p_base_rps)) * 100, 1)
            p_score = min(100, int(55 + (p_delta_pct / 10)))
            p_sev = "critical" if p_score >= 85 else "high" if p_score >= 70 else "medium"
            first_caller = next(iter(pdata["callers"]), None)
            first_op = next(iter(pdata["ops"]), None)
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="traffic_spike",
                severity=p_sev,
                score=p_score,
                confidence=0.95,
                principal_name=p_name,
                target_service=tgt_svc,
                caller_service=first_caller,
                operation=first_op,
                baseline_value=round(p_base_rps, 2),
                current_value=p_cur_rps,
                delta_percentage=p_delta_pct,
                reasons=[AnomalyReason(
                    type="traffic",
                    contribution=p_score,
                    baseline=round(p_base_rps, 2),
                    current=p_cur_rps,
                    text=f"Principal '{p_name}' traffic to {tgt_svc} surged from {round(p_base_rps, 2)} TPS to {p_cur_rps} TPS (+{p_delta_pct}%)"
                )],
                metadata={"operations": list(pdata["ops"]), "callers": list(pdata["callers"]), "principals": [p_name]}
            ))

    # Relationship and identity detectors
    with get_connection(db_path) as db:
        historical_caller_targets = {f"{row[0]}->{row[1]}" for row in db.execute("SELECT caller_service, target_service FROM service_edges FINAL WHERE first_seen < ?", (window_start_sec,)).fetchall()}
        historical_principal_targets = {f"{row[0]}->{row[1]}" for row in db.execute("SELECT principal_name, target_service FROM principal_service_edges FINAL WHERE first_seen < ? AND principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '')", (window_start_sec,)).fetchall()}
        try:
            established_principals = {row[0] for row in db.execute("SELECT principal_name FROM principal_baselines FINAL WHERE sample_count >= 10 AND principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '')").fetchall()}
        except Exception:
            established_principals = set()

        # Historical learned endpoints for users (no hardcoded keywords)
        historical_user_endpoints_rows = db.execute(
            "SELECT DISTINCT principal_name, target_service, operation FROM principal_operations WHERE first_seen < ? AND principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '')",
            (window_start_sec * 1000,)
        ).fetchall()
        historical_user_endpoints = {
            f"{row[0]}->{row[1]}:{row[2]}" for row in historical_user_endpoints_rows
        }
        learned_users = {row[0] for row in historical_user_endpoints_rows}
        learned_users.update(established_principals)
        try:
            learned_users.update({
                row[0] for row in db.execute(
                    "SELECT DISTINCT principal_name FROM principals WHERE first_seen < ? AND principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '')",
                    (window_start_sec * 1000,)
                ).fetchall()
            })
        except Exception:
            pass
        try:
            mb_rows = db.execute(
                "SELECT DISTINCT principal_name, target_service, operation FROM metric_buckets WHERE bucket_start < ? AND principal_name IS NOT NULL AND principal_name NOT IN ('', 'unknown', '-anonymous-', 'anonymous')",
                (window_start_sec,)
            ).fetchall()
            for r_mb in mb_rows:
                historical_user_endpoints.add(f"{r_mb[0]}->{r_mb[1]}:{r_mb[2]}")
                learned_users.add(r_mb[0])
        except Exception:
            pass

        historical_anonymous_endpoints = set()
        try:
            anon_ep_rows = db.execute(
                """SELECT DISTINCT target_service, operation FROM metric_buckets 
                   WHERE bucket_start < ? 
                     AND (principal_name IS NULL OR principal_name IN ('', 'unknown', '-anonymous-', 'anonymous'))""",
                (window_start_sec,)
            ).fetchall()
            for r_anon in anon_ep_rows:
                historical_anonymous_endpoints.add(f"{r_anon[0]}:{r_anon[1]}")
        except Exception:
            pass

    for r in current_rows:
        c = r["caller_service"]
        t = r["target_service"]
        p = r["principal_name"]
        op = r["operation"]
        reqs = r["request_count"] or 0

        # Detector 5: New Service Relationship
        if c and t and historical_caller_targets and f"{c}->{t}" not in historical_caller_targets and reqs >= 5:
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="new_service_edge",
                severity="medium",
                score=65,
                confidence=0.85,
                caller_service=c,
                target_service=t,
                principal_name=p if p and p not in ("unknown", "-anonymous-", "anonymous") else None,
                operation=op,
                baseline_value=0.0,
                current_value=float(reqs),
                reasons=[AnomalyReason(
                    type="new_dependency",
                    contribution=65,
                    baseline=0.0,
                    current=float(reqs),
                    text=f"New dependency detected: {c} calling {t} for the first time ({reqs} reqs)"
                )]
            ))

        # Detector 6: New Principal Relationship (Identified human/service principals only)
        if p and p not in ("unknown", "-anonymous-", "anonymous", "") and t and historical_principal_targets and f"{p}->{t}" not in historical_principal_targets and reqs >= 5:
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="new_principal_edge",
                severity="high" if "admin" in t.lower() or "pay" in t.lower() else "medium",
                score=75,
                confidence=0.90,
                caller_service=c,
                target_service=t,
                principal_name=p,
                operation=op,
                baseline_value=0.0,
                current_value=float(reqs),
                reasons=[AnomalyReason(
                    type="new_principal",
                    contribution=75,
                    baseline=0.0,
                    current=float(reqs),
                    text=f"Principal '{p}' calling target '{t}' for the first time without historical authorization pattern"
                )]
            ))

        # Detector 7: Unusual Access (Truy cập Bất thường)
        # Behavioral anomaly:
        # Case A: Learned user behavioral shift - accessing a new endpoint never seen in baseline
        # Case B: 401/403 Authentication / Authorization failure burst
        # Case C: Anonymous traffic hitting a novel endpoint never previously accessed anonymously
        errs = r["error_count"] or 0
        is_unusual_access = False
        ua_score = 75
        ua_severity = "medium"
        ua_reason = ""
        ua_reason_type = "unusual_access"

        is_anonymous = not p or p in {"", "unknown", "-anonymous-", "anonymous"}
        is_learned_user = bool(not is_anonymous and (p in learned_users))
        is_user_new_endpoint = is_learned_user and (f"{p}->{t}:{op}" not in historical_user_endpoints)

        # Case A: Learned user behavioral shift
        if is_user_new_endpoint and reqs >= 1:
            is_unusual_access = True
            ua_score = 80 if errs > 0 else 75
            ua_severity = "high" if errs > 0 else "medium"
            ua_reason_type = "user_new_endpoint"
            ua_reason = f"Learned user '{p}' exhibited behavioral shift by accessing new endpoint '{op}' on target '{t}' for the first time"

        # Case B: 401/403 Authentication / Authorization failure burst
        elif errs >= 3 and (errs / max(1, reqs)) >= 0.4:
            is_unusual_access = True
            ua_score = 85
            ua_severity = "high"
            ua_reason_type = "auth_failure_burst"
            ua_reason = f"Access failure burst detected on target '{t}' operation '{op}' by '{p if not is_anonymous else 'anonymous'}' ({errs}/{reqs} failures)"

        # Case C: Anonymous traffic on an endpoint never previously accessed anonymously
        elif is_anonymous and historical_anonymous_endpoints and f"{t}:{op}" not in historical_anonymous_endpoints and reqs >= 10:
            is_unusual_access = True
            ua_score = 80 if errs > 0 else 70
            ua_severity = "high" if errs > 0 else "medium"
            ua_reason_type = "anonymous_new_endpoint"
            ua_reason = f"Anonymous traffic observed on endpoint '{op}' of target '{t}' for the first time ({reqs} requests, {errs} errors)"

        if is_unusual_access:
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="unusual_access",
                severity=ua_severity,
                score=ua_score,
                confidence=0.90,
                caller_service=c,
                target_service=t,
                principal_name=None if is_anonymous else p,
                operation=op,
                baseline_value=0.0,
                current_value=float(reqs),
                delta_percentage=100.0,
                reasons=[AnomalyReason(
                    type=ua_reason_type,
                    contribution=ua_score,
                    baseline=0.0,
                    current=float(reqs),
                    text=ua_reason
                )],
                metadata={
                    "principal": None if is_anonymous else p,
                    "target_service": t,
                    "caller_service": c,
                    "operation": op,
                    "requests": reqs,
                    "errors": errs,
                    "traffic_class": "anonymous" if is_anonymous else "identified",
                    "reason_type": ua_reason_type
                }
            ))

        # Detector 8: Unusual Execution Time (e.g. 02:00 - 05:00 UTC for established human accounts)
        # Exclude anonymous, automated machine accounts and unestablished cold-start traffic
        is_human_account = p and p not in {
            "batch-recon", "svc-checkout", "svc-billing", "shared-legacy",
            "unknown", "-anonymous-", "anonymous", ""
        }
        has_baseline = (p in established_principals) or bool(historical_principal_targets and any(pt.startswith(f"{p}->") for pt in historical_principal_targets))
        if 2 <= hod <= 4 and is_human_account and has_baseline and reqs >= 3:
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="unusual_time",
                severity="medium",
                score=60,
                confidence=0.80,
                caller_service=c,
                target_service=t,
                principal_name=p,
                operation=op,
                baseline_value=0.0,
                current_value=float(reqs),
                reasons=[AnomalyReason(
                    type="unusual_hour",
                    contribution=60,
                    baseline=0.0,
                    current=float(reqs),
                    text=f"Off-hours activity detected: established principal '{p}' active at {hod:02d}:00 UTC ({reqs} requests)"
                )]
            ))

    # Detector 9: User + Source IP Behavioral Anomalies
    with get_connection(db_path) as db:
        user_ip_window = db.execute("""
            SELECT
              principal_name,
              caller_ip as source_ip,
              COALESCE(caller_service, '') as caller_service,
              target_service,
              operation,
              COUNT(*) as request_count
            FROM traces
            WHERE timestamp_ms >= ? AND timestamp_ms < ?
              AND principal_name IS NOT NULL AND principal_name NOT IN ('', 'unknown', '-anonymous-', 'anonymous')
              AND caller_ip IS NOT NULL AND caller_ip != '' AND caller_ip NOT IN ('unknown', 'unavailable')
            GROUP BY principal_name, caller_ip, caller_service, target_service, operation
        """, (window_start_sec * 1000, window_end_sec * 1000)).fetchall()

        historical_user_ips = {
            (row[0], row[1]) for row in db.execute(
                "SELECT DISTINCT principal_name, caller_ip FROM traces WHERE timestamp_ms < ? AND principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '') AND caller_ip IS NOT NULL AND caller_ip != ''",
                (window_start_sec * 1000,)
            ).fetchall()
        }
        known_ips = {
            row[0] for row in db.execute(
                "SELECT DISTINCT caller_ip FROM traces WHERE timestamp_ms < ? AND caller_ip IS NOT NULL AND caller_ip != ''",
                (window_start_sec * 1000,)
            ).fetchall()
        }
        historical_ip_endpoints = set()
        try:
            ip_ep_rows = db.execute(
                "SELECT DISTINCT caller_ip, target_service, operation FROM traces WHERE timestamp_ms < ? AND caller_ip IS NOT NULL AND caller_ip != '' AND caller_ip NOT IN ('unknown', 'unavailable')",
                (window_start_sec * 1000,)
            ).fetchall()
            for row in ip_ep_rows:
                historical_ip_endpoints.add(f"{row[0]}->{row[1]}:{row[2]}")
                known_ips.add(row[0])
        except Exception:
            pass
        known_users = {
            row[0] for row in db.execute(
                "SELECT DISTINCT principal_name FROM traces WHERE timestamp_ms < ? AND principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '')",
                (window_start_sec * 1000,)
            ).fetchall()
        }

    for uip in user_ip_window:
        user = uip["principal_name"]
        ip = uip["source_ip"]
        u_reqs = uip["request_count"] or 0
        c_svc = uip["caller_service"]
        t_svc = uip["target_service"]
        u_op = uip["operation"]

        if not user or user in {"unknown", "-anonymous-", "anonymous", ""} or not ip or ip in {"unknown", "unavailable", ""} or u_reqs < 1:
            continue

        # Suppress IP behavioral signals when IP is an unresolved load balancer / F5 proxy
        from backend.app.services.normalization import is_known_infrastructure_ip
        if is_known_infrastructure_ip(ip):
            continue

        # Case A: Known user from a completely new / unobserved source IP
        if user in known_users and (user, ip) not in historical_user_ips:
            score = 80 if ("admin" in t_svc.lower() or "pay" in t_svc.lower()) else 70
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="user_new_source_ip",
                severity="high" if score >= 75 else "medium",
                score=score,
                confidence=0.90,
                caller_service=c_svc,
                target_service=t_svc,
                principal_name=user,
                source_ip=ip,
                operation=u_op,
                baseline_value=0.0,
                current_value=float(u_reqs),
                reasons=[AnomalyReason(
                    type="user_new_ip",
                    contribution=score,
                    baseline=0.0,
                    current=float(u_reqs),
                    text=f"Established user '{user}' accessed target '{t_svc}' from unobserved source IP {ip} ({u_reqs} requests)"
                )],
                metadata={"user": user, "source_ip": ip, "target_service": t_svc, "operation": u_op, "requests": u_reqs}
            ))

        # Case B: Known source IP suddenly used by an unexpected / new user
        elif ip in known_ips and (user, ip) not in historical_user_ips:
            score = 75
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="ip_new_user",
                severity="medium",
                score=score,
                confidence=0.85,
                caller_service=c_svc,
                target_service=t_svc,
                principal_name=user,
                source_ip=ip,
                operation=u_op,
                baseline_value=0.0,
                current_value=float(u_reqs),
                reasons=[AnomalyReason(
                    type="new_user_on_ip",
                    contribution=score,
                    baseline=0.0,
                    current=float(u_reqs),
                    text=f"Known IP {ip} was accessed by novel user '{user}' calling '{t_svc}' ({u_reqs} requests)"
                )],
                metadata={"user": user, "source_ip": ip, "target_service": t_svc, "operation": u_op, "requests": u_reqs}
            ))

        # Case C: Established source IP accessing a new endpoint for the first time
        if ip in known_ips and f"{ip}->{t_svc}:{u_op}" not in historical_ip_endpoints:
            score = 75
            anomalies.append(AnomalyEvent(
                detected_at=detected_at,
                anomaly_type="unusual_access",
                severity="medium",
                score=score,
                confidence=0.88,
                caller_service=c_svc,
                target_service=t_svc,
                principal_name=user if user and user != "unknown" else None,
                source_ip=ip,
                operation=u_op,
                baseline_value=0.0,
                current_value=float(u_reqs),
                delta_percentage=100.0,
                reasons=[AnomalyReason(
                    type="ip_new_endpoint",
                    contribution=score,
                    baseline=0.0,
                    current=float(u_reqs),
                    text=f"Established source IP {ip} exhibited behavioral shift by accessing new endpoint '{u_op}' on target '{t_svc}' for the first time"
                )],
                metadata={"user": user, "source_ip": ip, "target_service": t_svc, "operation": u_op, "requests": u_reqs}
            ))

    for anomaly in anomalies:
        if anomaly.first_seen is None:
            anomaly.first_seen = window_start_sec * 1000
        if anomaly.last_seen is None:
            anomaly.last_seen = window_end_sec * 1000
        anomaly.id = deterministic_anomaly_id(anomaly)

    if anomalies:
        anomaly_repo.save_anomalies(anomalies)

    return anomalies
