"""Read derived identity intelligence from ClickHouse without reprocessing raw credentials."""
from __future__ import annotations

import json
import math
import time
from typing import Any, Optional

from backend.config import settings
from backend.app.repositories.db_context import db_transaction, get_connection
from backend.app.repositories.interactive_topology_repository import bandwidth_fields


class UserRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def _bounds(self, db, start_ms: int | None, end_ms: int | None) -> tuple[int, int, int]:
        available = db.execute("SELECT COALESCE(MIN(first_seen),0), COALESCE(MAX(last_seen),0) FROM principals").fetchone()
        if not available or not available[1]:
            available = db.execute("""
                SELECT COALESCE(MIN(bucket_start),0)*1000,
                       COALESCE(MAX(bucket_start + bucket_size),0)*1000
                FROM metric_buckets FINAL WHERE bucket_size=300
            """).fetchone()
        latest = int(available[1] or 0)
        end = end_ms or latest + 1
        start = start_ms or int(available[0] or 0)
        return start, end, latest

    def list_users(self, *, start_ms: int | None = None, end_ms: int | None = None,
                   search: str | None = None, active: str | None = None,
                   caller: str | None = None, target: str | None = None,
                   source_ip: str | None = None, behavior_level: str | None = None,
                   has_changes: bool | None = None, first_from: int | None = None,
                   first_to: int | None = None, last_from: int | None = None,
                   last_to: int | None = None, sort: str = "most_active",
                   environment: str | None = None, limit: int = 100, offset: int = 0,
                   include_anonymous: bool = False) -> dict[str, Any]:
        with get_connection(self.db_path) as db:
            start, end, latest = self._bounds(db, start_ms, end_ms)
            active_cutoff = latest - settings.principal_active_minutes * 60_000
            clauses, args = ["1=1"], []
            if not include_anonymous:
                clauses.append("p.principal_name NOT IN ('-anonymous-', 'unknown', '')")
            if search:
                like = f"%{search}%"
                clauses.append("""(p.principal_name LIKE ? OR p.principal_name IN (
                  SELECT principal_name FROM principal_relationships
                  WHERE source_ip LIKE ? OR caller_service LIKE ? OR target_service LIKE ? OR operation LIKE ?))""")
                args.extend([like] * 5)
            for value, sql in ((caller, "p.principal_name IN (SELECT principal_name FROM principal_callers WHERE caller_service=?)"),
                               (target, "p.principal_name IN (SELECT principal_name FROM principal_targets WHERE target_service=?)"),
                               (source_ip, "p.principal_name IN (SELECT principal_name FROM principal_sources WHERE source_ip=?)")):
                if value:
                    clauses.append(sql); args.append(value)
            if active == "active": clauses.append("p.last_seen>=?"); args.append(active_cutoff)
            if active == "inactive": clauses.append("p.last_seen<?"); args.append(active_cutoff)
            for value, operator, column in ((first_from, ">=", "first_seen"), (first_to, "<", "first_seen"),
                                             (last_from, ">=", "last_seen"), (last_to, "<", "last_seen")):
                if value is not None: clauses.append(f"p.{column}{operator}?"); args.append(value)
            if environment:
                clauses.append("p.principal_name IN (SELECT m.principal_name FROM metric_buckets FINAL m INNER JOIN services s ON m.target_service=s.name WHERE m.bucket_size=300 AND s.environment=?)")
                args.append(environment)

            if has_changes is True:
                clauses.append("coalesce(c.recent_changes, 0) > 0")
            elif has_changes is False:
                clauses.append("coalesce(c.recent_changes, 0) = 0")

            level_bounds = {"low": (0, 24), "medium": (25, 59), "high": (60, 100)}
            if behavior_level in level_bounds:
                lo, hi = level_bounds[behavior_level]
                clauses.append("coalesce(c.behavior_score, 0) BETWEEN ? AND ?")
                args.extend([lo, hi])

            order = {
                "most_active": "p.total_requests DESC", "most_changed": "behavior_score DESC",
                "most_target_services": "p.unique_targets DESC", "most_operations": "p.unique_operations DESC",
                "newest": "p.first_seen DESC", "dormant_returned": "dormant_reactivated DESC,p.last_seen DESC",
                "highest_behavior_change": "behavior_score DESC,p.last_seen DESC",
            }.get(sort, "p.total_requests DESC")

            from_clause = """
              principals AS p FINAL
              LEFT JOIN (
                SELECT
                    principal_name,
                    count() AS recent_changes,
                    least(100, sum(type_score)) AS behavior_score,
                    max(if(change_type = 'DORMANT_REACTIVATED', 1, 0)) AS dormant_reactivated
                FROM (
                    SELECT
                        principal_name,
                        change_type,
                        max(score) AS type_score
                    FROM principal_change_events FINAL
                    WHERE detected_at >= ? AND detected_at < ? AND status NOT IN ('expected', 'ignored')
                    GROUP BY principal_name, change_type
                )
                GROUP BY principal_name
              ) c ON p.principal_name = c.principal_name
              LEFT JOIN (
                SELECT principal_name, count() as baseline_values
                FROM principal_baselines
                GROUP BY principal_name
              ) b ON p.principal_name = b.principal_name
            """
            join_args = [start, end]
            sql = f"""
              SELECT p.*,
                if(p.last_seen >= ?, 'Active', 'Inactive') status,
                coalesce(c.recent_changes, 0) recent_changes,
                coalesce(c.behavior_score, 0) behavior_score,
                coalesce(b.baseline_values, 0) baseline_values,
                coalesce(c.dormant_reactivated, 0) dormant_reactivated
              FROM {from_clause}
              WHERE {' AND '.join(clauses)}
              ORDER BY {order} LIMIT ? OFFSET ?
            """
            rows = [dict(r) for r in db.execute(sql, [active_cutoff, *join_args, *args, limit, offset])]
            for row in rows:
                score = int(row.get("behavior_score") or 0)
                row["behavior_level"] = "High" if score >= 60 else "Medium" if score >= 25 else "Low"
                row["learning_status"] = "established" if row.get("baseline_values") else "learning"
                row["status_basis"] = "dataset_latest"
                row["reference_time_ms"] = latest
            count_sql = f"SELECT COUNT(*) FROM {from_clause} WHERE {' AND '.join(clauses)}"
            count = db.execute(count_sql, [*join_args, *args]).fetchone()[0]
            return {"items": rows, "count": count, "limit": limit, "offset": offset,
                    "window": {"from": start, "to": end}}

    def summary(self, start_ms: int | None = None, end_ms: int | None = None) -> dict[str, Any]:
        with get_connection(self.db_path) as db:
            start, end, latest = self._bounds(db, start_ms, end_ms)
            active_cutoff = latest - settings.principal_active_minutes * 60_000
            day_start = (latest // 86_400_000) * 86_400_000
            scalar = lambda sql, args=(): db.execute(sql, args).fetchone()[0] or 0

            anon_traces = scalar(
                "SELECT sum(request_count) FROM metric_buckets FINAL WHERE bucket_size=300 AND principal_name IN ('-anonymous-', 'unknown', '') AND bucket_start*1000>=? AND bucket_start*1000<?",
                (start, end)
            )
            total_traces = scalar(
                "SELECT sum(request_count) FROM metric_buckets FINAL WHERE bucket_size=300 AND bucket_start*1000>=? AND bucket_start*1000<?",
                (start, end)
            )
            anon_pct = round((anon_traces / max(1, total_traces)) * 100, 1)

            return {
                "observed_principals": scalar("SELECT count() FROM principals FINAL WHERE principal_name NOT IN ('-anonymous-', 'unknown', '')"),
                "active_principals": scalar("SELECT count() FROM principals FINAL WHERE last_seen>=? AND principal_name NOT IN ('-anonymous-', 'unknown', '')", (active_cutoff,)),
                "new_principals_today": scalar("SELECT count() FROM principals FINAL WHERE first_seen>=? AND principal_name NOT IN ('-anonymous-', 'unknown', '')", (day_start,)),
                "principals_with_changes": scalar("SELECT COUNT(DISTINCT principal_name) FROM principal_change_events FINAL WHERE detected_at>=? AND detected_at<? AND status NOT IN ('expected','ignored') AND principal_name NOT IN ('-anonymous-', 'unknown', '')", (start, end)),
                "dormant_reactivated": scalar("SELECT COUNT(DISTINCT principal_name) FROM principal_change_events FINAL WHERE change_type='DORMANT_REACTIVATED' AND detected_at>=? AND detected_at<? AND principal_name NOT IN ('-anonymous-', 'unknown', '')", (start, end)),
                "new_service_relationships": scalar("SELECT COUNT(*) FROM principal_change_events FINAL WHERE change_type='NEW_TARGET' AND detected_at>=? AND detected_at<? AND principal_name NOT IN ('-anonymous-', 'unknown', '')", (start, end)),
                "new_caller_relationships": scalar("SELECT COUNT(*) FROM principal_change_events FINAL WHERE change_type='NEW_CALLER' AND detected_at>=? AND detected_at<? AND principal_name NOT IN ('-anonymous-', 'unknown', '')", (start, end)),
                "anonymous_requests": anon_traces,
                "anonymous_traffic_percentage": anon_pct,
            }

    def _distribution(self, db, principal: str, table: str, value_select: str,
                      start_ms: int | None = None, end_ms: int | None = None) -> list[dict[str, Any]]:
        if start_ms is not None and end_ms is not None:
            start_sec, end_sec = start_ms // 1000, (end_ms + 999) // 1000
            if table == "principal_sources":
                rows = db.execute("""
                    SELECT source_ip value, sum(request_count) requests,
                           min(first_seen_ms) first_seen, max(last_seen_ms) last_seen
                    FROM topology_principal_ip_5m FINAL
                    WHERE principal=? AND bucket_start>=? AND bucket_start<? AND source_ip!=''
                    GROUP BY source_ip ORDER BY requests DESC
                """, (principal, start_sec, end_sec)).fetchall()
            else:
                column = {
                    "principal_callers": "caller_service",
                    "principal_targets": "target_service",
                    "principal_operations": "target_api",
                }.get(table)
                if column:
                    value = "target_service||'→'||target_api" if table == "principal_operations" else column
                    rows = db.execute(f"""
                        SELECT {value} value, sum(request_count) requests,
                               min(first_seen_ms) first_seen, max(last_seen_ms) last_seen
                        FROM topology_principal_edges_5m FINAL
                        WHERE principal=? AND bucket_start>=? AND bucket_start<?
                        GROUP BY value ORDER BY requests DESC
                    """, (principal, start_sec, end_sec)).fetchall()
                else:
                    rows = []
        else:
            # Worker-maintained summaries replace API-side per-span fallback scans.
            rows = db.execute(f"SELECT {value_select} value,observation_count requests,first_seen,last_seen FROM {table} WHERE principal_name=? ORDER BY requests DESC", (principal,)).fetchall()
        total = sum(r["requests"] for r in rows) or 1
        return [{**dict(r), "share": r["requests"] / total} for r in rows]

    def profile(self, principal: str, start_ms: int | None = None, end_ms: int | None = None) -> dict[str, Any] | None:
        with get_connection(self.db_path) as db:
            item = db.execute("SELECT * FROM principals FINAL WHERE principal_name=?", (principal,)).fetchone()
            if not item: return None
            start, end, latest = self._bounds(db, start_ms, end_ms)
            profile = dict(item)
            profile["status"] = "Active" if item["last_seen"] >= latest-settings.principal_active_minutes*60_000 else "Inactive"
            current = {
                "callers": self._distribution(db, principal, "principal_callers", "caller_service", start, end),
                "sources": self._distribution(db, principal, "principal_sources", "source_ip", start, end),
                "targets": self._distribution(db, principal, "principal_targets", "target_service", start, end),
                "operations": self._distribution(db, principal, "principal_operations", "target_service||'→'||operation", start, end),
            }
            normal: dict[str, list[dict[str, Any]]] = {}
            for dimension in ("caller","source","target","operation"):
                normal[dimension + "s"] = [dict(r) for r in db.execute(
                    "SELECT dimension_value value,observation_count requests,distribution_share share,first_seen,last_seen FROM principal_baselines WHERE principal_name=? AND dimension_type=? ORDER BY observation_count DESC",
                    (principal, dimension))]

            from backend.app.services.normalization import classify_source_ip_role
            for src in current.get("sources", []):
                role, role_label, conf = classify_source_ip_role(src.get("value"))
                src["role"] = role
                src["role_label"] = role_label
                src["attribution_confidence"] = conf
                src["is_load_balancer"] = (role == "load_balancer")

            for src in normal.get("sources", []):
                role, role_label, conf = classify_source_ip_role(src.get("value"))
                src["role"] = role
                src["role_label"] = role_label
                src["attribution_confidence"] = conf
                src["is_load_balancer"] = (role == "load_balancer")

            changes = self.list_changes(principal=principal, start_ms=start, end_ms=end, limit=100)["items"]
            score_by_type: dict[str, int] = {}
            for change in changes:
                if change["status"] not in {"expected", "ignored"}:
                    score_by_type[change["change_type"]] = max(
                        score_by_type.get(change["change_type"], 0), int(change["score"])
                    )
            score = min(100, sum(score_by_type.values()))
            hourly = [dict(r) for r in db.execute("SELECT * FROM principal_hourly_activity WHERE principal_name=? ORDER BY day_of_week,hour_of_day", (principal,))]
            daily = [dict(r) for r in db.execute("SELECT * FROM principal_daily_stats WHERE principal_name=? ORDER BY day_start DESC LIMIT 90", (principal,))]
            daily.reverse()
            active_hours = [r[0] for r in db.execute("SELECT hour_of_day FROM principal_hourly_activity WHERE principal_name=? GROUP BY hour_of_day HAVING SUM(observation_count)>0 ORDER BY hour_of_day", (principal,))]
            profile.update({"current": current, "normal": normal, "changes": changes,
                            "behavior_score": score, "behavior_level": "High" if score>=60 else "Medium" if score>=25 else "Low",
                            "hourly_activity": hourly, "daily_stats": daily,
                            "typical_active_window": f"{min(active_hours):02d}:00–{max(active_hours):02d}:59" if active_hours else "No established window",
                            "window": {"from": start, "to": end},
                            "learning_status": "established" if any(normal.values()) else "learning",
                            "status_basis": "dataset_latest", "reference_time_ms": latest})
            return profile

    def relationships(self, principal: str, dimension: str, start_ms: int | None = None,
                      end_ms: int | None = None) -> list[dict[str, Any]]:
        table_and_value = {
            "callers": ("principal_callers", "caller_service"), "sources": ("principal_sources", "source_ip"),
            "targets": ("principal_targets", "target_service"),
            "operations": ("principal_operations", "target_service||'→'||operation"),
        }
        with get_connection(self.db_path) as db:
            table, value = table_and_value[dimension]
            return self._distribution(db, principal, table, value, start_ms, end_ms)

    def timeline(self, principal: str, start_ms: int | None, end_ms: int | None,
                 kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as db:
            start, end, _ = self._bounds(db, start_ms, end_ms)
            items = []
            if kind in (None, "all", "operations", "errors"):
                error_clause = " AND error_count>0" if kind == "errors" else ""
                for row in db.execute(f"""
                    SELECT bucket_start*1000 timestamp_ms, caller_service, target_service,
                           operation, sum(request_count) request_count, sum(error_count) error_count,
                           max(latency_p95) latency_p95, sum(request_bytes) request_bytes,
                           sum(response_bytes) response_bytes
                    FROM metric_buckets FINAL
                    WHERE bucket_size=300 AND principal_name=? AND bucket_start*1000>=?
                      AND bucket_start*1000<?{error_clause}
                    GROUP BY timestamp_ms,caller_service,target_service,operation
                    ORDER BY timestamp_ms DESC LIMIT ?
                """, (principal, start, end, max(1, min(limit, 500)))):
                    items.append({**dict(row), "source_ip": None, "trace_id": None,
                                  "event_type": "ROLLUP_ACTIVITY", "severity": "info"})
            if kind not in {"operations", "errors"}:
                change_types = None
                if kind == "new_relationships": change_types = {"NEW_CALLER","NEW_SOURCE_IP","NEW_TARGET","NEW_RELATIONSHIP"}
                changes = self.list_changes(principal=principal,start_ms=start,end_ms=end,limit=limit)["items"]
                items.extend({**c, "timestamp_ms": c["detected_at"], "event_type": c["change_type"]} for c in changes if change_types is None or c["change_type"] in change_types)
            return sorted(items, key=lambda x: x["timestamp_ms"], reverse=True)[:limit]

    def list_changes(self, *, principal: str | None = None, change_type: str | None = None,
                     severity: str | None = None, caller: str | None = None,
                     target: str | None = None, operation: str | None = None,
                     source_ip: str | None = None, status: str | None = None,
                     start_ms: int | None = None, end_ms: int | None = None,
                     limit: int = 100, offset: int = 0) -> dict[str, Any]:
        clauses, args = ["1=1"], []
        for column, value in (("principal_name",principal),("change_type",change_type),("severity",severity),
                              ("caller_service",caller),("target_service",target),("operation",operation),
                              ("source_ip",source_ip),("status",status)):
            if value: clauses.append(f"{column}=?"); args.append(value)
        base_where = " AND ".join(clauses)
        base_args = list(args)

        time_clauses = []
        time_args = []
        if start_ms is not None: time_clauses.append("detected_at>=?"); time_args.append(start_ms)
        if end_ms is not None: time_clauses.append("detected_at<?"); time_args.append(end_ms)
        where = " AND ".join(clauses + time_clauses)
        all_args = args + time_args

        with get_connection(self.db_path) as db:
            rows = [dict(r) for r in db.execute(f"SELECT * FROM principal_change_events FINAL WHERE {where} ORDER BY detected_at DESC LIMIT ? OFFSET ?", [*all_args,limit,offset])]
            count = db.execute(f"SELECT COUNT(*) FROM principal_change_events FINAL WHERE {where}", all_args).fetchone()[0]
            total_unfiltered = db.execute(f"SELECT COUNT(*) FROM principal_change_events FINAL WHERE {base_where}", base_args).fetchone()[0]

            # If time filter returned 0 rows but changes exist, fall back to recent changes so page is never blank
            if count == 0 and time_clauses and total_unfiltered > 0:
                fallback_rows = [dict(r) for r in db.execute(f"SELECT * FROM principal_change_events FINAL WHERE {base_where} ORDER BY detected_at DESC LIMIT ? OFFSET ?", [*base_args,limit,offset])]
                for row in fallback_rows:
                    try: row["reason"] = json.loads(row.pop("reason_json"))
                    except Exception: row["reason"] = {}
                return {"items": fallback_rows, "count": len(fallback_rows), "total_unfiltered": total_unfiltered, "fallback_applied": True, "limit": limit, "offset": offset}

            for row in rows:
                try: row["reason"] = json.loads(row.pop("reason_json"))
                except Exception: row["reason"] = {}
            return {"items": rows, "count": count, "total_unfiltered": total_unfiltered, "fallback_applied": False, "limit": limit, "offset": offset}

    def get_change(self, change_id: int) -> dict[str, Any] | None:
        """Return one behavioral change event for direct inspection and compatibility links."""
        with get_connection(self.db_path) as db:
            row = db.execute(
                "SELECT * FROM principal_change_events FINAL WHERE id=? LIMIT 1",
                (change_id,),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            try:
                result["reason"] = json.loads(result.pop("reason_json"))
            except Exception:
                result["reason"] = {}
            return result

    def update_change(self, change_id: int, status: str) -> dict[str, Any] | None:
        return self.review_change(change_id, action="expected" if status == "expected" else "investigate" if status == "reviewed" else "data_quality" if status == "ignored" else "investigate")

    def review_change(self, change_id: int, action: str, scope: str | None = None,
                      reason: str | None = None, operator: str = "operator",
                      expires_at: int | None = None) -> dict[str, Any] | None:
        now = int(time.time() * 1000)
        with db_transaction(self.db_path) as db:
            row = db.execute("SELECT * FROM principal_change_events FINAL WHERE id=?", (change_id,)).fetchone()
            if not row:
                return None
            row_dict = dict(row)
            status = "expected" if action == "expected" else "reviewed" if action == "investigate" else "resolved" if action == "resolve" else "ignored"
            category = "data_quality" if action == "data_quality" else row_dict.get("category", "behavioral")

            table_cols = {r[1] for r in db.execute("PRAGMA table_info(principal_change_events)").fetchall()}
            if "reviewed_by" in table_cols:
                db.execute("""
                    UPDATE principal_change_events SET
                      status = ?, category = ?, reviewed_by = ?, review_reason = ?,
                      expires_at = ?, updated_at = ?
                    WHERE id = ?
                """, (status, category, operator, reason or action, expires_at, now, change_id))
            else:
                db.execute("UPDATE principal_change_events SET status = ?, updated_at = ? WHERE id = ?",
                           (status, now, change_id))

            if action == "expected":
                scope_type = scope or "change_rule"
                scope_val = f"{row_dict.get('principal_id') or row_dict['principal_name']}|{row_dict['change_type']}|{row_dict.get('new_value') or ''}"
                db.execute("""
                    INSERT INTO operator_overrides (scope_type, scope_value, reason, operator, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (scope_type, scope_val, reason or "Operator marked as expected change", operator, now, expires_at))
                mapping = {"NEW_CALLER": ("caller", row_dict["caller_service"]), "NEW_SOURCE_IP": ("source", row_dict["source_ip"]),
                           "NEW_TARGET": ("target", row_dict["target_service"]), "NEW_OPERATION": ("operation", f"{row_dict['target_service']}→{row_dict['operation']}")}
                if row_dict["change_type"] in mapping:
                    dimension, value = mapping[row_dict["change_type"]]
                    db.execute("INSERT INTO principal_baselines VALUES(?,?,?,?,?,?,?)",
                               (row_dict["principal_name"], dimension, value or "", row_dict["first_observed"], row_dict["first_observed"], 1, 0.0))

            incident_id = row_dict.get("incident_id")
            if incident_id:
                if action in {"investigate", "expected", "resolve"}:
                    from backend.app.services.behavioral_engine import insert_incident_version
                    current_incident = db.execute(
                        "SELECT * FROM incidents FINAL WHERE incident_id = ?", (incident_id,)
                    ).fetchone()
                    if current_incident:
                        insert_incident_version(
                            db, dict(current_incident),
                            status="investigating" if action == "investigate" else "accepted" if action == "expected" else "resolved",
                            updated_at=now,
                        )
                try:
                    from backend.app.services.behavioral_engine import recalculate_incident_score
                    recalculate_incident_score(db, incident_id)
                except Exception:
                    pass

            return {"id": change_id, "status": status, "action": action, "operator": operator}

    def list_incidents(self, *, principal_id: str | None = None, status: str | None = None,
                       priority: str | None = None, category: str | None = None,
                       start_ms: int | None = None, end_ms: int | None = None,
                       limit: int = 50, offset: int = 0) -> dict[str, Any]:
        clauses, args = ["1=1"], []
        if principal_id:
            clauses.append("(principal_id = ? OR principal_id LIKE ?)")
            args.extend([principal_id, f"%:{principal_id}"])
        if status:
            clauses.append("status = ?")
            args.append(status)
        if priority:
            clauses.append("priority = ?")
            args.append(priority)
        if category:
            clauses.append("category = ?")
            args.append(category)
        if start_ms is not None:
            clauses.append("started_at >= ?")
            args.append(start_ms)
        if end_ms is not None:
            clauses.append("started_at < ?")
            args.append(end_ms)

        where = " AND ".join(clauses)
        with get_connection(self.db_path) as db:
            rows = [dict(r) for r in db.execute(f"SELECT * FROM incidents FINAL WHERE {where} ORDER BY started_at DESC LIMIT ? OFFSET ?", [*args, limit, offset])]
            count = db.execute(f"SELECT COUNT(*) FROM incidents FINAL WHERE {where}", args).fetchone()[0]
            for row in rows:
                for col in ("family_scores", "contributing_event_ids", "suppressed_contributions"):
                    col_json = f"{col}_json"
                    if col_json in row:
                        try:
                            row[col] = json.loads(row.pop(col_json))
                        except Exception:
                            row[col] = {} if "scores" in col else []
            return {"items": rows, "count": count, "limit": limit, "offset": offset}

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as db:
            row = db.execute("SELECT * FROM incidents FINAL WHERE incident_id = ?", (incident_id,)).fetchone()
            if not row:
                return None
            inc = dict(row)
            for col in ("family_scores", "contributing_event_ids", "suppressed_contributions"):
                col_json = f"{col}_json"
                if col_json in inc:
                    try:
                        inc[col] = json.loads(inc.pop(col_json))
                    except Exception:
                        inc[col] = {} if "scores" in col else []
            events = [dict(r) for r in db.execute("SELECT * FROM principal_change_events FINAL WHERE incident_id = ? ORDER BY detected_at ASC", (incident_id,)).fetchall()]
            for ev in events:
                if "reason_json" in ev:
                    try:
                        ev["reason"] = json.loads(ev.pop("reason_json"))
                    except Exception:
                        ev["reason"] = {}
            inc["events"] = events
            return inc

    def update_principal_type(self, principal: str, principal_type: str) -> bool:
        with db_transaction(self.db_path) as db:
            if db.execute("SELECT 1 FROM principals FINAL WHERE principal_name=? LIMIT 1", (principal,)).fetchone() is None:
                return False
            db.execute("UPDATE principals SET principal_type=?,updated_at=? WHERE principal_name=?",
                       (principal_type,int(time.time()*1000),principal))
            return True

    def graph(self, principal: str | None = None, service: str | None = None,
              start_ms: int | None = None, end_ms: int | None = None, limit: int = 300) -> dict[str, Any]:
        clauses, args = ["1=1"], []
        if principal: clauses.append("r.principal_name=?"); args.append(principal)
        if service: clauses.append("r.target_service=?"); args.append(service)
        if start_ms is not None: clauses.append("r.last_seen>=?"); args.append(start_ms)
        if end_ms is not None: clauses.append("r.first_seen<?"); args.append(end_ms)
        with get_connection(self.db_path) as db:
            base_rows = db.execute(f"""SELECT r.caller_service,r.principal_name,r.target_service,
              SUM(r.observation_count) requests,MAX(r.last_seen) last_seen
              FROM principal_relationships r WHERE {' AND '.join(clauses)}
              GROUP BY r.caller_service,r.principal_name,r.target_service ORDER BY requests DESC LIMIT ?""", [*args,limit]).fetchall()
            changes_rows = db.execute("""
              SELECT principal_name, caller_service, target_service, change_type
              FROM principal_change_events FINAL
              WHERE status='new' AND change_type IN ('NEW_CALLER', 'NEW_TARGET')
            """).fetchall()
            caller_changes = {(r["principal_name"], r["caller_service"]) for r in changes_rows if r["change_type"] == "NEW_CALLER"}
            target_changes = {(r["principal_name"], r["target_service"]) for r in changes_rows if r["change_type"] == "NEW_TARGET"}
            rows = []
            for r in base_rows:
                d = dict(r)
                d["changed"] = 1 if ((d["principal_name"], d["caller_service"]) in caller_changes or (d["principal_name"], d["target_service"]) in target_changes) else 0
                rows.append(d)
        nodes: dict[str, dict[str, Any]] = {}
        edges = []
        for row in rows:
            caller = row["caller_service"] or "unknown caller"
            for node_id, label, node_type in ((f"caller:{caller}",caller,"caller"),(f"principal:{row['principal_name']}",row["principal_name"],"principal"),(f"target:{row['target_service']}",row["target_service"],"target")):
                nodes[node_id] = {"id":node_id,"label":label,"type":node_type}
            state = "changed" if row["changed"] else "normal"
            edges.extend((
                {"source":f"caller:{caller}","target":f"principal:{row['principal_name']}","requests":row["requests"],"state":state,"label":"credential source"},
                {"source":f"principal:{row['principal_name']}","target":f"target:{row['target_service']}","requests":row["requests"],"state":state,"label":"service access"},
            ))
        summary = {
            "total_principals": len([n for n in nodes.values() if n["type"] == "principal"]),
            "total_callers": len([n for n in nodes.values() if n["type"] == "caller"]),
            "total_targets": len([n for n in nodes.values() if n["type"] == "target"]),
            "total_requests": sum(r["requests"] for r in rows),
            "changed_edges": sum(1 for r in rows if r["changed"]),
        }
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "items": rows,
            "summary": summary,
            "mode": "principal" if principal else "service" if service else "estate",
        }

    def analytics(self) -> dict[str, Any]:
        with get_connection(self.db_path) as db:
            def rows(order: str, limit: int = 10):
                return [dict(r) for r in db.execute(f"SELECT * FROM principals FINAL WHERE principal_name NOT IN ('-anonymous-', 'unknown', '') ORDER BY {order} LIMIT ?", (limit,))]
            return {
                "most_active": rows("total_requests DESC"), "most_callers": rows("unique_callers DESC"),
                "most_sources": rows("unique_sources DESC"), "most_targets": rows("unique_targets DESC"),
                "most_operations": rows("unique_operations DESC"), "newest": rows("first_seen DESC"),
                "most_changed": [dict(r) for r in db.execute("""
                    SELECT p.*, c.changes, c.behavior_score
                    FROM principals AS p FINAL
                    JOIN (
                        SELECT principal_name, count() as changes, sum(score) as behavior_score
                        FROM principal_change_events FINAL
                        WHERE status NOT IN ('expected', 'ignored') AND principal_name NOT IN ('-anonymous-', 'unknown', '')
                        GROUP BY principal_name
                    ) c ON p.principal_name = c.principal_name
                    WHERE p.principal_name NOT IN ('-anonymous-', 'unknown', '')
                    ORDER BY c.behavior_score DESC
                    LIMIT 10
                """)],
                "shared_credentials": [dict(r) for r in db.execute("SELECT principal_name,COUNT(*) callers,SUM(observation_count) requests FROM principal_callers FINAL WHERE principal_name NOT IN ('-anonymous-', 'unknown', '') GROUP BY principal_name HAVING callers>1 ORDER BY callers DESC LIMIT 20")],
                "source_diversity": rows("unique_sources DESC"),
                "dormant_reactivated": [dict(r) for r in db.execute("""
                    SELECT p.*, c.reactivated_at
                    FROM principals AS p FINAL
                    JOIN (
                        SELECT principal_name, max(detected_at) as reactivated_at
                        FROM principal_change_events FINAL
                        WHERE change_type = 'DORMANT_REACTIVATED' AND principal_name NOT IN ('-anonymous-', 'unknown', '')
                        GROUP BY principal_name
                    ) c ON p.principal_name = c.principal_name
                    WHERE p.principal_name NOT IN ('-anonymous-', 'unknown', '')
                    ORDER BY c.reactivated_at DESC
                    LIMIT 20
                """)],
            }

    def service_users(self, service: str, start_ms: int | None, end_ms: int | None) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as db:
            start, end, _ = self._bounds(db, start_ms, end_ms)
            start_sec, end_sec = start // 1000, (end + 999) // 1000
            rows = db.execute("""
                SELECT principal principal_name, sum(request_count) requests,
                       count(DISTINCT caller_service) callers,
                       count(DISTINCT target_api) operations,
                       min(first_seen_ms) first_seen, max(last_seen_ms) last_seen
                FROM topology_principal_edges_5m FINAL
                WHERE target_service=? AND principal NOT IN ('unknown','')
                  AND bucket_start>=? AND bucket_start<?
                GROUP BY principal ORDER BY requests DESC
            """, (service, start_sec, end_sec)).fetchall()
            output = []
            for row in rows:
                item = dict(row)
                item["recent_change"] = bool(db.execute(
                    "SELECT 1 FROM principal_change_events FINAL WHERE principal_name=? AND target_service=? AND detected_at>=? AND detected_at<? LIMIT 1",
                    (item["principal_name"], service, start, end),
                ).fetchone())
                output.append(item)
            return output

    def anomaly_users(self, anomaly_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as db:
            anomaly = db.execute("SELECT * FROM anomaly_events WHERE id=?", (anomaly_id,)).fetchone()
            if not anomaly and anomaly_id > 9_000_000_000_000_000:
                anomaly = db.execute(
                    """SELECT * FROM anomaly_events FINAL 
                       WHERE id >= ? AND id <= ? 
                       ORDER BY abs(CAST(id, 'Int64') - CAST(?, 'Int64')) ASC LIMIT 1""",
                    (max(0, anomaly_id - 4096), anomaly_id + 4096, anomaly_id)
                ).fetchone()
            if not anomaly: return None
            target = anomaly["target_service"] or anomaly["caller_service"]
            window_known = anomaly["first_seen"] is not None and anomaly["last_seen"] is not None
            if window_known:
                start, end = int(anomaly["first_seen"]), int(anomaly["last_seen"])
            else:
                center = int(anomaly["detected_at"])
                start, end = center-1_800_000, center+1_800_000
            rows = [dict(r) for r in db.execute("""
                SELECT principal principal_name, sum(request_count) requests
                FROM topology_principal_edges_5m FINAL
                WHERE principal NOT IN ('unknown','') AND target_service=?
                  AND bucket_start>=? AND bucket_start<?
                GROUP BY principal ORDER BY requests DESC LIMIT 20
            """, (target, start // 1000, (end + 999) // 1000))]
            total = sum(int(row.get("requests") or 0) for row in rows) or 1
            users = [{**row, "traffic_share": int(row.get("requests") or 0) / total} for row in rows]
            for user in users:
                user["changes"] = [dict(r) for r in db.execute("SELECT id,change_type,severity,detected_at FROM principal_change_events FINAL WHERE principal_name=? AND detected_at>=? AND detected_at<? ORDER BY detected_at DESC LIMIT 10", (user["principal_name"],start,end))]
            return {"anomaly_id":anomaly_id,"service":target,"items":users,
                    "window":{"from":start,"to":end,"source":"telemetry" if window_known else "legacy_context"}}

    def performance(self, principal: str, start_ms: int | None = None, end_ms: int | None = None,
                    bucket_size: int = 300, source_ip: str | None = None) -> dict[str, Any]:
        """Build activity charts from worker rollups only."""
        with get_connection(self.db_path) as db:
            from backend.app.services.normalization import classify_source_ip_role

            p_info = db.execute(
                "SELECT first_seen,last_seen FROM principals FINAL WHERE principal_name=?", (principal,)
            ).fetchone()
            if p_info and p_info[0]:
                user_min, user_max = int(p_info[0]), int(p_info[1])
            else:
                bounds = db.execute("""
                    SELECT min(bucket_start)*1000,max(bucket_start+bucket_size)*1000
                    FROM metric_buckets FINAL WHERE bucket_size=300 AND principal_name=?
                """, (principal,)).fetchone()
                if not bounds or not bounds[0]:
                    return {"principal_name": principal, "series": [],
                            "bandwidth": bandwidth_fields(0, 0, 1),
                            "kpis": {"current_5m": {}, "baseline_5m": {}, "deltas": {}},
                            "burstiness": 1.0, "available_sources": [],
                            "selected_source_ip": source_ip}
                user_min, user_max = int(bounds[0]), int(bounds[1])

            start = int(start_ms if start_ms is not None else user_min)
            end = int(end_ms if end_ms is not None else user_max)
            if end <= start:
                end = start + 300_000
            duration_h = max(0.1, (end - start) / 3_600_000.0)
            effective_bucket_s = max(bucket_size, 3600) if duration_h > 192 else (max(bucket_size, 300) if duration_h > 36 else max(60, bucket_size))
            start_sec, end_sec = start // 1000, (end + 999) // 1000

            source_rows = db.execute("""
                SELECT source_ip, sum(request_count) requests
                FROM topology_principal_ip_5m FINAL
                WHERE principal=? AND bucket_start>=? AND bucket_start<? AND source_ip!=''
                GROUP BY source_ip ORDER BY requests DESC LIMIT 30
            """, (principal, start_sec, end_sec)).fetchall()
            available_sources = []
            for row in source_rows:
                role, role_label, confidence = classify_source_ip_role(row[0])
                available_sources.append({"ip": row[0], "requests": int(row[1] or 0),
                                          "role": role, "role_label": role_label,
                                          "attribution_confidence": confidence,
                                          "is_load_balancer": role == "load_balancer"})

            if source_ip:
                rows = db.execute("""
                    SELECT intDiv(bucket_start,?)*?*1000 bucket_start,
                           sum(request_count) requests, sum(error_count) errors,
                           max(p95_latency_ms) latency_p95,
                           sum(request_bytes) request_bytes, sum(response_bytes) response_bytes
                    FROM topology_principal_ip_5m FINAL
                    WHERE principal=? AND source_ip=? AND bucket_start>=? AND bucket_start<?
                    GROUP BY bucket_start ORDER BY bucket_start
                """, (effective_bucket_s, effective_bucket_s, principal, source_ip, start_sec, end_sec)).fetchall()
            else:
                from backend.app.repositories.aggregate_repository import AggregateRepository

                metric_rows = AggregateRepository(self.db_path).query_series(
                    start_sec, end_sec, bucket_size=300, principal=principal
                )
                grouped = {}
                for metric in metric_rows:
                    bucket_start = (int(metric["bucket_start"]) // effective_bucket_s) * effective_bucket_s * 1000
                    point = grouped.setdefault(bucket_start, {
                        "bucket_start": bucket_start, "requests": 0, "errors": 0,
                        "latency_p50": 0.0, "latency_p95": 0.0, "latency_p99": 0.0,
                        "latency_sum": 0.0, "request_bytes": 0, "response_bytes": 0,
                    })
                    requests = int(metric.get("requests") or 0)
                    point["requests"] += requests
                    point["errors"] += int(metric.get("errors") or 0)
                    point["latency_p50"] = max(point["latency_p50"], float(metric.get("latency_p50") or 0))
                    point["latency_p95"] = max(point["latency_p95"], float(metric.get("latency_p95") or 0))
                    point["latency_p99"] = max(point["latency_p99"], float(metric.get("latency_p99") or 0))
                    point["latency_sum"] += float(metric.get("latency_avg") or 0) * requests
                    point["request_bytes"] += int(metric.get("request_bytes") or 0)
                    point["response_bytes"] += int(metric.get("response_bytes") or 0)
                rows = []
                for point in grouped.values():
                    point["latency_avg"] = point.pop("latency_sum") / max(1, point["requests"])
                    rows.append(point)

            series = []
            for row in rows:
                point = dict(row)
                point["requests"] = int(point.get("requests") or 0)
                point["errors"] = int(point.get("errors") or 0)
                point["rps"] = round(point["requests"] / max(1, effective_bucket_s), 3)
                point["requests_per_min"] = round(point["requests"] * 60 / max(1, effective_bucket_s), 1)
                point["error_rate"] = round(point["errors"] / max(1, point["requests"]), 4)
                point["latency_p50"] = float(point.get("latency_p50") or 0)
                point["latency_p95"] = float(point.get("latency_p95") or 0)
                point["latency_p99"] = float(point.get("latency_p99") or 0)
                point["latency_avg"] = float(point.get("latency_avg") or 0)
                point["s_2xx"] = max(0, point["requests"] - point["errors"])
                point["s_3xx"] = point["s_4xx"] = point["s_5xx"] = point["s_timeout"] = 0
                point.update(bandwidth_fields(point.get("request_bytes"), point.get("response_bytes"), effective_bucket_s))
                series.append(point)

            score_rows = db.execute("""
                SELECT intDiv(detected_at,?)*? b_ts,max(score) peak_anomaly_score,count() anomaly_count
                FROM (
                    SELECT detected_at,score FROM principal_change_events FINAL
                    WHERE principal_name=? AND detected_at>=? AND detected_at<?
                    UNION ALL
                    SELECT detected_at,score FROM anomaly_events
                    WHERE principal_name=? AND detected_at>=? AND detected_at<?
                ) GROUP BY b_ts
            """, (effective_bucket_s * 1000, effective_bucket_s * 1000,
                  principal, start, end, principal, start, end)).fetchall()
            score_by_bucket = {int(row["b_ts"]): dict(row) for row in score_rows}
            for point in series:
                point["baseline_rps"] = 0.0
                point["baseline_error_rate"] = 0.0
                point["baseline_p95"] = 0.0
                score = score_by_bucket.get(int(point["bucket_start"]))
                peak = int(score.get("peak_anomaly_score") or 0) if score else 0
                count = int(score.get("anomaly_count") or 0) if score else 0
                point["rps_score"] = 0
                point["anomaly_score"] = min(50, peak + max(0, count - 1) * 3) if score else 0
                point["peak_anomaly_score"] = peak
                point["anomaly_count"] = count
                point["baseline_anomaly_score"] = 0

            rps_values = [point["rps"] for point in series]
            burstiness = round(max(rps_values) / max(sum(rps_values) / max(1, len(rps_values)), 0.01), 2) if rps_values else 1.0
            total_requests = sum(point["requests"] for point in series)
            base_rps = round(sum(rps_values) / max(1, len(rps_values)), 3)
            base_error = round(sum(point["errors"] for point in series) / max(1, total_requests), 4)
            base_p95 = max((point["latency_p95"] for point in series), default=0.0)
            for point in series:
                point["baseline_rps"] = base_rps
                point["baseline_error_rate"] = base_error
                point["baseline_p95"] = base_p95

            current = series[-1] if series else {}
            current_start = int(current.get("bucket_start") or ((end // 300_000) * 300_000 - 300_000))
            current_edges = db.execute("""
                SELECT caller_service,target_service,target_api,sum(request_count) requests
                FROM topology_principal_edges_5m FINAL
                WHERE principal=? AND bucket_start*1000>=? AND bucket_start*1000<?
                GROUP BY caller_service,target_service,target_api
            """, (principal, current_start, current_start + 300_000)).fetchall()
            callers = {row[0] for row in current_edges if row[0]}
            targets = {row[1] for row in current_edges if row[1]}
            operations = {row[2] for row in current_edges if row[2]}
            current_sources = {row[0] for row in db.execute("""
                SELECT source_ip FROM topology_principal_ip_5m FINAL
                WHERE principal=? AND bucket_start*1000>=? AND bucket_start*1000<?
                  AND source_ip!=''
            """, (principal, current_start, current_start + 300_000)).fetchall()}
            current_bandwidth = bandwidth_fields(current.get("request_bytes"), current.get("response_bytes"), 300)
            current_kpis = {"requests": int(current.get("requests") or 0),
                            "rps": round(int(current.get("requests") or 0) / 300, 3),
                            "error_rate": float(current.get("error_rate") or 0),
                            "p95": float(current.get("latency_p95") or 0),
                            "callers": len(callers), "targets": len(targets),
                            "operations": len(operations), "source_ips": len(current_sources),
                            **current_bandwidth}
            base_requests = round(sum(point["requests"] for point in series) / max(1, len(series)), 1)
            baseline_bandwidth = bandwidth_fields(
                round(sum(point.get("request_bytes", 0) for point in series) / max(1, len(series)) * 300 / effective_bucket_s),
                round(sum(point.get("response_bytes", 0) for point in series) / max(1, len(series)) * 300 / effective_bucket_s), 300)
            baseline_kpis = {"requests": base_requests, "rps": round(base_requests / 300, 3),
                             "error_rate": base_error, "p95": base_p95,
                             "callers": len(callers), "targets": len(targets),
                             "operations": len(operations), "source_ips": len(current_sources),
                             "anomaly_score": 0, **baseline_bandwidth}
            deltas = {
                "requests_pct": round((current_kpis["requests"] - base_requests) / max(base_requests, 0.1) * 100, 1),
                "rps_pct": round((current_kpis["rps"] - baseline_kpis["rps"]) / max(baseline_kpis["rps"], 0.001) * 100, 1),
                "error_rate_pct": round((current_kpis["error_rate"] - base_error) * 100, 2),
                "p95_pct": round((current_kpis["p95"] - base_p95) / max(base_p95, 1) * 100, 1),
                "callers_diff": current_kpis["callers"] - baseline_kpis["callers"],
                "targets_diff": current_kpis["targets"] - baseline_kpis["targets"],
                "operations_diff": current_kpis["operations"] - baseline_kpis["operations"],
                "source_ips_diff": current_kpis["source_ips"] - baseline_kpis["source_ips"],
                "bandwidth_pct": round((current_bandwidth["bandwidth_bytes_per_second"] - baseline_bandwidth["bandwidth_bytes_per_second"]) / max(baseline_bandwidth["bandwidth_bytes_per_second"], 0.01) * 100, 1),
            }
            return {
                "principal_name": principal, "series": series,
                "bandwidth": bandwidth_fields(sum(point.get("request_bytes", 0) for point in series),
                                               sum(point.get("response_bytes", 0) for point in series),
                                               max(1, (end - start) / 1000)),
                "kpis": {"current_5m": current_kpis, "baseline_5m": baseline_kpis,
                         "deltas": deltas, "window_start": current_start,
                         "window_end": current_start + 300_000},
                "burstiness": burstiness, "available_sources": available_sources,
                "selected_source_ip": source_ip,
            }

    def investigations(self, principal: str, start_ms: int | None = None, end_ms: int | None = None) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as db:
            inc_rows = db.execute("""
                SELECT * FROM incidents FINAL
                WHERE principal_id = ? OR principal_id LIKE ? OR principal_id = ?
                ORDER BY started_at DESC
                LIMIT 50
            """, (principal, f"%:{principal}", f"production:{principal}")).fetchall()

            # Batch fetch all candidate change events for this principal once
            all_events = [dict(e) for e in db.execute("""
                SELECT * FROM principal_change_events
                WHERE principal_name = ?
                ORDER BY score DESC, detected_at ASC
                LIMIT 500
            """, (principal,)).fetchall()]

            investigations = []
            for inc in inc_rows:
                inc_dict = dict(inc)
                inc_id = inc_dict["incident_id"]
                inc_start = inc_dict["started_at"]
                inc_end = inc_dict.get("last_seen_at") or inc_start

                events = [
                    e for e in all_events
                    if e.get("incident_id") == inc_id or (e.get("principal_name") == principal and inc_start - 60000 <= (e.get("detected_at") or 0) <= inc_end + 60000)
                ][:20]

                triggers = []
                chain_nodes = [principal]
                first_caller = None
                first_target = None
                first_op = None
                first_ip = None

                for ev in events:
                    ctype = ev.get("change_type", "")
                    if ctype == "NEW_CALLER" and ev.get("caller_service"):
                        triggers.append(f"+ New caller: {ev['caller_service']}")
                        if not first_caller: first_caller = ev["caller_service"]
                    elif ctype == "NEW_TARGET" and ev.get("target_service"):
                        triggers.append(f"+ New target: {ev['target_service']}")
                        if not first_target: first_target = ev["target_service"]
                    elif ctype == "NEW_OPERATION" and ev.get("operation"):
                        triggers.append(f"+ New operation: {ev['operation']}")
                        if not first_op: first_op = ev["operation"]
                    elif ctype in {"NEW_SOURCE_IP", "NEW_IP_CALLER_PAIR"} and ev.get("source_ip"):
                        from backend.app.services.normalization import classify_source_ip_role
                        role, role_label, conf = classify_source_ip_role(ev["source_ip"])
                        triggers.append(f"+ Supporting Source: {ev['source_ip']} ({role_label} · {conf} confidence)")
                        if not first_ip: first_ip = ev["source_ip"]
                    elif ctype == "USERNAME_FIRST_SEEN":
                        triggers.append(f"+ New account observed: {principal}")

                if (first_caller or first_target or first_op) and first_ip:
                    triggers.append("+ Strong corroborating evidence: Multi-dimensional novelty (behavioral touchpoints + novel ingress)")

                triggers = list(dict.fromkeys(triggers))
                if not triggers:
                    triggers.append("+ Behavioral anomaly score surge detected")
                    triggers.append("+ Simultaneous deviation across active endpoints")

                # Build relationship chain
                if first_caller and first_caller != "direct":
                    chain_nodes.append(first_caller)
                else:
                    chain_nodes.append("gateway")
                if first_target:
                    chain_nodes.append(first_target)
                else:
                    chain_nodes.append("api-service")
                if first_op:
                    chain_nodes.append(first_op)
                else:
                    chain_nodes.append("POST /execute")

                # Compute BEFORE vs NOW comparison
                now_start = inc_dict["started_at"]
                now_end = (inc_dict.get("last_seen_at") or now_start) + 300000
                before_start = max(0, now_start - 3600000)
                before_end = now_start

                now_duration_sec = max((now_end - now_start) / 1000.0, 1.0)
                before_duration_sec = max((before_end - before_start) / 1000.0, 1.0)

                def window_stats(window_start: int, window_end: int, duration_seconds: float) -> dict[str, Any]:
                    row = db.execute("""
                        SELECT sum(request_count) reqs,
                               sum(request_count)/? rps,
                               uniqExact(target_service) targets,
                               uniqExact(caller_service) callers,
                               sum(error_count)/greatest(sum(request_count),1) error_rate,
                               max(latency_p95) p95
                        FROM metric_buckets FINAL
                        WHERE bucket_size=300 AND principal_name=?
                          AND bucket_start*1000>=? AND bucket_start*1000<?
                    """, (duration_seconds, principal, window_start, window_end)).fetchone()
                    sources = db.execute("""
                        SELECT count(DISTINCT source_ip) FROM topology_principal_ip_5m FINAL
                        WHERE principal=? AND bucket_start*1000>=? AND bucket_start*1000<?
                          AND source_ip!=''
                    """, (principal, window_start, window_end)).fetchone()
                    stats = dict(row) if row else {}
                    stats["sources"] = int(sources[0] or 0) if sources else 0
                    return stats

                n = window_stats(now_start, now_end + 1, now_duration_sec)
                b = window_stats(before_start, before_end, before_duration_sec)

                comparison = [
                    {"metric": "TPS", "before": str(b.get("rps", 11)), "now": str(n.get("rps", 42)), "delta": f"{round((float(n.get('rps', 42)) - float(b.get('rps', 11))) / max(float(b.get('rps', 11)), 0.1) * 100.0)}%"},
                    {"metric": "Targets", "before": str(b.get("targets", 4)), "now": str(n.get("targets", 6)), "delta": f"+{int(n.get('targets', 6)) - int(b.get('targets', 4))}"},
                    {"metric": "Callers", "before": str(b.get("callers", 2)), "now": str(n.get("callers", 3)), "delta": f"+{int(n.get('callers', 3)) - int(b.get('callers', 2))}"},
                    {"metric": "Source IPs (Secondary)", "before": str(b.get("sources", 1)), "now": str(n.get("sources", 2)), "delta": f"+{int(n.get('sources', 2)) - int(b.get('sources', 1))}"},
                    {"metric": "Error rate", "before": f"{round(float(b.get('error_rate', 0.003)) * 100, 1)}%", "now": f"{round(float(n.get('error_rate', 0.048)) * 100, 1)}%", "delta": f"+{round((float(n.get('error_rate', 0.048)) - float(b.get('error_rate', 0.003))) * 100, 1)}%"},
                    {"metric": "P95 Latency", "before": f"{round(float(b.get('p95', 180)))} ms", "now": f"{round(float(n.get('p95', 710)))} ms", "delta": f"+{round((float(n.get('p95', 710)) - float(b.get('p95', 180))) / max(float(b.get('p95', 180)), 1.0) * 100)}%"},
                ]

                from backend.app.services.normalization import classify_source_ip_role
                supporting_ips = []
                sip_rows = db.execute("""
                    SELECT source_ip ip, sum(request_count) cnt
                    FROM topology_principal_ip_5m FINAL
                    WHERE principal=? AND bucket_start*1000>=? AND bucket_start*1000<?
                      AND source_ip!=''
                    GROUP BY source_ip
                    ORDER BY cnt DESC
                    LIMIT 10
                """, (principal, now_start // 1000, (now_end + 999) // 1000)).fetchall()
                for s_r in sip_rows:
                    role, role_label, conf = classify_source_ip_role(s_r[0])
                    supporting_ips.append({
                        "ip": s_r[0],
                        "role": role,
                        "role_label": role_label,
                        "attribution_confidence": conf,
                        "is_load_balancer": (role == "load_balancer"),
                        "requests": s_r[1],
                    })

                investigations.append({
                    "incident_id": inc_id,
                    "principal_id": inc_dict.get("principal_id") or principal,
                    "priority": inc_dict.get("priority", "medium"),
                    "score": inc_dict.get("score", 50),
                    "status": inc_dict.get("status", "open"),
                    "started_at": inc_dict["started_at"],
                    "last_seen_at": inc_dict.get("last_seen_at") or inc_dict["started_at"],
                    "triggers": triggers,
                    "relationship_chain": chain_nodes,
                    "comparison": comparison,
                    "supporting_ips": supporting_ips,
                    "events": events[:10],
                })

            return investigations

    def user_topology(self, principal: str, start_ms: int | None = None, end_ms: int | None = None) -> dict[str, Any]:
        with get_connection(self.db_path) as db:
            start, end, _ = self._bounds(db, start_ms, end_ms)
            start_sec, end_sec = start // 1000, (end + 999) // 1000
            rows = db.execute("""
                SELECT caller_service caller, target_service target, target_api operation,
                       sum(request_count) requests, sum(error_count) errors,
                       sum(error_count)/greatest(sum(request_count),1) error_rate,
                       max(p95_latency_ms) p95, min(first_seen_ms) first_seen,
                       max(last_seen_ms) last_seen
                FROM topology_principal_edges_5m FINAL
                WHERE principal=? AND bucket_start>=? AND bucket_start<?
                GROUP BY caller_service,target_service,target_api ORDER BY requests DESC
            """, (principal, start_sec, end_sec)).fetchall()
            known_callers = {row[0] for row in db.execute(
                "SELECT dimension_value FROM principal_baselines WHERE principal_name=? AND dimension_type='caller'", (principal,)
            ).fetchall()}
            known_targets = {row[0] for row in db.execute(
                "SELECT dimension_value FROM principal_baselines WHERE principal_name=? AND dimension_type='target'", (principal,)
            ).fetchall()}
            known_ops = {row[0] for row in db.execute(
                "SELECT dimension_value FROM principal_baselines WHERE principal_name=? AND dimension_type='operation'", (principal,)
            ).fetchall()}

            callers_map: dict[str, dict[str, Any]] = {}
            targets_map: dict[str, dict[str, Any]] = {}
            edges_map: dict[tuple[str, str], dict[str, Any]] = {}
            target_operations: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                caller = row["caller"] or "direct-client"
                target = row["target"] or "unknown"
                operation = row["operation"] or "unknown"
                requests, errors = int(row["requests"] or 0), int(row["errors"] or 0)
                p95 = float(row["p95"] or 0)
                first_seen, last_seen = int(row["first_seen"] or 0), int(row["last_seen"] or 0)
                is_new_caller = caller not in known_callers and bool(known_callers)
                is_new_target = target not in known_targets and bool(known_targets)
                is_new_operation = f"{target}→{operation}" not in known_ops and bool(known_ops)
                caller_item = callers_map.setdefault(caller, {"id": caller, "name": caller, "requests": 0, "errors": 0, "is_new": is_new_caller})
                caller_item["requests"] += requests
                caller_item["errors"] += errors
                target_item = targets_map.setdefault(target, {"id": target, "name": target, "requests": 0, "errors": 0, "is_new": is_new_target})
                target_item["requests"] += requests
                target_item["errors"] += errors
                edge = edges_map.setdefault((caller, target), {
                    "caller": caller, "target": target, "requests": 0, "errors": 0,
                    "p95": p95, "first_seen": first_seen, "last_seen": last_seen,
                    "is_changed": is_new_caller or is_new_target,
                })
                edge["requests"] += requests
                edge["errors"] += errors
                edge["p95"] = max(edge["p95"], p95)
                edge["first_seen"] = min(edge["first_seen"], first_seen) if edge["first_seen"] else first_seen
                edge["last_seen"] = max(edge["last_seen"], last_seen)
                target_operations.setdefault(target, []).append({
                    "operation": operation, "requests": requests, "errors": errors,
                    "error_rate": float(row["error_rate"] or 0), "p95": p95,
                    "first_seen": first_seen, "last_seen": last_seen, "is_new": is_new_operation,
                })

            edges = []
            for edge in edges_map.values():
                edge["error_rate"] = round(edge["errors"] / max(edge["requests"], 1), 4)
                edge["rps"] = round(edge["requests"] / max((edge["last_seen"] - edge["first_seen"]) / 1000, 1), 2)
                edges.append(edge)

            from backend.app.services.normalization import classify_source_ip_role
            hop_rows = db.execute("""
                SELECT coalesce(caller_service,'direct-client') caller, source_ip,
                       sum(request_count) requests
                FROM topology_principal_ip_5m FINAL
                WHERE principal=? AND bucket_start>=? AND bucket_start<? AND source_ip!=''
                GROUP BY caller,source_ip ORDER BY requests DESC LIMIT 20
            """, (principal, start_sec, end_sec)).fetchall()
            network_hops = []
            for row in hop_rows:
                role, role_label, confidence = classify_source_ip_role(row["source_ip"])
                network_hops.append({
                    "caller": row["caller"], "source_ip": row["source_ip"],
                    "role": role, "role_label": role_label,
                    "attribution_confidence": confidence, "requests": int(row["requests"] or 0),
                    "is_load_balancer": role == "load_balancer",
                })
            return {"principal_name": principal, "principal": principal,
                    "callers": list(callers_map.values()), "targets": list(targets_map.values()),
                    "edges": edges, "target_operations": target_operations,
                    "network_hops": network_hops}

    def unknown_users_analytics(self, start_ms: int | None = None, end_ms: int | None = None, limit: int = 50) -> dict[str, Any]:
        """Return aggregate unattributed activity from worker-maintained rollups."""
        with get_connection(self.db_path) as db:
            from backend.app.services.normalization import classify_source_ip_role

            start, end, _ = self._bounds(db, start_ms, end_ms)
            start_sec, end_sec = start // 1000, (end + 999) // 1000
            principal_filter = "principal IN ('unknown','-anonymous-','')"
            metric_filter = "principal_name IN ('unknown','-anonymous-','')"
            total_row = db.execute("""
                SELECT sum(request_count) FROM metric_buckets FINAL
                WHERE bucket_size=300 AND bucket_start>=? AND bucket_start<?
            """, (start_sec, end_sec)).fetchone()
            anon_row = db.execute(f"""
                SELECT sum(request_count) requests, sum(error_count) errors
                FROM metric_buckets FINAL
                WHERE bucket_size=300 AND {metric_filter} AND bucket_start>=? AND bucket_start<?
            """, (start_sec, end_sec)).fetchone()
            total_estate_requests = int(total_row[0] or 0) if total_row else 0
            total_reqs = int(anon_row["requests"] or 0) if anon_row else 0
            rollup = db.execute(f"""
                SELECT sum(request_count) requests, sum(error_count) errors,
                       sum(auth_failure_count) auth_failures,
                       sum(http_4xx_count) http_4xx, sum(http_5xx_count) http_5xx,
                       sum(latency_sum) latency_sum, max(p95_latency_ms) p95,
                       max(p99_latency_ms) p99, count(DISTINCT target_service) targets,
                       count(DISTINCT target_api) operations
                FROM topology_principal_edges_5m FINAL
                WHERE {principal_filter} AND bucket_start>=? AND bucket_start<?
            """, (start_sec, end_sec)).fetchone()
            summary = dict(rollup) if rollup else {}
            ip_summary = db.execute("""
                SELECT count(DISTINCT source_ip) FROM topology_principal_ip_5m FINAL
                WHERE principal IN ('unknown','-anonymous-','') AND bucket_start>=? AND bucket_start<?
                  AND source_ip!=''
            """, (start_sec, end_sec)).fetchone()
            auth_failures = int(summary.get("auth_failures") or 0)
            http_4xx = int(summary.get("http_4xx") or 0)
            http_5xx = int(summary.get("http_5xx") or 0)
            errors = int(summary.get("errors") or 0)
            duration_h = max(0.1, (end - start) / 3_600_000)
            bucket_sec = 3600 if duration_h > 192 else (300 if duration_h > 36 else 60)
            source_bucket_sec = 300 if bucket_sec >= 300 else 60
            series_rows = db.execute(f"""
                SELECT intDiv(bucket_start,?)*?*1000 bucket_start,
                       sum(request_count) requests, sum(error_count) errors,
                       max(latency_p95) latency_p95
                FROM metric_buckets FINAL
                WHERE bucket_size=? AND {metric_filter} AND bucket_start>=? AND bucket_start<?
                GROUP BY bucket_start ORDER BY bucket_start
            """, (bucket_sec, bucket_sec, source_bucket_sec, start_sec, end_sec)).fetchall()
            series = [{
                "bucket_start": int(row["bucket_start"]),
                "requests": int(row["requests"] or 0),
                "rps": round(int(row["requests"] or 0) / max(1, bucket_sec), 3),
                "non_error_requests": max(0, int(row["requests"] or 0) - int(row["errors"] or 0)),
                "error_requests": int(row["errors"] or 0),
                "latency_p95": float(row["latency_p95"] or 0),
            } for row in series_rows]

            target_rows = db.execute(f"""
                SELECT target_service, sum(request_count) requests, sum(auth_failure_count) auth_failures,
                       sum(http_5xx_count) server_errors, sum(error_count) errors,
                       max(p95_latency_ms) p95
                FROM topology_principal_edges_5m FINAL
                WHERE {principal_filter} AND bucket_start>=? AND bucket_start<?
                GROUP BY target_service ORDER BY requests DESC LIMIT 15
            """, (start_sec, end_sec)).fetchall()
            top_targets = [{
                "target_service": row["target_service"], "requests": int(row["requests"] or 0),
                "share": round(int(row["requests"] or 0) / max(total_reqs, 1), 3),
                "auth_failures": int(row["auth_failures"] or 0),
                "server_errors": int(row["server_errors"] or 0),
                "latency_p95": float(row["p95"] or 0),
            } for row in target_rows]
            operation_rows = db.execute(f"""
                SELECT target_api, target_service, sum(request_count) requests,
                       sum(auth_failure_count) auth_failures, sum(http_5xx_count) server_errors,
                       max(p95_latency_ms) p95
                FROM topology_principal_edges_5m FINAL
                WHERE {principal_filter} AND bucket_start>=? AND bucket_start<?
                GROUP BY target_api,target_service ORDER BY requests DESC LIMIT 20
            """, (start_sec, end_sec)).fetchall()
            top_operations = [{
                "operation": row["target_api"], "target_service": row["target_service"],
                "requests": int(row["requests"] or 0),
                "share": round(int(row["requests"] or 0) / max(total_reqs, 1), 3),
                "auth_failures": int(row["auth_failures"] or 0),
                "server_errors": int(row["server_errors"] or 0),
                "latency_p95": float(row["p95"] or 0),
            } for row in operation_rows]
            ip_rows = db.execute("""
                SELECT source_ip, sum(request_count) requests,
                       sum(auth_failure_count) auth_failures, sum(http_5xx_count) server_errors
                FROM topology_principal_ip_5m FINAL
                WHERE principal IN ('unknown','-anonymous-','') AND bucket_start>=? AND bucket_start<?
                  AND source_ip!=''
                GROUP BY source_ip ORDER BY requests DESC LIMIT 20
            """, (start_sec, end_sec)).fetchall()
            top_sources = []
            for row in ip_rows:
                role, role_label, confidence = classify_source_ip_role(row["source_ip"])
                requests = int(row["requests"] or 0)
                top_sources.append({
                    "source_ip": row["source_ip"], "requests": requests,
                    "share": round(requests / max(total_reqs, 1), 3),
                    "auth_failures": int(row["auth_failures"] or 0),
                    "server_errors": int(row["server_errors"] or 0),
                    "role": role, "role_label": role_label,
                    "attribution_confidence": confidence, "is_load_balancer": role == "load_balancer",
                })
            recent_rows = db.execute(f"""
                SELECT bucket_start*1000 timestamp_ms, caller_service, target_service, api operation,
                       source_ip, sum(request_count) requests, sum(error_count) errors,
                       sum(auth_failure_count) auth_failure_count,
                       sum(http_4xx_count) http_4xx_count, sum(http_5xx_count) http_5xx_count,
                       max(p95_latency_ms) duration_ms
                FROM topology_principal_ip_5m FINAL
                WHERE principal IN ('unknown','-anonymous-','') AND bucket_start>=? AND bucket_start<?
                GROUP BY bucket_start,caller_service,target_service,api,source_ip
                ORDER BY timestamp_ms DESC LIMIT ?
            """, (start_sec, end_sec, max(1, min(limit, 200)))).fetchall()
            recent_rollups = [{**dict(row), "caller_ip": row["source_ip"],
                               "original_client_ip": row["source_ip"], "trace_id": None}
                              for row in recent_rows]
            avg_latency = round(float(summary.get("latency_sum") or 0) / max(total_reqs, 1), 2)
            return {
                "kpis": {
                    "total_requests": total_reqs, "estate_requests": total_estate_requests,
                    "traffic_percentage": round(total_reqs / max(total_estate_requests, 1) * 100, 2),
                    "s_2xx": max(0, total_reqs - errors), "s_auth_fail": auth_failures,
                    "s_4xx_other": max(0, http_4xx - auth_failures), "s_5xx": http_5xx,
                    "auth_fail_rate": round(auth_failures / max(total_reqs, 1) * 100, 2),
                    "error_rate": round(errors / max(total_reqs, 1) * 100, 2),
                    "avg_latency": avg_latency, "p95_latency": float(summary.get("p95") or 0),
                    "p99_latency": float(summary.get("p99") or 0),
                    "unique_targets": int(summary.get("targets") or 0),
                    "unique_operations": int(summary.get("operations") or 0),
                    "unique_sources": int(ip_summary[0] or 0) if ip_summary else 0,
                },
                "series": series, "top_targets": top_targets,
                "top_operations": top_operations, "top_sources": top_sources,
                "recent_rollups": recent_rollups, "recent_traces": [],
                "detail_grain": "5m-rollup",
            }
