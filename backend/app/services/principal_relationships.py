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
    evaluate_readiness_from_stats,
    record_historical_observation,
    record_candidate_behavior,
    detect_operation_mix_shift,
    detect_caller_principal_switch,
    detect_target_fanout_surge,
    detect_source_fanout_surge,
    detect_principal_rate_surge,
    detect_explicit_auth_anomalies,
    detect_telemetry_quality_gates,
    INCIDENT_COLUMNS,
    recalculate_incident_score,
)
from backend.app.services.normalization import _is_trusted_proxy, derive_source_group

PRINCIPAL_BATCH_SIZE = 5000


def _load_readiness_stats(db, principal_ids: list[str], cache: dict[str, Any]) -> None:
    """Load compact ingest-maintained readiness summaries once per principal/cycle."""
    missing = sorted(set(principal_ids).difference(cache))
    if not missing:
        return
    marks = ",".join("?" for _ in missing)
    rows = db.execute(
        "SELECT principal_id,minMerge(first_seen_state),maxMerge(last_seen_state),"
        "uniqExactMerge(active_days_state),countMerge(observation_count_state) "
        "FROM principal_readiness_summary "
        f"WHERE principal_id IN ({marks}) GROUP BY principal_id",
        missing,
    ).fetchall()
    cache.update({str(row[0]): tuple(row[1:5]) for row in rows})
    # Cache misses too. A principal absent from the summary cannot become present
    # during this already-fetched page, and the next worker cycle starts fresh.
    for principal_id in missing:
        cache.setdefault(principal_id, None)


def _severity(score: int) -> str:
    return "high" if score >= 30 else "medium" if score >= 20 else "low"


def _emit(db, *, principal: str, change_type: str, observed: int,
          caller: str = "", source: str = "", target: str = "",
          operation: str = "", old: str = "", new: str = "",
          reason: dict[str, Any] | None = None, recurrence: str = "",
          principal_id: str = "", _incident_cache=None, _event_rows=None,
          _override_cache=None, _defer_incident_score: bool = False) -> None:
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
        _incident_cache=_incident_cache,
        _event_rows=_event_rows,
        _override_cache=_override_cache,
        _defer_incident_score=_defer_incident_score,
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


