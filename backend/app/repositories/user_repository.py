"""Read derived identity intelligence from ClickHouse without reprocessing raw credentials."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from backend.config import settings
from backend.app.repositories.db_context import db_transaction, get_connection


class UserRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def _bounds(self, db, start_ms: int | None, end_ms: int | None) -> tuple[int, int, int]:
        available = db.execute("SELECT COALESCE(MIN(timestamp_ms),0),COALESCE(MAX(timestamp_ms),0) FROM traces").fetchone()
        end = end_ms or int(available[1]) + 1
        start = start_ms or int(available[0])
        return start, end, int(available[1])

    def list_users(self, *, start_ms: int | None = None, end_ms: int | None = None,
                   search: str | None = None, active: str | None = None,
                   caller: str | None = None, target: str | None = None,
                   source_ip: str | None = None, behavior_level: str | None = None,
                   has_changes: bool | None = None, first_from: int | None = None,
                   first_to: int | None = None, last_from: int | None = None,
                   last_to: int | None = None, sort: str = "most_active",
                   environment: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        with get_connection(self.db_path) as db:
            start, end, latest = self._bounds(db, start_ms, end_ms)
            active_cutoff = latest - settings.principal_active_minutes * 60_000
            clauses, args = ["1=1"], []
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
                clauses.append("p.principal_name IN (SELECT principal_name FROM traces WHERE service_environment=?)")
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
              principals p
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
                    FROM principal_change_events
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
            return {
                "observed_principals": scalar("SELECT COUNT(*) FROM principals"),
                "active_principals": scalar("SELECT COUNT(*) FROM principals WHERE last_seen>=?", (active_cutoff,)),
                "new_principals_today": scalar("SELECT COUNT(*) FROM principals WHERE first_seen>=?", (day_start,)),
                "principals_with_changes": scalar("SELECT COUNT(DISTINCT principal_name) FROM principal_change_events WHERE detected_at>=? AND detected_at<? AND status NOT IN ('expected','ignored')", (start, end)),
                "dormant_reactivated": scalar("SELECT COUNT(DISTINCT principal_name) FROM principal_change_events WHERE change_type='DORMANT_REACTIVATED' AND detected_at>=? AND detected_at<?", (start, end)),
                "new_service_relationships": scalar("SELECT COUNT(*) FROM principal_change_events WHERE change_type='NEW_TARGET' AND detected_at>=? AND detected_at<?", (start, end)),
                "new_caller_relationships": scalar("SELECT COUNT(*) FROM principal_change_events WHERE change_type='NEW_CALLER' AND detected_at>=? AND detected_at<?", (start, end)),
            }

    def _distribution(self, db, principal: str, table: str, value_select: str,
                      start_ms: int | None = None, end_ms: int | None = None) -> list[dict[str, Any]]:
        if start_ms is None or end_ms is None:
            rows = db.execute(f"SELECT {value_select} value,observation_count requests,first_seen,last_seen FROM {table} WHERE principal_name=? ORDER BY requests DESC", (principal,)).fetchall()
        else:
            column = {"principal_callers": "caller_service", "principal_sources": "caller_ip",
                      "principal_targets": "target_service", "principal_operations": "operation"}[table]
            group = "target_service,operation" if table == "principal_operations" else column
            value = "target_service||'→'||operation" if table == "principal_operations" else column
            rows = db.execute(f"SELECT {value} value,COUNT(*) requests,MIN(timestamp_ms) first_seen,MAX(timestamp_ms) last_seen FROM traces WHERE principal_name=? AND timestamp_ms>=? AND timestamp_ms<? AND COALESCE({column},'')<>'' GROUP BY {group} ORDER BY requests DESC", (principal,start_ms,end_ms)).fetchall()
        total = sum(r["requests"] for r in rows) or 1
        return [{**dict(r), "share": r["requests"] / total} for r in rows]

    def profile(self, principal: str, start_ms: int | None = None, end_ms: int | None = None) -> dict[str, Any] | None:
        with get_connection(self.db_path) as db:
            item = db.execute("SELECT * FROM principals WHERE principal_name=?", (principal,)).fetchone()
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
            changes = self.list_changes(principal=principal, start_ms=start, end_ms=end, limit=100)["items"]
            score_by_type: dict[str, int] = {}
            for change in changes:
                if change["status"] not in {"expected", "ignored"}:
                    score_by_type[change["change_type"]] = max(
                        score_by_type.get(change["change_type"], 0), int(change["score"])
                    )
            score = min(100, sum(score_by_type.values()))
            hourly = [dict(r) for r in db.execute("SELECT * FROM principal_hourly_activity WHERE principal_name=? ORDER BY day_of_week,hour_of_day", (principal,))]
            daily = [dict(r) for r in db.execute("SELECT * FROM principal_daily_stats WHERE principal_name=? ORDER BY day_start", (principal,))]
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
                error_clause = " AND (http_status>=400 OR outcome='failure')" if kind == "errors" else ""
                for row in db.execute(f"SELECT timestamp_ms,caller_service,caller_ip source_ip,target_service,operation,http_status,outcome,trace_id FROM traces WHERE principal_name=? AND timestamp_ms>=? AND timestamp_ms<?{error_clause} ORDER BY timestamp_ms DESC LIMIT ?", (principal,start,end,limit)):
                    items.append({**dict(row), "event_type": "TRACE_ACTIVITY", "severity": "info"})
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
            rows = [dict(r) for r in db.execute(f"SELECT * FROM principal_change_events WHERE {where} ORDER BY detected_at DESC LIMIT ? OFFSET ?", [*all_args,limit,offset])]
            count = db.execute(f"SELECT COUNT(*) FROM principal_change_events WHERE {where}", all_args).fetchone()[0]
            total_unfiltered = db.execute(f"SELECT COUNT(*) FROM principal_change_events WHERE {base_where}", base_args).fetchone()[0]

            # If time filter returned 0 rows but changes exist, fall back to recent changes so page is never blank
            if count == 0 and time_clauses and total_unfiltered > 0:
                fallback_rows = [dict(r) for r in db.execute(f"SELECT * FROM principal_change_events WHERE {base_where} ORDER BY detected_at DESC LIMIT ? OFFSET ?", [*base_args,limit,offset])]
                for row in fallback_rows:
                    try: row["reason"] = json.loads(row.pop("reason_json"))
                    except Exception: row["reason"] = {}
                return {"items": fallback_rows, "count": len(fallback_rows), "total_unfiltered": total_unfiltered, "fallback_applied": True, "limit": limit, "offset": offset}

            for row in rows:
                try: row["reason"] = json.loads(row.pop("reason_json"))
                except Exception: row["reason"] = {}
            return {"items": rows, "count": count, "total_unfiltered": total_unfiltered, "fallback_applied": False, "limit": limit, "offset": offset}

    def update_change(self, change_id: int, status: str) -> dict[str, Any] | None:
        return self.review_change(change_id, action="expected" if status == "expected" else "investigate" if status == "reviewed" else "data_quality" if status == "ignored" else "investigate")

    def review_change(self, change_id: int, action: str, scope: str | None = None,
                      reason: str | None = None, operator: str = "operator",
                      expires_at: int | None = None) -> dict[str, Any] | None:
        now = int(time.time() * 1000)
        with db_transaction(self.db_path) as db:
            row = db.execute("SELECT * FROM principal_change_events WHERE id=?", (change_id,)).fetchone()
            if not row:
                return None
            row_dict = dict(row)
            status = "expected" if action == "expected" else "reviewed" if action == "investigate" else "ignored"
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
                if action == "investigate":
                    db.execute("UPDATE incidents SET status = 'investigating', updated_at = ? WHERE incident_id = ?", (now, incident_id))
                elif action == "expected":
                    db.execute("UPDATE incidents SET status = 'accepted', updated_at = ? WHERE incident_id = ?", (now, incident_id))
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
            rows = [dict(r) for r in db.execute(f"SELECT * FROM incidents WHERE {where} ORDER BY started_at DESC LIMIT ? OFFSET ?", [*args, limit, offset])]
            count = db.execute(f"SELECT COUNT(*) FROM incidents WHERE {where}", args).fetchone()[0]
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
            row = db.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
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
            events = [dict(r) for r in db.execute("SELECT * FROM principal_change_events WHERE incident_id = ? ORDER BY detected_at ASC", (incident_id,)).fetchall()]
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
              FROM principal_change_events
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
        return {"nodes":list(nodes.values()),"edges":edges,"mode":"principal" if principal else "service" if service else "estate"}

    def analytics(self) -> dict[str, Any]:
        with get_connection(self.db_path) as db:
            def rows(order: str, limit: int = 10):
                return [dict(r) for r in db.execute(f"SELECT * FROM principals ORDER BY {order} LIMIT ?", (limit,))]
            return {
                "most_active": rows("total_requests DESC"), "most_callers": rows("unique_callers DESC"),
                "most_sources": rows("unique_sources DESC"), "most_targets": rows("unique_targets DESC"),
                "most_operations": rows("unique_operations DESC"), "newest": rows("first_seen DESC"),
                "most_changed": [dict(r) for r in db.execute("""
                    SELECT p.*, c.changes, c.behavior_score
                    FROM principals p
                    JOIN (
                        SELECT principal_name, count() as changes, sum(score) as behavior_score
                        FROM principal_change_events
                        WHERE status NOT IN ('expected', 'ignored')
                        GROUP BY principal_name
                    ) c ON p.principal_name = c.principal_name
                    ORDER BY c.behavior_score DESC
                    LIMIT 10
                """)],
                "shared_credentials": [dict(r) for r in db.execute("SELECT principal_name,COUNT(*) callers,SUM(observation_count) requests FROM principal_callers GROUP BY principal_name HAVING callers>1 ORDER BY callers DESC LIMIT 20")],
                "source_diversity": rows("unique_sources DESC"),
                "dormant_reactivated": [dict(r) for r in db.execute("""
                    SELECT p.*, c.reactivated_at
                    FROM principals p
                    JOIN (
                        SELECT principal_name, max(detected_at) as reactivated_at
                        FROM principal_change_events
                        WHERE change_type = 'DORMANT_REACTIVATED'
                        GROUP BY principal_name
                    ) c ON p.principal_name = c.principal_name
                    ORDER BY c.reactivated_at DESC
                    LIMIT 20
                """)],
            }

    def service_users(self, service: str, start_ms: int | None, end_ms: int | None) -> list[dict[str, Any]]:
        clauses, args = ["target_service=?"], [service]
        if start_ms is not None: clauses.append("timestamp_ms>=?"); args.append(start_ms)
        if end_ms is not None: clauses.append("timestamp_ms<?"); args.append(end_ms)
        with get_connection(self.db_path) as db:
            return [dict(r) for r in db.execute(f"""SELECT principal_name,COUNT(*) requests,
              COUNT(DISTINCT caller_service) callers,COUNT(DISTINCT operation) operations,
              MIN(timestamp_ms) first_seen,MAX(timestamp_ms) last_seen,
              principal_name IN (SELECT principal_name FROM principal_change_events WHERE target_service=?) recent_change
              FROM traces WHERE principal_name<>'unknown' AND {' AND '.join(clauses)}
              GROUP BY principal_name ORDER BY requests DESC""", [service,*args])]

    def anomaly_users(self, anomaly_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as db:
            anomaly = db.execute("SELECT * FROM anomaly_events WHERE id=?", (anomaly_id,)).fetchone()
            if not anomaly: return None
            target = anomaly["target_service"] or anomaly["caller_service"]
            window_known = anomaly["first_seen"] is not None and anomaly["last_seen"] is not None
            if window_known:
                start, end = int(anomaly["first_seen"]), int(anomaly["last_seen"])
            else:
                center = int(anomaly["detected_at"])
                start, end = center-1_800_000, center+1_800_000
            users = [dict(r) for r in db.execute("""SELECT principal_name,COUNT(*) requests,
              COUNT(*)*1.0/SUM(COUNT(*)) OVER() traffic_share FROM traces
              WHERE principal_name<>'unknown' AND target_service=? AND timestamp_ms>=? AND timestamp_ms<?
              GROUP BY principal_name ORDER BY requests DESC LIMIT 20""", (target,start,end))]
            for user in users:
                user["changes"] = [dict(r) for r in db.execute("SELECT id,change_type,severity,detected_at FROM principal_change_events WHERE principal_name=? AND detected_at>=? AND detected_at<? ORDER BY detected_at DESC LIMIT 10", (user["principal_name"],start,end))]
            return {"anomaly_id":anomaly_id,"service":target,"items":users,
                    "window":{"from":start,"to":end,"source":"telemetry" if window_known else "legacy_context"}}
