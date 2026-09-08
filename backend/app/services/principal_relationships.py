from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from backend.config import settings
from backend.app.repositories.db_context import db_transaction, get_connection


CHANGE_SCORES = {
    "USERNAME_FIRST_SEEN": 10,
    "NEW_CALLER": 30,
    "NEW_SOURCE_IP": 20,
    "NEW_TARGET": 25,
    "NEW_OPERATION": 15,
    "NEW_RELATIONSHIP": 15,
    "DORMANT_REACTIVATED": 40,
    "UNUSUAL_TIME": 10,
    "CALLER_EXPANSION": 30,
    "TARGET_EXPANSION": 25,
    "OPERATION_EXPANSION": 15,
    "RELATIONSHIP_REAPPEARED": 25,
    "RELATIONSHIP_DISAPPEARED": 15,
}


def _severity(score: int) -> str:
    return "high" if score >= 30 else "medium" if score >= 20 else "low"


def _emit(db, *, principal: str, change_type: str, observed: int,
          caller: str = "", source: str = "", target: str = "",
          operation: str = "", old: str = "", new: str = "",
          reason: dict[str, Any] | None = None, recurrence: str = "") -> None:
    score = CHANGE_SCORES[change_type]
    identity = "|".join((principal, change_type, caller, source, target, operation, recurrence))
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()
    explanation = reason or {
        "summary": change_type.replace("_", " ").title(),
        "evidence": {"old": old or None, "new": new or None},
        "framing": "Behavior change; review operational context before classification.",
    }
    now = int(time.time() * 1000)
    db.execute("""
      INSERT OR IGNORE INTO principal_change_events(
        fingerprint,principal_name,change_type,severity,score,detected_at,
        caller_service,source_ip,target_service,operation,old_value,new_value,
        first_observed,reason_json,status,updated_at
      ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (fingerprint, principal, change_type, _severity(score), score, observed,
          caller or None, source or None, target or None, operation or None,
          old or None, new or None, observed,
          json.dumps(explanation, separators=(",", ":")), "new", now))


def _upsert_dimension(db, table: str, column: str, principal: str, value: str,
                      timestamp_ms: int, is_error: int = 0) -> None:
    if not value:
        return
    error_sql = ",error_count" if table in {"principal_targets", "principal_operations"} else ""
    error_value = ",?" if error_sql else ""
    conflict_columns = f"principal_name,{column}"
    if table == "principal_operations":
        conflict_columns = "principal_name,target_service,operation"
    values = (principal, *value.split("\0"), timestamp_ms, timestamp_ms)
    placeholders = ",".join("?" for _ in values)
    db.execute(f"""
      INSERT INTO {table}(principal_name,{column},first_seen,last_seen,observation_count{error_sql})
      VALUES({placeholders},1{error_value})
      ON CONFLICT({conflict_columns}) DO UPDATE SET
        first_seen=MIN(first_seen,excluded.first_seen),last_seen=MAX(last_seen,excluded.last_seen),
        observation_count=observation_count+1
        {',error_count=error_count+excluded.error_count' if error_sql else ''}
    """, (*values, *([is_error] if error_sql else [])))


def _dimension_known(db, principal: str, dimension: str, value: str) -> bool:
    return db.execute(
        "SELECT 1 FROM principal_baselines WHERE principal_name=? AND dimension_type=? AND dimension_value=?",
        (principal, dimension, value),
    ).fetchone() is not None


def _refresh_principal_counts(db, principal: str) -> None:
    db.execute("""
      UPDATE principals SET
        unique_callers=(SELECT COUNT(*) FROM principal_callers WHERE principal_name=?),
        unique_sources=(SELECT COUNT(*) FROM principal_sources WHERE principal_name=?),
        unique_targets=(SELECT COUNT(*) FROM principal_targets WHERE principal_name=?),
        unique_operations=(SELECT COUNT(*) FROM principal_operations WHERE principal_name=?),
        updated_at=? WHERE principal_name=?
    """, (principal, principal, principal, principal, int(time.time() * 1000), principal))


def _bootstrap(db, ratio: float) -> dict[str, int]:
    bounds = db.execute(
        "SELECT MIN(timestamp_ms),MAX(timestamp_ms),MAX(id) FROM traces WHERE principal_name<>'unknown'"
    ).fetchone()
    if not bounds or bounds[0] is None:
        return {"processed": 0, "changes": 0, "cursor": 0, "bootstrap_cutoff_ms": 0}
    minimum, maximum, cursor = map(int, bounds)
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
      ON CONFLICT(principal_name) DO UPDATE SET first_seen=excluded.first_seen,last_seen=excluded.last_seen,
        total_requests=excluded.total_requests,unique_callers=excluded.unique_callers,
        unique_sources=excluded.unique_sources,unique_targets=excluded.unique_targets,
        unique_operations=excluded.unique_operations,updated_at=excluded.updated_at
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
        observation_count,success_count,error_count) """ + relationship_select + """
      ON CONFLICT(principal_name,caller_service,caller_instance,source_ip,target_service,target_instance,target_ip,target_port,operation,http_method)
      DO UPDATE SET first_seen=excluded.first_seen,last_seen=excluded.last_seen,
        observation_count=excluded.observation_count,success_count=excluded.success_count,error_count=excluded.error_count
    """)
    for table, column, expression, extra in (
        ("principal_callers", "caller_service", "caller_service", ""),
        ("principal_sources", "source_ip", "caller_ip", ""),
        ("principal_targets", "target_service", "target_service", ",SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END)"),
    ):
        db.execute(f"""
          INSERT INTO {table}(principal_name,{column},first_seen,last_seen,observation_count{',error_count' if extra else ''})
          SELECT principal_name,{expression},MIN(timestamp_ms),MAX(timestamp_ms),COUNT(*){extra}
          FROM traces WHERE principal_name<>'unknown' AND COALESCE({expression},'')<>''
          GROUP BY principal_name,{expression}
          ON CONFLICT(principal_name,{column}) DO UPDATE SET first_seen=excluded.first_seen,
            last_seen=excluded.last_seen,observation_count=excluded.observation_count
            {',error_count=excluded.error_count' if extra else ''}
        """)
    db.execute("""
      INSERT INTO principal_operations(principal_name,target_service,operation,first_seen,last_seen,observation_count,error_count)
      SELECT principal_name,target_service,operation,MIN(timestamp_ms),MAX(timestamp_ms),COUNT(*),
        SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END)
      FROM traces WHERE principal_name<>'unknown' GROUP BY principal_name,target_service,operation
      ON CONFLICT(principal_name,target_service,operation) DO UPDATE SET first_seen=excluded.first_seen,
        last_seen=excluded.last_seen,observation_count=excluded.observation_count,error_count=excluded.error_count
    """)
    db.execute("""
      INSERT INTO principal_hourly_activity(principal_name,day_of_week,hour_of_day,observation_count,error_count)
      SELECT principal_name,CAST(strftime('%w',timestamp_ms/1000,'unixepoch') AS INTEGER),
        CAST(strftime('%H',timestamp_ms/1000,'unixepoch') AS INTEGER),COUNT(*),
        SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END)
      FROM traces WHERE principal_name<>'unknown' GROUP BY principal_name,2,3
      ON CONFLICT(principal_name,day_of_week,hour_of_day) DO UPDATE SET
        observation_count=excluded.observation_count,error_count=excluded.error_count
    """)
    db.execute("""
      INSERT INTO principal_daily_stats(principal_name,day_start,observation_count,error_count,
        unique_callers,unique_sources,unique_targets,unique_operations)
      SELECT principal_name,(timestamp_ms/86400000)*86400000,COUNT(*),
        SUM(CASE WHEN http_status>=400 OR outcome='failure' THEN 1 ELSE 0 END),
        COUNT(DISTINCT caller_service),COUNT(DISTINCT caller_ip),COUNT(DISTINCT target_service),COUNT(DISTINCT operation)
      FROM traces WHERE principal_name<>'unknown' GROUP BY principal_name,2
      ON CONFLICT(principal_name,day_start) DO UPDATE SET observation_count=excluded.observation_count,
        error_count=excluded.error_count,unique_callers=excluded.unique_callers,
        unique_sources=excluded.unique_sources,unique_targets=excluded.unique_targets,
        unique_operations=excluded.unique_operations
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
            COUNT(*)*1.0/(SELECT COUNT(*) FROM traces total WHERE total.principal_name=traces.principal_name AND total.timestamp_ms<=?)
          FROM traces WHERE principal_name<>'unknown' AND timestamp_ms<=? AND {condition}
          GROUP BY principal_name,{expression}
          ON CONFLICT(principal_name,dimension_type,dimension_value) DO UPDATE SET
            first_seen=excluded.first_seen,last_seen=excluded.last_seen,observation_count=excluded.observation_count,
            distribution_share=excluded.distribution_share
        """, (dimension, cutoff, cutoff))

    before = db.total_changes
    for principal, first_seen in db.execute(
        "SELECT principal_name,first_seen FROM principals WHERE first_seen>?", (cutoff,)
    ).fetchall():
        _emit(db, principal=principal, change_type="USERNAME_FIRST_SEEN", observed=first_seen,
              new=principal, reason={"summary": f"{principal} first appeared after the historical baseline window.",
              "evidence": {"first_seen": first_seen}, "framing": "Newly observed identity; not automatically suspicious."})
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
    checkpoint = json.dumps({"trace_id": cursor, "bootstrap_cutoff_ms": cutoff, "ratio": ratio})
    db.execute("INSERT INTO checkpoints(source,cursor_json,updated_at_ms) VALUES('principal_intelligence',?,?) "
               "ON CONFLICT(source) DO UPDATE SET cursor_json=excluded.cursor_json,updated_at_ms=excluded.updated_at_ms",
               (checkpoint, now))
    return {"processed": db.execute("SELECT COUNT(*) FROM traces WHERE principal_name<>'unknown'").fetchone()[0],
            "changes": changes, "cursor": cursor, "bootstrap_cutoff_ms": cutoff}