class _BatchState:
    """Batch-local latest-row view plus block-write accumulator."""

    def __init__(self, db, rows, readiness_cache: dict[str, Any] | None = None):
        self.db = db
        self.writes: dict[tuple[str, str], list[tuple]] = {}
        self.cache: dict[tuple, Any] = {}
        self.emissions: dict[tuple, dict[str, Any]] = {}
        self.auth_windows: set[tuple[str, int]] = set()
        principal_ids = sorted({
            (row["principal_id"] or f"{row['service_environment'] or 'production'}:{row['principal_name']}")
            for row in rows if row["principal_name"] and row["principal_name"] != "unknown"
        })
        self.readiness = readiness_cache if readiness_cache is not None else {}
        _load_readiness_stats(db, principal_ids, self.readiness)
        self._preload(rows, principal_ids)

    def _preload(self, rows, principal_ids: list[str]) -> None:
        names = sorted({str(row["principal_name"]) for row in rows
                        if row["principal_name"] and row["principal_name"] != "unknown"})
        if not names:
            return
        name_marks = ",".join("?" for _ in names)
        pid_marks = ",".join("?" for _ in principal_ids)

        # Seed every key used by this page as absent, then overlay the durable FINAL rows.
        for row in rows:
            principal = str(row["principal_name"] or "")
            if not principal or principal == "unknown":
                continue
            env = str(row["service_environment"] or "production")
            pid = str(row["principal_id"] or f"{env}:{principal}")
            caller, source = str(row["caller_service"] or ""), str(row["caller_ip"] or "")
            target, operation = str(row["target_service"] or ""), str(row["operation"] or "")
            op_key = str(row["operation_key"] or operation)
            source_group = str(row["source_group"] or derive_source_group(source) or "")
            timestamp_ms = int(row["timestamp_ms"])
            logical = f"{caller}→{target}→{op_key}"
            dimensions = [("caller", caller), ("source", source), ("target", target),
                          ("operation", op_key), ("logical_relationship", logical)]
            if source_group:
                dimensions.append(("origin_relationship", f"{caller}→{source_group}→{target}→{op_key}"))
            for dim_type, value in dimensions:
                registry_key = f"{dim_type}:{pid}:{value}"
                self.cache.setdefault(("historical", registry_key), None)
            for dim_type, value in (("caller", caller), ("target", target), ("operation", op_key)):
                self.cache.setdefault(("candidate", f"{dim_type}:{pid}:{value}"), None)
            baseline_values = (("caller", caller), ("source", source), ("target", target),
                               ("operation", f"{target}→{operation}"),
                               ("relationship", f"{caller}→{source}→{target}→{operation}"),
                               ("hour", time.strftime("%w:%H", time.gmtime(timestamp_ms / 1000))))
            for dim_type, value in baseline_values:
                self.cache.setdefault(("baseline", principal, dim_type, value), None)
            self.cache.setdefault(("principal", principal), None)
            if source:
                self.cache.setdefault(("source_global", source), None)
                self.cache.setdefault(("source_pair", principal, source), None)
            for table, values in (("principal_callers", (caller,)), ("principal_sources", (source,)),
                                  ("principal_targets", (target,)), ("principal_operations", (target, operation))):
                if all(values):
                    self.cache.setdefault((table, principal, *values), None)
            relationship = (principal, caller, str(row["caller_instance"] or ""), source, target,
                            str(row["target_instance"] or ""), str(row["target_ip"] or ""),
                            int(row["target_port"] or 0), operation, str(row["http_method"] or ""))
            self.cache.setdefault(("relationship", *relationship), None)
            day = (timestamp_ms // 86_400_000) * 86_400_000
            dow, hour = map(int, time.strftime("%w %H", time.gmtime(timestamp_ms / 1000)).split())
            self.cache.setdefault(("hour", principal, dow, hour), None)
            self.cache.setdefault(("day", principal, day), None)

        for row in self.db.execute(
            f"SELECT principal_name,principal_type,first_seen,last_seen,total_requests,unique_callers,unique_sources,"
            f"unique_targets,unique_operations,created_at FROM principals FINAL WHERE principal_name IN ({name_marks})", names
        ).fetchall():
            self.cache[("principal", str(row[0]))] = list(row[1:10])
        for row in self.db.execute(
            f"SELECT principal_name,dimension_type,dimension_value FROM principal_baselines FINAL WHERE principal_name IN ({name_marks})", names
        ).fetchall():
            self.cache[("baseline", str(row[0]), str(row[1]), str(row[2]))] = [1]
        if principal_ids:
            for row in self.db.execute(
                f"SELECT registry_key,first_seen,last_seen,observation_count,created_at FROM historical_registry FINAL "
                f"WHERE principal_id IN ({pid_marks})", principal_ids
            ).fetchall():
                self.cache[("historical", str(row[0]))] = list(row[1:5])
            for row in self.db.execute(
                f"SELECT candidate_key,first_seen,last_seen,distinct_days_count,distinct_windows_count,observation_count,status,created_at "
                f"FROM candidate_behaviors FINAL WHERE principal_id IN ({pid_marks})", principal_ids
            ).fetchall():
                self.cache[("candidate", str(row[0]))] = list(row[1:8])

        table_specs = (
            ("principal_callers", "caller_service,first_seen,last_seen,observation_count"),
            ("principal_sources", "source_ip,first_seen,last_seen,observation_count"),
            ("principal_targets", "target_service,first_seen,last_seen,observation_count,error_count"),
            ("principal_operations", "target_service,operation,first_seen,last_seen,observation_count,error_count"),
        )
        for table, columns in table_specs:
            for row in self.db.execute(
                f"SELECT principal_name,{columns} FROM {table} FINAL WHERE principal_name IN ({name_marks})", names
            ).fetchall():
                key_width = 2 if table == "principal_operations" else 1
                self.cache[(table, str(row[0]), *map(str, row[1:1 + key_width]))] = list(row[1 + key_width:])
        for row in self.db.execute(
            f"SELECT principal_name,caller_service,caller_instance,source_ip,target_service,target_instance,target_ip,target_port,"
            f"operation,http_method,first_seen,last_seen,observation_count,success_count,error_count FROM principal_relationships FINAL "
            f"WHERE principal_name IN ({name_marks})", names
        ).fetchall():
            self.cache[("relationship", *tuple(row[:10]))] = list(row[10:15])
        hourly_counts: dict[str, set[int]] = {name: set() for name in names}
        for row in self.db.execute(
            f"SELECT principal_name,day_of_week,hour_of_day,observation_count,error_count FROM principal_hourly_activity FINAL "
            f"WHERE principal_name IN ({name_marks})", names
        ).fetchall():
            self.cache[("hour", str(row[0]), int(row[1]), int(row[2]))] = [int(row[3]), int(row[4])]
            hourly_counts[str(row[0])].add(int(row[2]))
        for name, hours in hourly_counts.items():
            self.cache[("active_hours", name)] = [len(hours)]
        for row in self.db.execute(
            f"SELECT principal_name,day_start,observation_count,error_count,unique_callers,unique_sources,unique_targets,unique_operations "
            f"FROM principal_daily_stats FINAL WHERE principal_name IN ({name_marks})", names
        ).fetchall():
            self.cache[("day", str(row[0]), int(row[1]))] = list(map(int, row[2:8]))
        sources = sorted({str(row["caller_ip"]) for row in rows if row["caller_ip"]})
        if sources:
            source_marks = ",".join("?" for _ in sources)
            for row in self.db.execute(
                f"SELECT principal_name,source_ip FROM principal_sources FINAL WHERE source_ip IN ({source_marks})", sources
            ).fetchall():
                self.cache[("source_global", str(row[1]))] = [1]
                self.cache[("source_pair", str(row[0]), str(row[1]))] = [1]

    def query_one(self, key: tuple, sql: str, params: tuple):
        if key not in self.cache:
            row = self.db.execute(sql, params).fetchone()
            self.cache[key] = list(row) if row else None
        return self.cache[key]

    def add(self, table: str, columns: str, values: tuple) -> None:
        self.writes.setdefault((table, columns), []).append(values)

    def ready(self, principal_id: str, detector: str, timestamp_ms: int):
        return evaluate_readiness_from_stats(self.readiness.get(principal_id), detector, timestamp_ms)

    def dimension_known(self, principal: str, dimension: str, value: str) -> bool:
        key = ("baseline", principal, dimension, value)
        return bool(self.query_one(
            key, "SELECT 1 FROM principal_baselines WHERE principal_name=? AND dimension_type=? AND dimension_value=?",
            (principal, dimension, value),
        ))

    def source_seen(self, source: str, principal: str) -> tuple[bool, bool]:
        globally = bool(self.query_one(("source_global", source),
            "SELECT 1 FROM principal_sources FINAL WHERE source_ip=? LIMIT 1", (source,)))
        together = bool(self.query_one(("source_pair", principal, source),
            "SELECT 1 FROM principal_sources FINAL WHERE principal_name=? AND source_ip=? LIMIT 1", (principal, source)))
        return globally, together

    def dimension(self, table: str, column: str, principal: str, values: tuple[str, ...],
                  timestamp_ms: int, error: int = 0) -> None:
        if not all(values):
            return
        key = (table, principal, *values)
        where = " AND ".join(f"{name}=?" for name in ("principal_name", *column.split(",")))
        has_error = table in {"principal_targets", "principal_operations"}
        selected = "first_seen,last_seen,observation_count" + (",error_count" if has_error else "")
        state = self.query_one(key, f"SELECT {selected} FROM {table} FINAL WHERE {where} LIMIT 1", (principal, *values))
        was_new = not state
        if state:
            state[0] = min(int(state[0]), timestamp_ms)
            state[1] = max(int(state[1]), timestamp_ms)
            state[2] = int(state[2]) + 1
            if has_error:
                state[3] = int(state[3]) + error
        else:
            state = [timestamp_ms, timestamp_ms, 1] + ([error] if has_error else [])
            self.cache[key] = state
        self.cache[("dimension_dirty", *key)] = (principal, *values, *state)
        if was_new:
            principal_state = self.cache.get(("principal", principal))
            count_index = {"principal_callers": 4, "principal_sources": 5,
                           "principal_targets": 6, "principal_operations": 7}.get(table)
            if principal_state is not None and count_index is not None:
                principal_state[count_index] = int(principal_state[count_index]) + 1
        if table == "principal_sources":
            self.cache[("source_global", values[0])] = [1]
            self.cache[("source_pair", principal, values[0])] = [1]

    def relationship(self, key_values: tuple, timestamp_ms: int, error: int) -> None:
        key = ("relationship", *key_values)
        columns = ("principal_name", "caller_service", "caller_instance", "source_ip", "target_service",
                   "target_instance", "target_ip", "target_port", "operation", "http_method")
        where = " AND ".join(f"{column}=?" for column in columns)
        state = self.query_one(key, f"SELECT first_seen,last_seen,observation_count,success_count,error_count "
                                    f"FROM principal_relationships FINAL WHERE {where} LIMIT 1", key_values)
        if state:
            state[:] = [min(int(state[0]), timestamp_ms), max(int(state[1]), timestamp_ms), int(state[2]) + 1,
                        int(state[3]) + 1 - error, int(state[4]) + error]
        else:
            state = [timestamp_ms, timestamp_ms, 1, 1 - error, error]
            self.cache[key] = state
        self.cache[("relationship_dirty", *key_values)] = (*key_values, *state)

    def activity(self, principal: str, timestamp_ms: int, error: int) -> None:
        day = (timestamp_ms // 86_400_000) * 86_400_000
        dow, hour = map(int, time.strftime("%w %H", time.gmtime(timestamp_ms / 1000)).split())
        hour_key = ("hour", principal, dow, hour)
        hour_state = self.query_one(hour_key, "SELECT observation_count,error_count FROM principal_hourly_activity FINAL "
                                    "WHERE principal_name=? AND day_of_week=? AND hour_of_day=?", (principal, dow, hour))
        hour_state = [int(hour_state[0]) + 1, int(hour_state[1]) + error] if hour_state else [1, error]
        self.cache[hour_key] = hour_state
        self.cache[("hour_dirty", principal, dow, hour)] = (principal, dow, hour, *hour_state)
        day_key = ("day", principal, day)
        day_state = self.query_one(day_key, "SELECT observation_count,error_count,unique_callers,unique_sources,unique_targets,unique_operations "
                                  "FROM principal_daily_stats FINAL WHERE principal_name=? AND day_start=?", (principal, day))
        day_state = [int(day_state[0]) + 1, int(day_state[1]) + error, *map(int, day_state[2:])] if day_state else [1, error, 0, 0, 0, 0]
        self.cache[day_key] = day_state
        self.cache[("day_dirty", principal, day)] = (principal, day, *day_state)

    def emit(self, **kwargs) -> None:
        # The event fingerprint is window-bounded; retaining the last observation in a
        # batch has the same FINAL state as repeatedly replacing the same fingerprint.
        key = (
            kwargs.get("principal_id") or kwargs.get("principal"), kwargs["change_type"],
            kwargs.get("caller", ""), kwargs.get("source", ""), kwargs.get("target", ""),
            kwargs.get("operation", ""), kwargs["observed"] // 900_000,
        )
        self.emissions[key] = kwargs

    def historical(self, principal_id: str, dim_type: str, value: str, timestamp_ms: int) -> None:
        key_value = f"{dim_type}:{principal_id}:{value}"
        key = ("historical", key_value)
        state = self.query_one(
            key, "SELECT first_seen,last_seen,observation_count,created_at FROM historical_registry FINAL WHERE registry_key=?",
            (key_value,),
        )
        now = int(time.time() * 1000)
        if state:
            state[:] = [min(int(state[0]), timestamp_ms), max(int(state[1]), timestamp_ms), int(state[2]) + 1, int(state[3])]
        else:
            state = [timestamp_ms, timestamp_ms, 1, now]
            self.cache[key] = state
        self.cache[("historical_dirty", key_value)] = (key_value, principal_id, dim_type, value, *state, now)

    def candidate(self, principal_id: str, dim_type: str, value: str, timestamp_ms: int) -> None:
        key_value = f"{dim_type}:{principal_id}:{value}"
        key = ("candidate", key_value)
        state = self.query_one(
            key, "SELECT first_seen,last_seen,distinct_days_count,distinct_windows_count,observation_count,status,created_at "
                 "FROM candidate_behaviors FINAL WHERE candidate_key=?", (key_value,),
        )
        now = int(time.time() * 1000)
        if state:
            state[2] = int(state[2]) + int(timestamp_ms // 86400000 > int(state[1]) // 86400000)
            state[3] = int(state[3]) + int(timestamp_ms // 900000 > int(state[1]) // 900000)
            state[4] = int(state[4]) + 1
            state[1] = timestamp_ms
            if state[2] >= 3 and state[3] >= 5:
                state[5] = "promoted"
                self.add("established_baselines", "baseline_key,principal_id,dimension_type,dimension_value,first_seen,last_seen,observation_count,distribution_share,promoted_at,promotion_reason,created_at,updated_at",
                         (key_value, principal_id, dim_type, value, state[0], timestamp_ms, state[4], 0.05, now,
                          "Promoted after 3+ days and 5+ windows support", now, now))
        else:
            state = [timestamp_ms, timestamp_ms, 1, 1, 1, "pending", now]
            self.cache[key] = state
        self.cache[("candidate_dirty", key_value)] = (key_value, principal_id, dim_type, value, *state, now)

    def flush(self) -> None:
        for key, value in self.cache.items():
            if key[0] == "historical_dirty":
                self.add("historical_registry", "registry_key,principal_id,dimension_type,dimension_value,first_seen,last_seen,observation_count,created_at,updated_at", value)
            elif key[0] == "candidate_dirty":
                self.add("candidate_behaviors", "candidate_key,principal_id,dimension_type,dimension_value,first_seen,last_seen,distinct_days_count,distinct_windows_count,observation_count,status,created_at,updated_at", value)
            elif key[0] == "dimension_dirty":
                table = key[1]
                dimension_columns = {
                    "principal_callers": "principal_name,caller_service,first_seen,last_seen,observation_count",
                    "principal_sources": "principal_name,source_ip,first_seen,last_seen,observation_count",
                    "principal_targets": "principal_name,target_service,first_seen,last_seen,observation_count,error_count",
                    "principal_operations": "principal_name,target_service,operation,first_seen,last_seen,observation_count,error_count",
                }
                self.add(table, dimension_columns[table], value)
            elif key[0] == "relationship_dirty":
                self.add("principal_relationships", "principal_name,caller_service,caller_instance,source_ip,target_service,target_instance,target_ip,target_port,operation,http_method,first_seen,last_seen,observation_count,success_count,error_count", value)
            elif key[0] == "hour_dirty":
                self.add("principal_hourly_activity", "principal_name,day_of_week,hour_of_day,observation_count,error_count", value)
            elif key[0] == "day_dirty":
                self.add("principal_daily_stats", "principal_name,day_start,observation_count,error_count,unique_callers,unique_sources,unique_targets,unique_operations", value)
            elif key[0] == "principal_dirty":
                principal = key[1]
                state = self.cache[("principal", principal)]
                self.add("principals", "principal_name,principal_type,first_seen,last_seen,total_requests,unique_callers,unique_sources,unique_targets,unique_operations,created_at,updated_at",
                         (principal, *state, int(time.time() * 1000)))
        for (table, columns), values in self.writes.items():
            placeholders = ",".join("?" for _ in columns.split(","))
            self.db.executemany(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values)
        incident_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        override_cache: dict[str, bool] = {}
        event_rows: list[tuple] = []
        override_rows = self.db.execute(
            "SELECT scope_value,expires_at FROM operator_overrides WHERE scope_type='change_rule'"
        ).fetchall()
        overrides = {str(row[0]): row[1] for row in override_rows}
        for kwargs in self.emissions.values():
            pid = kwargs.get("principal_id") or f"production:{kwargs.get('principal', '')}"
            scope_key = f"{pid}|{kwargs['change_type']}|{kwargs.get('new', '')}"
            expires_at = overrides.get(scope_key)
            override_cache[scope_key] = scope_key in overrides and (
                expires_at is None or int(expires_at) > int(kwargs["observed"])
            )
        for kwargs in self.emissions.values():
            _emit(self.db, **kwargs, _incident_cache=incident_cache, _event_rows=event_rows,
                  _override_cache=override_cache, _defer_incident_score=True)
        if event_rows:
            event_columns = (
                "id,fingerprint,principal_name,change_type,severity,score,detected_at,caller_service,source_ip,"
                "target_service,operation,old_value,new_value,first_observed,reason_json,status,updated_at,incident_id,"
                "principal_id,environment,base_importance,category,family,reliability"
            )
            self.db.executemany(
                f"INSERT INTO principal_change_events ({event_columns}) VALUES ({','.join('?' for _ in event_columns.split(','))})",
                event_rows,
            )
        if incident_cache:
            incident_columns = ",".join(INCIDENT_COLUMNS)
            self.db.executemany(
                f"INSERT INTO incidents ({incident_columns}) VALUES ({','.join('?' for _ in INCIDENT_COLUMNS)})",
                [tuple(incident.get(column) for column in INCIDENT_COLUMNS) for incident in incident_cache.values()],
            )
            for incident in incident_cache.values():
                recalculate_incident_score(self.db, incident["incident_id"])
        for principal_id, window_end in self.auth_windows:
            detect_explicit_auth_anomalies(self.db, principal_id, window_end - 900_000, window_end + 1)


def _process_incremental_row(db, row, batch: _BatchState | None = None) -> int:
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
    record_history = batch.historical if batch else lambda *args: record_historical_observation(db, *args)
    emit = batch.emit if batch else lambda **kwargs: _emit(db, **kwargs)
    readiness = batch.ready if batch else lambda pid, detector, ts: evaluate_readiness(db, pid, detector, ts)
    record_history(principal_id, "caller", caller, timestamp_ms)
    record_history(principal_id, "source", source, timestamp_ms)
    record_history(principal_id, "target", target, timestamp_ms)
    record_history(principal_id, "operation", op_key, timestamp_ms)
    logical_rel = f"{caller}→{target}→{op_key}"
    record_history(principal_id, "logical_relationship", logical_rel, timestamp_ms)
    if src_group:
        origin_rel = f"{caller}→{src_group}→{target}→{op_key}"
        record_history(principal_id, "origin_relationship", origin_rel, timestamp_ms)

    principal_key = ("principal", principal)
    existing = batch.query_one(principal_key, "SELECT principal_type,first_seen,last_seen,total_requests,unique_callers,unique_sources,"
                               "unique_targets,unique_operations,created_at FROM principals FINAL WHERE principal_name=?", (principal,)) if batch else db.execute(
        "SELECT principal_type,first_seen,last_seen,total_requests,unique_callers,unique_sources,unique_targets,unique_operations,created_at FROM principals FINAL WHERE principal_name=?", (principal,)).fetchone()
    is_new = existing is None

    # Track novelty flags to avoid duplicate scoring
    is_caller_new = False
    is_target_new = False
    is_op_new = False

    if is_new:
        emit(principal=principal, principal_id=principal_id, change_type="USERNAME_FIRST_SEEN", observed=timestamp_ms,
              caller=caller, source=source, target=target, operation=operation,
              new=principal, recurrence=str(timestamp_ms // 86_400_000))
    elif timestamp_ms - existing[2] >= settings.principal_dormant_days * 86_400_000:
        ready, _ = readiness(principal_id, "DORMANT_REACTIVATED", timestamp_ms)
        if ready:
            days = (timestamp_ms - existing[2]) // 86_400_000
            emit(principal=principal, principal_id=principal_id, change_type="DORMANT_REACTIVATED", observed=timestamp_ms,
                  old=f"inactive {days} days", new="active", recurrence=str(timestamp_ms // 86_400_000),
                  reason={"summary": f"{principal} became active after {days} inactive days."})

    # Dedicated source host accessed by novel user (excluding shared proxies / gateways)
    if source and source not in {"unknown", ""} and not _is_trusted_proxy(source):
        if batch:
            ip_globally_known, already_seen_together = batch.source_seen(source, principal)
        else:
            ip_globally_known = db.execute("SELECT 1 FROM principal_sources WHERE source_ip=? LIMIT 1", (source,)).fetchone()
            already_seen_together = db.execute(
                "SELECT 1 FROM principal_sources WHERE principal_name=? AND source_ip=?", (principal, source)
            ).fetchone()
        if ip_globally_known and not (batch.dimension_known(principal, "source", source) if batch else _dimension_known(db, principal, "source", source)):
            if not already_seen_together:
                ready, _ = readiness(principal_id, "NEW_PRINCIPAL_ON_SOURCE", timestamp_ms)
                if ready:
                    emit(principal=principal, principal_id=principal_id, change_type="NEW_PRINCIPAL_ON_SOURCE", observed=timestamp_ms,
                          caller=caller, source=source, target=target, operation=operation, new=principal,
                          reason={"summary": f"Host {source} was accessed by novel user {principal}."})

    # Detector readiness-guarded novelty checks
    if caller and not (batch.dimension_known(principal, "caller", caller) if batch else _dimension_known(db, principal, "caller", caller)):
        ready, _ = readiness(principal_id, "NEW_CALLER", timestamp_ms)
        if ready:
            emit(principal=principal, principal_id=principal_id, change_type="NEW_CALLER", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=caller)
            is_caller_new = True

    if source and not (batch.dimension_known(principal, "source", source) if batch else _dimension_known(db, principal, "source", source)):
        ready, _ = readiness(principal_id, "NEW_SOURCE_IP", timestamp_ms)
        if ready:
            emit(principal=principal, principal_id=principal_id, change_type="NEW_SOURCE_IP", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=source)

    if target and not (batch.dimension_known(principal, "target", target) if batch else _dimension_known(db, principal, "target", target)):
        ready, _ = readiness(principal_id, "NEW_TARGET", timestamp_ms)
        if ready:
            emit(principal=principal, principal_id=principal_id, change_type="NEW_TARGET", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=target)
            is_target_new = True

    op_dim = f"{target}→{operation}"
    if operation and not (batch.dimension_known(principal, "operation", op_dim) if batch else _dimension_known(db, principal, "operation", op_dim)):
        ready, _ = readiness(principal_id, "NEW_OPERATION", timestamp_ms)
        if ready:
            emit(principal=principal, principal_id=principal_id, change_type="NEW_OPERATION", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=operation)
            is_op_new = True

    # Logical relationship novelty
    rel_dim = f"{caller}→{source}→{target}→{operation}"
    if not (batch.dimension_known(principal, "relationship", rel_dim) if batch else _dimension_known(db, principal, "relationship", rel_dim)):
        ready, _ = readiness(principal_id, "NEW_RELATIONSHIP", timestamp_ms)
        # Score NEW_RELATIONSHIP only when constituent dimensions are already known
        if ready and not (is_caller_new or is_target_new or is_op_new):
            emit(principal=principal, principal_id=principal_id, change_type="NEW_RELATIONSHIP", observed=timestamp_ms,
                  caller=caller, source=source, target=target, operation=operation, new=rel_dim)

    # Circadian unusual time check
    day_hour = time.strftime("%w:%H", time.gmtime(timestamp_ms / 1000))
    if not (batch.dimension_known(principal, "hour", day_hour) if batch else _dimension_known(db, principal, "hour", day_hour)):
        ready, _ = readiness(principal_id, "UNUSUAL_TIME", timestamp_ms)
        if ready:
            active_hours = (batch.query_one(
                ("active_hours", principal),
                "SELECT COUNT(DISTINCT hour_of_day) FROM principal_hourly_activity FINAL WHERE principal_name = ?",
                (principal,),
            )[0] if batch else db.execute(
                "SELECT COUNT(DISTINCT hour_of_day) FROM principal_hourly_activity WHERE principal_name = ?", (principal,)
            ).fetchone()[0])
            # Only alert if account is diurnal/periodic, not continuous 24h
            if active_hours <= 18:
                emit(principal=principal, principal_id=principal_id, change_type="UNUSUAL_TIME", observed=timestamp_ms,
                      caller=caller, source=source, target=target, operation=operation, new=day_hour,
                      recurrence=str(timestamp_ms // 3_600_000))

    # Check explicit authentication outcomes
    if "auth_result" in row.keys() and row["auth_result"] == "failure":
        if batch:
            batch.auth_windows.add((principal_id, timestamp_ms))
        else:
            detect_explicit_auth_anomalies(db, principal_id, timestamp_ms - 900_000, timestamp_ms + 1)

    # Update candidate behaviors
    if batch:
        batch.candidate(principal_id, "caller", caller, timestamp_ms)
        batch.candidate(principal_id, "target", target, timestamp_ms)
        batch.candidate(principal_id, "operation", op_key, timestamp_ms)
    else:
        record_candidate_behavior(db, principal_id, "caller", caller, timestamp_ms, timestamp_ms // 900000)
        record_candidate_behavior(db, principal_id, "target", target, timestamp_ms, timestamp_ms // 900000)
        record_candidate_behavior(db, principal_id, "operation", op_key, timestamp_ms, timestamp_ms // 900000)

    now = int(time.time() * 1000)
    error = int((row["http_status"] or 0) >= 400 or row["outcome"] == "failure")
    if batch:
        if existing:
            existing[:] = [existing[0], min(int(existing[1]), timestamp_ms), max(int(existing[2]), timestamp_ms),
                           int(existing[3]) + 1, *existing[4:]]
        else:
            existing = ["unknown", timestamp_ms, timestamp_ms, 1, 0, 0, 0, 0, now]
            batch.cache[principal_key] = existing
        batch.cache[("principal_dirty", principal)] = (
            principal, existing[0], existing[1], existing[2], existing[3], existing[4], existing[5],
            existing[6], existing[7], existing[8], now,
        )
        batch.dimension("principal_callers", "caller_service", principal, (caller,), timestamp_ms)
        batch.dimension("principal_sources", "source_ip", principal, (source,), timestamp_ms)
        batch.dimension("principal_targets", "target_service", principal, (target,), timestamp_ms, error)
        batch.dimension("principal_operations", "target_service,operation", principal, (target, operation), timestamp_ms, error)
    else:
        if existing:
            db.execute("INSERT INTO principals(principal_name,principal_type,first_seen,last_seen,total_requests,unique_callers,"
                       "unique_sources,unique_targets,unique_operations,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (principal, existing[0], min(int(existing[1]), timestamp_ms), max(int(existing[2]), timestamp_ms),
                        int(existing[3]) + 1, existing[4], existing[5], existing[6], existing[7], existing[8], now))
        else:
            db.execute("INSERT INTO principals(principal_name,principal_type,first_seen,last_seen,total_requests,created_at,updated_at) "
                       "VALUES(?,'unknown',?,?,1,?,?)", (principal, timestamp_ms, timestamp_ms, now, now))
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
    prior_relationship = None if batch else db.execute(
        f"SELECT first_seen,last_seen,observation_count,success_count,error_count FROM principal_relationships FINAL "
        f"WHERE {relationship_where} LIMIT 1", relationship_key).fetchone()
    if batch:
        batch.relationship(relationship_key, timestamp_ms, error)
    elif prior_relationship:
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
    prior_hour = None if batch else db.execute("SELECT observation_count,error_count FROM principal_hourly_activity FINAL WHERE principal_name=? AND day_of_week=? AND hour_of_day=?", (principal, dow, hour)).fetchone()
    if batch:
        batch.activity(principal, timestamp_ms, error)
    elif prior_hour:
        db.execute("INSERT INTO principal_hourly_activity VALUES(?,?,?,?,?)",
                   (principal, dow, hour, int(prior_hour[0]) + 1, int(prior_hour[1]) + error))
    else:
        db.execute("INSERT INTO principal_hourly_activity VALUES(?,?,?,?,?)", (principal, dow, hour, 1, error))
    prior_day = None if batch else db.execute("SELECT observation_count,error_count,unique_callers,unique_sources,unique_targets,unique_operations "
                           "FROM principal_daily_stats FINAL WHERE principal_name=? AND day_start=?", (principal, day)).fetchone()
    if batch:
        pass
    elif prior_day:
        db.execute("INSERT INTO principal_daily_stats VALUES(?,?,?,?,?,?,?,?)",
                   (principal, day, int(prior_day[0]) + 1, int(prior_day[1]) + error,
                    int(prior_day[2]), int(prior_day[3]), int(prior_day[4]), int(prior_day[5])))
    else:
        db.execute("INSERT INTO principal_daily_stats VALUES(?,?,?,?,?,?,?,?)", (principal, day, 1, error, 0, 0, 0, 0))
    if not batch:
        _refresh_principal_counts(db, principal)
    return 1


def process_principal_intelligence(db_path: Optional[str] = None) -> dict[str, int]:
    stage_started = time.monotonic()
    with db_transaction(db_path) as db:
        checkpoint_row = db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source='principal_intelligence'"
        ).fetchone()
        if not checkpoint_row:
            return _bootstrap(db, settings.principal_bootstrap_ratio)
        checkpoint = json.loads(checkpoint_row[0])
        cursor_order = int(checkpoint.get("ingest_order", 0))
        cursor_uid = str(checkpoint.get("row_uid", "00000000-0000-0000-0000-000000000000"))
        processed = 0
        readiness_cache: dict[str, Any] = {}
        while True:
            rows = db.execute(
                "SELECT ingest_order,row_uid,timestamp_ms,principal_name,"
                "service_environment,principal_id,operation_key,source_group,caller_service,caller_ip,"
                "target_service,operation,auth_result,http_status,outcome,caller_instance,target_instance,"
                "target_ip,target_port,http_method FROM traces "
                "WHERE (ingest_order,row_uid)>(?,toUUID(?)) "
                "ORDER BY ingest_order,row_uid LIMIT ?", (cursor_order, cursor_uid, PRINCIPAL_BATCH_SIZE)
            ).fetchall()
            if not rows:
                break
            batch = _BatchState(db, rows, readiness_cache)
            for row in rows:
                processed += _process_incremental_row(db, row, batch)
            # No derived statement is issued until the whole page has been computed.
            # Once all block inserts return, the page cursor is durable and can advance.
            batch.flush()
            cursor_order = int(rows[-1]["ingest_order"])
            cursor_uid = str(rows[-1]["row_uid"])
            checkpoint["ingest_order"] = cursor_order
            checkpoint["row_uid"] = cursor_uid
            db.execute(
                "INSERT INTO checkpoints(source,cursor_json,updated_at_ms) VALUES('principal_intelligence',?,?)",
                (json.dumps(checkpoint), int(time.time() * 1000)),
            )
            if time.monotonic() - stage_started >= settings.analytics_stage_budget_seconds:
                break
        return {"processed": processed, "changes": db.total_changes, "cursor": cursor_order,
                "bootstrap_cutoff_ms": int(checkpoint.get("bootstrap_cutoff_ms", 0))}
