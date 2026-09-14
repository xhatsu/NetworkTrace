"""Incrementally derive identity relationships from sanitized, durable trace dimensions."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from backend.config import settings
from backend.app.repositories.db_context import db_transaction, get_connection
from backend.app.services.behavioral_engine import (
    CHANGE_SCORES,
    EVENT_SCORES,
    EVENT_FAMILY,
    FAMILY_CAPS,
    BASE_IMPORTANCE,
    emit_behavioral_change,
    evaluate_readiness,
    record_historical_observation,
    record_candidate_behavior,
    detect_operation_mix_shift,
    detect_caller_principal_switch,
    detect_target_fanout_surge,
    detect_source_fanout_surge,
    detect_principal_rate_surge,
    detect_explicit_auth_anomalies,
    detect_telemetry_quality_gates,
)
from backend.app.services.normalization import _is_trusted_proxy, derive_source_group


def _severity(score: int) -> str:
    return "high" if score >= 30 else "medium" if score >= 20 else "low"


def _emit(db, *, principal: str, change_type: str, observed: int,
          caller: str = "", source: str = "", target: str = "",
          operation: str = "", old: str = "", new: str = "",
          reason: dict[str, Any] | None = None, recurrence: str = "",
          principal_id: str = "") -> None:
    # Rename legacy NEW_USER_ON_IP to NEW_PRINCIPAL_ON_SOURCE
    if change_type == "NEW_USER_ON_IP":
        change_type = "NEW_PRINCIPAL_ON_SOURCE"

    pid = principal_id or f"production:{principal}"
    summary = None
    if reason and isinstance(reason, dict) and "summary" in reason:
        summary = reason["summary"]

    emit_behavioral_change(
        db,
        principal_id=pid,
        change_type=change_type,
        detected_at=observed,
        caller_service=caller,
        source_ip=source,
        target_service=target,
        operation=operation,
        old_value=old,
        new_value=new,
        custom_summary=summary,
    )


def _upsert_dimension(db, table: str, column: str, principal: str, value: str,
                      timestamp_ms: int, is_error: int = 0) -> None:
    if not value:
        return
    error_sql = ",error_count" if table in {"principal_targets", "principal_operations"} else ""
    error_value = ",?" if error_sql else ""
    key_values = value.split("\0")
    key_columns = column.split(",")
    where = " AND ".join(f"{name}=?" for name in ("principal_name", *key_columns))
    params = (principal, *key_values)
    select_cols = "first_seen,last_seen,observation_count" + (",error_count" if error_sql else "")
    existing = db.execute(f"SELECT {select_cols} FROM {table} FINAL WHERE {where} LIMIT 1", params).fetchone()
    if existing:
        replacement = (principal, *key_values, min(int(existing[0]), timestamp_ms),
                       max(int(existing[1]), timestamp_ms), int(existing[2]) + 1)
        if error_sql:
            replacement = (*replacement, int(existing[3]) + is_error)
        placeholders = ",".join("?" for _ in replacement)
        db.execute(f"INSERT INTO {table}(principal_name,{column},first_seen,last_seen,observation_count{error_sql}) "
                   f"VALUES({placeholders})", replacement)
        return
    values = (principal, *key_values, timestamp_ms, timestamp_ms)
    placeholders = ",".join("?" for _ in values)
    db.execute(f"INSERT INTO {table}(principal_name,{column},first_seen,last_seen,observation_count{error_sql}) "
               f"VALUES({placeholders},1{error_value})", (*values, *([is_error] if error_sql else [])))


def _dimension_known(db, principal: str, dimension: str, value: str) -> bool:
    return db.execute(
        "SELECT 1 FROM principal_baselines WHERE principal_name=? AND dimension_type=? AND dimension_value=?",
        (principal, dimension, value),
    ).fetchone() is not None


def _refresh_principal_counts(db, principal: str) -> None:
    row = db.execute("SELECT principal_type,first_seen,last_seen,total_requests,created_at FROM principals FINAL "
                     "WHERE principal_name=?", (principal,)).fetchone()
    if not row:
        return
    counts = [db.execute(f"SELECT COUNT(*) FROM {table} FINAL WHERE principal_name=?", (principal,)).fetchone()[0]
              for table in ("principal_callers", "principal_sources", "principal_targets", "principal_operations")]
    db.execute("INSERT INTO principals(principal_name,principal_type,first_seen,last_seen,total_requests,unique_callers,"
               "unique_sources,unique_targets,unique_operations,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (principal, row[0], row[1], row[2], row[3], *counts, row[4], int(time.time() * 1000)))


def _bootstrap(db, ratio: float) -> dict[str, int]:
    bounds = db.execute(
        "SELECT MIN(timestamp_ms),MAX(timestamp_ms) FROM traces WHERE principal_name<>'unknown'"
    ).fetchone()
    if not bounds or bounds[0] is None:
        return {"processed": 0, "changes": 0, "cursor": 0, "bootstrap_cutoff_ms": 0}
    minimum, maximum = map(int, bounds)
    cursor_row = db.execute(
        "SELECT ingest_order,toString(row_uid) FROM traces ORDER BY ingest_order DESC,row_uid DESC LIMIT 1"
    ).fetchone()
    cursor_order = int(cursor_row[0]) if cursor_row else 0
    cursor_uid = str(cursor_row[1]) if cursor_row else "00000000-0000-0000-0000-000000000000"
    cutoff = minimum + int((maximum - minimum) * ratio)
    now = int(time.time() * 1000)

    db.execute("""
      INSERT INTO principals(principal_name,principal_type,first_seen,last_seen,total_requests,
        unique_callers,unique_sources,unique_targets,unique_operations,created_at,updated_at)
      SELECT principal_name,'unknown',MIN(timestamp_ms),MAX(timestamp_ms),COUNT(*),
        COUNT(DISTINCT CASE WHEN caller_service<>'' THEN caller_service END),
        COUNT(DISTINCT CASE WHEN caller_ip<>'' THEN caller_ip END),COUNT(DISTINCT target_service),
        COUNT(DISTINCT operation),?,? FROM traces
      WHERE principal_name<>'unknown' GROUP BY principal_name
    """, (now, now))
    relationship_select = """
      SELECT principal_name,COALESCE(caller_service,''),COALESCE(caller_instance,''),COALESCE(caller_ip,''),
        target_service,COALESCE(target_instance,''),COALESCE(target_ip,''),COALESCE(target_port,0),
        operation,COALESCE(http_method,''),MIN(timestamp_ms),MAX(timestamp_ms),COUNT(*),
        SUM(CASE WHEN http_status<400 AND outcome<>'failure' THEN 1 ELSE 0 END),
        SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END)
      FROM traces WHERE principal_name<>'unknown'
      GROUP BY principal_name,caller_service,caller_instance,caller_ip,target_service,target_instance,target_ip,target_port,operation,http_method
    """
    db.execute("""
      INSERT INTO principal_relationships(principal_name,caller_service,caller_instance,source_ip,
        target_service,target_instance,target_ip,target_port,operation,http_method,first_seen,last_seen,
        observation_count,success_count,error_count) """ + relationship_select)
    for table, column, expression, col_extra, expr_extra in (
        ("principal_callers", "caller_service", "caller_service", "", ""),
        ("principal_sources", "source_ip", "caller_ip", "", ""),
        ("principal_targets", "target_service", "target_service", ",error_count", ",SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END)"),
    ):
        db.execute(f"""
          INSERT INTO {table}(principal_name,{column},first_seen,last_seen,observation_count{col_extra})
          SELECT principal_name,{expression},MIN(timestamp_ms),MAX(timestamp_ms),COUNT(*){expr_extra}
          FROM traces WHERE principal_name<>'unknown' AND COALESCE({expression},'')<>''
          GROUP BY principal_name,{expression}
        """)
    db.execute("""
      INSERT INTO principal_operations(principal_name,target_service,operation,first_seen,last_seen,observation_count,error_count)
      SELECT principal_name,target_service,operation,MIN(timestamp_ms),MAX(timestamp_ms),COUNT(*),
        SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END)
      FROM traces WHERE principal_name<>'unknown' GROUP BY principal_name,target_service,operation
    """)
    db.execute("""
      INSERT INTO principal_hourly_activity(principal_name,day_of_week,hour_of_day,observation_count,error_count)
      SELECT principal_name,CAST(strftime('%w',timestamp_ms/1000,'unixepoch') AS INTEGER),
        CAST(strftime('%H',timestamp_ms/1000,'unixepoch') AS INTEGER),COUNT(*),
        SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END)
      FROM traces WHERE principal_name<>'unknown' GROUP BY principal_name,2,3
    """)
    db.execute("""
      INSERT INTO principal_daily_stats(principal_name,day_start,observation_count,error_count,
        unique_callers,unique_sources,unique_targets,unique_operations)
      SELECT principal_name,(timestamp_ms/86400000)*86400000,COUNT(*),
        SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END),
        COUNT(DISTINCT caller_service),COUNT(DISTINCT caller_ip),COUNT(DISTINCT target_service),COUNT(DISTINCT operation)
      FROM traces WHERE principal_name<>'unknown' GROUP BY principal_name,2
    """)

    baseline_dimensions = (
        ("caller", "caller_service", "caller_service<>''"),
        ("source", "caller_ip", "caller_ip<>''"),
        ("target", "target_service", "target_service<>''"),
        ("operation", "target_service||'→'||operation", "operation<>''"),
        ("hour", "CAST(strftime('%w',timestamp_ms/1000,'unixepoch') AS TEXT)||':'||strftime('%H',timestamp_ms/1000,'unixepoch')", "1=1"),
        ("relationship", "COALESCE(caller_service,'')||'→'||COALESCE(caller_ip,'')||'→'||target_service||'→'||operation", "1=1"),
    )
    for dimension, expression, condition in baseline_dimensions:
        db.execute(f"""
          INSERT INTO principal_baselines(principal_name,dimension_type,dimension_value,first_seen,last_seen,observation_count,distribution_share)
          SELECT principal_name,?,{expression},MIN(timestamp_ms),MAX(timestamp_ms),COUNT(*),
            COUNT(*)*1.0/SUM(COUNT(*)) OVER (PARTITION BY principal_name)
          FROM traces WHERE principal_name<>'unknown' AND timestamp_ms<=? AND {condition}
          GROUP BY principal_name,{expression}
        """, (dimension, cutoff))

    before = db.total_changes
    for principal, first_seen in db.execute(
        "SELECT principal_name,first_seen FROM principals WHERE first_seen>?", (cutoff,)
    ).fetchall():
        _emit(db, principal=principal, change_type="USERNAME_FIRST_SEEN", observed=first_seen,
              new=principal, reason={"summary": f"{principal} first appeared after the historical baseline window."})

    dimension_events = (
        ("principal_callers", "caller_service", "caller", "NEW_CALLER"),
        ("principal_sources", "source_ip", "source", "NEW_SOURCE_IP"),
        ("principal_targets", "target_service", "target", "NEW_TARGET"),
    )
    for table, column, dimension, event_type in dimension_events:
        for principal, value, first_seen in db.execute(
            f"SELECT principal_name,{column},first_seen FROM {table} WHERE first_seen>?", (cutoff,)
        ).fetchall():
            kwargs = {"caller": value} if dimension == "caller" else {"source": value} if dimension == "source" else {"target": value}
            _emit(db, principal=principal, change_type=event_type, observed=first_seen, new=value, **kwargs)

    # Check for dedicated IPs accessed by novel users post-cutoff (excluding shared proxies)
    for principal, source, first_seen in db.execute("""
        SELECT DISTINCT ps.principal_name, ps.source_ip, ps.first_seen
        FROM principal_sources ps
        INNER JOIN principal_baselines pb
          ON ps.source_ip = pb.dimension_value
        WHERE ps.first_seen > ?
          AND pb.dimension_type = 'source'
          AND pb.principal_name <> ps.principal_name
    """, (cutoff,)).fetchall():
        if not _is_trusted_proxy(source):
            _emit(db, principal=principal, change_type="NEW_PRINCIPAL_ON_SOURCE", observed=first_seen,
                  source=source, new=principal,
                  reason={"summary": f"Known host {source} was accessed by novel user {principal}."})

    for principal, target, operation, first_seen in db.execute(
        "SELECT principal_name,target_service,operation,first_seen FROM principal_operations WHERE first_seen>?", (cutoff,)
    ).fetchall():
        _emit(db, principal=principal, change_type="NEW_OPERATION", observed=first_seen,
              target=target, operation=operation, new=operation)

    for row in db.execute("""
        SELECT principal_name,caller_service,source_ip,target_service,operation,first_seen
        FROM principal_relationships WHERE first_seen>?
    """, (cutoff,)).fetchall():
        _emit(db, principal=row[0], change_type="NEW_RELATIONSHIP", observed=row[5], caller=row[1],
              source=row[2], target=row[3], operation=row[4], new=" → ".join(row[1:5]))

    changes = db.total_changes - before
    checkpoint = json.dumps({"ingest_order": cursor_order, "row_uid": cursor_uid, "bootstrap_cutoff_ms": cutoff, "ratio": ratio})
    db.execute("INSERT INTO checkpoints(source,cursor_json,updated_at_ms) VALUES('principal_intelligence',?,?)",
               (checkpoint, now))
    return {"processed": db.execute("SELECT COUNT(*) FROM traces WHERE principal_name<>'unknown'").fetchone()[0],
            "changes": changes, "cursor": cursor_order, "bootstrap_cutoff_ms": cutoff}


def _process_incremental_row(db, row) -> int:
    principal = row["principal_name"]
    if not principal or principal == "unknown":
        return 0
    timestamp_ms = row["timestamp_ms"]
    caller = row["caller_service"] or ""
    source = row["caller_ip"] or ""
    target = row["target_service"] or ""
    operation = row["operation"] or ""

    env = row["service_environment"] if "service_environment" in row.keys() else "production"
    principal_id = row["principal_id"] if "principal_id" in row.keys() and row["principal_id"] else f"{env}:{principal}"
    op_key = row["operation_key"] if "operation_key" in row.keys() and row["operation_key"] else operation
    src_group = row["source_group"] if "source_group" in row.keys() and row["source_group"] else derive_source_group(source)

    # 1. Update historical registry for all dimensions
    record_historical_observation(db, principal_id, "caller", caller, timestamp_ms)
    record_historical_observation(db, principal_id, "source", source, timestamp_ms)
    record_historical_observation(db, principal_id, "target", target, timestamp_ms)
    record_historical_observation(db, principal_id, "operation", op_key, timestamp_ms)
    logical_rel = f"{caller}→{target}→{op_key}"
    record_historical_observation(db, principal_id, "logical_relationship", logical_rel, timestamp_ms)
    if src_group:
        origin_rel = f"{caller}→{src_group}→{target}→{op_key}"
        record_historical_observation(db, principal_id, "origin_relationship", origin_rel, timestamp_ms)

    existing = db.execute("SELECT principal_type,first_seen,last_seen,total_requests,unique_callers,unique_sources,"
                          "unique_targets,unique_operations,created_at FROM principals FINAL WHERE principal_name=?",
                          (principal,)).fetchone()
    is_new = existing is None

    # Track novelty flags to avoid duplicate scoring
    is_caller_new = False
    is_target_new = False
    is_op_new = False

    if is_new:
        _emit(db, principal=principal, principal_id=principal_id, change_type="USERNAME_FIRST_SEEN", observed=timestamp_ms,
              caller=caller, source=source, target=target, operation=operation,
              new=principal, recurrence=str(timestamp_ms // 86_400_000))
    elif timestamp_ms - existing[2] >= settings.principal_dormant_days * 86_400_000:
        ready, _ = evaluate_readiness(db, principal_id, "DORMANT_REACTIVATED", timestamp_ms)
        if ready:
            days = (timestamp_ms - existing[2]) // 86_400_000
            _emit(db, principal=principal, principal_id=principal_id, change_type="DORMANT_REACTIVATED", observed=timestamp_ms,
                  old=f"inactive {days} days", new="active", recurrence=str(timestamp_ms // 86_400_000),
                  reason={"summary": f"{principal} became active after {days} inactive days."})

    # Dedicated source host accessed by novel user (excluding shared proxies / gateways)
    if source and source not in {"unknown", ""} and not _is_trusted_proxy(source):
        ip_globally_known = db.execute("SELECT 1 FROM principal_sources WHERE source_ip=? LIMIT 1", (source,)).fetchone()
        if ip_globally_known and not _dimension_known(db, principal, "source", source):
            already_seen_together = db.execute(
                "SELECT 1 FROM principal_sources WHERE principal_name=? AND source_ip=?", (principal, source)
            ).fetchone()
            if not already_seen_together:
                ready, _ = evaluate_readiness(db, principal_id, "NEW_PRINCIPAL_ON_SOURCE", timestamp_ms)
                if ready:
                    _emit(db, principal=principal, principal_id=principal_id, change_type="NEW_PRINCIPAL_ON_SOURCE", observed=timestamp_ms,
                          caller=caller, source=source, target=target, operation=operation, new=principal,
                          reason={"summary": f"Host {source} was accessed by novel user {principal}."})

    # Detector readiness-guarded novelty checks
    if caller and not _dimension_known(db, principal, "caller", caller):
        ready, _ = evaluate_readiness(db, principal_id, "NEW_CALLER", timestamp_ms)
        if ready:
            _emit(db, principal=principal, principal_id=principal_id, change_type="NEW_CALLER", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=caller)
            is_caller_new = True

    if source and not _dimension_known(db, principal, "source", source):
        ready, _ = evaluate_readiness(db, principal_id, "NEW_SOURCE_IP", timestamp_ms)
        if ready:
            _emit(db, principal=principal, principal_id=principal_id, change_type="NEW_SOURCE_IP", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=source)

    if target and not _dimension_known(db, principal, "target", target):
        ready, _ = evaluate_readiness(db, principal_id, "NEW_TARGET", timestamp_ms)
        if ready:
            _emit(db, principal=principal, principal_id=principal_id, change_type="NEW_TARGET", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=target)
            is_target_new = True

    op_dim = f"{target}→{operation}"
    if operation and not _dimension_known(db, principal, "operation", op_dim):
        ready, _ = evaluate_readiness(db, principal_id, "NEW_OPERATION", timestamp_ms)
        if ready:
            _emit(db, principal=principal, principal_id=principal_id, change_type="NEW_OPERATION", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=operation)
            is_op_new = True

    # Logical relationship novelty
    rel_dim = f"{caller}→{source}→{target}→{operation}"
    if not _dimension_known(db, principal, "relationship", rel_dim):
        ready, _ = evaluate_readiness(db, principal_id, "NEW_RELATIONSHIP", timestamp_ms)
        # Score NEW_RELATIONSHIP only when constituent dimensions are already known
        if ready and not (is_caller_new or is_target_new or is_op_new):
            _emit(db, principal=principal, principal_id=principal_id, change_type="NEW_RELATIONSHIP", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=rel_dim)

    # Circadian unusual time check
    day_hour = time.strftime("%w:%H", time.gmtime(timestamp_ms / 1000))
    if not _dimension_known(db, principal, "hour", day_hour):
        ready, _ = evaluate_readiness(db, principal_id, "UNUSUAL_TIME", timestamp_ms)
        if ready:
            active_hours = db.execute(
                "SELECT COUNT(DISTINCT hour_of_day) FROM principal_hourly_activity WHERE principal_name = ?",
                (principal,)
            ).fetchone()[0]
            # Only alert if account is diurnal/periodic, not continuous 24h
            if active_hours <= 18:
                _emit(db, principal=principal, principal_id=principal_id, change_type="UNUSUAL_TIME", observed=timestamp_ms,
                      caller=caller, source=source, target=target, operation=operation, new=day_hour,
                      recurrence=str(timestamp_ms // 3_600_000))

    # Check explicit authentication outcomes
    if "auth_result" in row.keys() and row["auth_result"] == "failure":
        detect_explicit_auth_anomalies(db, principal_id, timestamp_ms - 900_000, timestamp_ms + 1)

    # Update candidate behaviors
    record_candidate_behavior(db, principal_id, "caller", caller, timestamp_ms, timestamp_ms // 900000)
    record_candidate_behavior(db, principal_id, "target", target, timestamp_ms, timestamp_ms // 900000)
    record_candidate_behavior(db, principal_id, "operation", op_key, timestamp_ms, timestamp_ms // 900000)

    now = int(time.time() * 1000)
    if existing:
        db.execute("INSERT INTO principals(principal_name,principal_type,first_seen,last_seen,total_requests,unique_callers,"
                   "unique_sources,unique_targets,unique_operations,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (principal, existing[0], min(int(existing[1]), timestamp_ms), max(int(existing[2]), timestamp_ms),
                    int(existing[3]) + 1, existing[4], existing[5], existing[6], existing[7], existing[8], now))
    else:
        db.execute("INSERT INTO principals(principal_name,principal_type,first_seen,last_seen,total_requests,created_at,updated_at) "
                   "VALUES(?,'unknown',?,?,1,?,?)", (principal, timestamp_ms, timestamp_ms, now, now))
    error = int((row["http_status"] or 0) >= 400 or row["outcome"] == "failure")
    _upsert_dimension(db, "principal_callers", "caller_service", principal, caller, timestamp_ms)
    _upsert_dimension(db, "principal_sources", "source_ip", principal, source, timestamp_ms)
    _upsert_dimension(db, "principal_targets", "target_service", principal, target, timestamp_ms, error)
    _upsert_dimension(db, "principal_operations", "target_service,operation", principal,
                      f"{target}\0{operation}", timestamp_ms, error)
    relationship_key = (principal, caller, row["caller_instance"] or "", source, target,
                        row["target_instance"] or "", row["target_ip"] or "", row["target_port"] or 0,
                        operation, row["http_method"] or "")
    relationship_where = " AND ".join(f"{c}=?" for c in (
        "principal_name", "caller_service", "caller_instance", "source_ip", "target_service",
        "target_instance", "target_ip", "target_port", "operation", "http_method"))
    prior_relationship = db.execute(
        f"SELECT first_seen,last_seen,observation_count,success_count,error_count FROM principal_relationships FINAL "
        f"WHERE {relationship_where} LIMIT 1", relationship_key).fetchone()
    if prior_relationship:
        db.execute("INSERT INTO principal_relationships(principal_name,caller_service,caller_instance,source_ip,target_service,"
                   "target_instance,target_ip,target_port,operation,http_method,first_seen,last_seen,observation_count,success_count,error_count) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (*relationship_key, min(int(prior_relationship[0]), timestamp_ms),
                    max(int(prior_relationship[1]), timestamp_ms), int(prior_relationship[2]) + 1,
                    int(prior_relationship[3]) + 1-error, int(prior_relationship[4]) + error))
    else:
        db.execute("INSERT INTO principal_relationships(principal_name,caller_service,caller_instance,source_ip,target_service,"
                   "target_instance,target_ip,target_port,operation,http_method,first_seen,last_seen,observation_count,success_count,error_count) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)", (*relationship_key, timestamp_ms, timestamp_ms, 1-error, error))
    day = (timestamp_ms // 86_400_000) * 86_400_000
    dow, hour = map(int, time.strftime("%w %H", time.gmtime(timestamp_ms / 1000)).split())
    prior_hour = db.execute("SELECT observation_count,error_count FROM principal_hourly_activity FINAL WHERE principal_name=? AND day_of_week=? AND hour_of_day=?", (principal, dow, hour)).fetchone()
    if prior_hour:
        db.execute("INSERT INTO principal_hourly_activity VALUES(?,?,?,?,?)",
                   (principal, dow, hour, int(prior_hour[0]) + 1, int(prior_hour[1]) + error))
    else:
        db.execute("INSERT INTO principal_hourly_activity VALUES(?,?,?,?,?)", (principal, dow, hour, 1, error))
    prior_day = db.execute("SELECT observation_count,error_count,unique_callers,unique_sources,unique_targets,unique_operations "
                           "FROM principal_daily_stats FINAL WHERE principal_name=? AND day_start=?", (principal, day)).fetchone()
    if prior_day:
        db.execute("INSERT INTO principal_daily_stats VALUES(?,?,?,?,?,?,?,?)",
                   (principal, day, int(prior_day[0]) + 1, int(prior_day[1]) + error,
                    int(prior_day[2]), int(prior_day[3]), int(prior_day[4]), int(prior_day[5])))
    else:
        db.execute("INSERT INTO principal_daily_stats VALUES(?,?,?,?,?,?,?,?)", (principal, day, 1, error, 0, 0, 0, 0))
    _refresh_principal_counts(db, principal)
    return 1


def process_principal_intelligence(db_path: Optional[str] = None) -> dict[str, int]:
    with db_transaction(db_path) as db:
        checkpoint_row = db.execute(
            "SELECT cursor_json FROM checkpoints WHERE source='principal_intelligence'"
        ).fetchone()
        if not checkpoint_row:
            return _bootstrap(db, settings.principal_bootstrap_ratio)
        checkpoint = json.loads(checkpoint_row[0])
        cursor_order = int(checkpoint.get("ingest_order", 0))
        cursor_uid = str(checkpoint.get("row_uid", "00000000-0000-0000-0000-000000000000"))
        processed = 0
        while True:
            rows = db.execute(
                "SELECT * FROM traces WHERE (ingest_order,row_uid)>(?,toUUID(?)) "
                "ORDER BY ingest_order,row_uid LIMIT 10000", (cursor_order, cursor_uid)
            ).fetchall()
            if not rows:
                break
            for row in rows:
                processed += _process_incremental_row(db, row)
                cursor_order = int(row["ingest_order"])
                cursor_uid = str(row["row_uid"])
        checkpoint["ingest_order"] = cursor_order
        checkpoint["row_uid"] = cursor_uid
        db.execute("UPDATE checkpoints SET cursor_json=?,updated_at_ms=? WHERE source='principal_intelligence'",
                   (json.dumps(checkpoint), int(time.time() * 1000)))
        return {"processed": processed, "changes": db.total_changes, "cursor": cursor_order,
                "bootstrap_cutoff_ms": int(checkpoint.get("bootstrap_cutoff_ms", 0))}