def _process_incremental_row(db, row) -> int:
    principal = row["principal_name"]
    if not principal or principal == "unknown":
        return 0
    timestamp_ms = row["timestamp_ms"]
    caller, source, target, operation = (row["caller_service"] or "", row["caller_ip"] or "",
                                          row["target_service"] or "", row["operation"] or "")
    existing = db.execute("SELECT first_seen,last_seen FROM principals WHERE principal_name=?", (principal,)).fetchone()
    is_new = existing is None
    learning = is_new or timestamp_ms - existing[0] < settings.principal_learning_days * 86_400_000
    if is_new:
        _emit(db, principal=principal, change_type="USERNAME_FIRST_SEEN", observed=timestamp_ms,
              new=principal, recurrence=str(timestamp_ms // 86_400_000))
    elif timestamp_ms - existing[1] >= settings.principal_dormant_days * 86_400_000:
        days = (timestamp_ms - existing[1]) // 86_400_000
        _emit(db, principal=principal, change_type="DORMANT_REACTIVATED", observed=timestamp_ms,
              old=f"inactive {days} days", new="active", recurrence=str(timestamp_ms // 86_400_000),
              reason={"summary": f"{principal} became active after {days} inactive days.",
                      "evidence": {"previous_last_seen": existing[1], "inactive_days": days},
                      "framing": "Reactivation may be operationally expected; verify ownership and deployment context."})

    if not learning:
        checks = (("caller", caller, "NEW_CALLER"), ("source", source, "NEW_SOURCE_IP"),
                  ("target", target, "NEW_TARGET"), ("operation", f"{target}→{operation}", "NEW_OPERATION"),
                  ("relationship", f"{caller}→{source}→{target}→{operation}", "NEW_RELATIONSHIP"))
        for dimension, value, change_type in checks:
            if value and not _dimension_known(db, principal, dimension, value):
                kwargs = {"caller": caller, "source": source, "target": target, "operation": operation}
                _emit(db, principal=principal, change_type=change_type, observed=timestamp_ms,
                      new=value, **kwargs)
        day_hour = time.strftime("%w:%H", time.gmtime(timestamp_ms / 1000))
        if not _dimension_known(db, principal, "hour", day_hour):
            _emit(db, principal=principal, change_type="UNUSUAL_TIME", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=day_hour,
                  recurrence=str(timestamp_ms // 3_600_000))

    now = int(time.time() * 1000)
    db.execute("""
      INSERT INTO principals(principal_name,principal_type,first_seen,last_seen,total_requests,created_at,updated_at)
      VALUES(?,'unknown',?,?,1,?,?) ON CONFLICT(principal_name) DO UPDATE SET
      first_seen=MIN(first_seen,excluded.first_seen),last_seen=MAX(last_seen,excluded.last_seen),
      total_requests=total_requests+1,updated_at=excluded.updated_at
    """, (principal, timestamp_ms, timestamp_ms, now, now))
    error = int((row["http_status"] or 0) >= 400 or row["outcome"] == "failure")
    _upsert_dimension(db, "principal_callers", "caller_service", principal, caller, timestamp_ms)
    _upsert_dimension(db, "principal_sources", "source_ip", principal, source, timestamp_ms)
    _upsert_dimension(db, "principal_targets", "target_service", principal, target, timestamp_ms, error)
    _upsert_dimension(db, "principal_operations", "target_service,operation", principal,
                      f"{target}\0{operation}", timestamp_ms, error)
    db.execute("""
      INSERT INTO principal_relationships(principal_name,caller_service,caller_instance,source_ip,target_service,
        target_instance,target_ip,target_port,operation,http_method,first_seen,last_seen,observation_count,success_count,error_count)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
      ON CONFLICT(principal_name,caller_service,caller_instance,source_ip,target_service,target_instance,target_ip,target_port,operation,http_method)
      DO UPDATE SET last_seen=MAX(last_seen,excluded.last_seen),observation_count=observation_count+1,
        success_count=success_count+excluded.success_count,error_count=error_count+excluded.error_count
    """, (principal, caller, row["caller_instance"] or "", source, target, row["target_instance"] or "",
          row["target_ip"] or "", row["target_port"] or 0, operation, row["http_method"] or "",
          timestamp_ms, timestamp_ms, 1-error, error))
    day = (timestamp_ms // 86_400_000) * 86_400_000
    dow, hour = map(int, time.strftime("%w %H", time.gmtime(timestamp_ms / 1000)).split())
    db.execute("INSERT INTO principal_hourly_activity VALUES(?,?,?,?,?) ON CONFLICT(principal_name,day_of_week,hour_of_day) "
               "DO UPDATE SET observation_count=observation_count+1,error_count=error_count+excluded.error_count",
               (principal, dow, hour, 1, error))
    db.execute("""
      INSERT INTO principal_daily_stats VALUES(?,?,?,?,?,?,?,?)
      ON CONFLICT(principal_name,day_start) DO UPDATE SET observation_count=observation_count+1,
        error_count=error_count+excluded.error_count
    """, (principal, day, 1, error, 0, 0, 0, 0))
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
        cursor = int(checkpoint.get("trace_id", 0))
        processed = 0
        while True:
            rows = db.execute(
                "SELECT * FROM traces WHERE id>? ORDER BY id LIMIT 10000", (cursor,)
            ).fetchall()
            if not rows:
                break
            for row in rows:
                processed += _process_incremental_row(db, row)
                cursor = row["id"]
        checkpoint["trace_id"] = cursor
        db.execute("UPDATE checkpoints SET cursor_json=?,updated_at_ms=? WHERE source='principal_intelligence'",
                   (json.dumps(checkpoint), int(time.time() * 1000)))
        return {"processed": processed, "changes": db.total_changes, "cursor": cursor,
                "bootstrap_cutoff_ms": int(checkpoint.get("bootstrap_cutoff_ms", 0))}
