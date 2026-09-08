from __future__ import annotations
import json
import time
from typing import Any, Dict, List, Optional
from backend.app.models.anomaly import AnomalyEvent, AnomalyReason
from backend.app.repositories.db_context import get_connection, db_transaction

class AnomalyRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def save_anomalies(self, anomalies: List[AnomalyEvent]) -> None:
        if not anomalies:
            return
        sql = """
        INSERT INTO anomaly_events (
          detected_at, anomaly_type, severity, score, confidence,
          caller_service, target_service, principal_name, operation, instance,
          baseline_value, current_value, delta_percentage, first_seen, last_seen,
          status, acknowledged, reason_json, metadata_json
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
          SELECT 1 FROM anomaly_events
          WHERE anomaly_type=? AND caller_service IS ? AND target_service IS ?
            AND principal_name IS ? AND operation IS ? AND first_seen IS ? AND last_seen IS ?
        )
        """
        with db_transaction(self.db_path) as db:
            db.executemany(sql, [[
                a.detected_at, a.anomaly_type, a.severity, a.score, a.confidence,
                a.caller_service, a.target_service, a.principal_name, a.operation, a.instance,
                a.baseline_value, a.current_value, a.delta_percentage, a.first_seen, a.last_seen,
                a.status, a.acknowledged,
                json.dumps([r.dict() for r in a.reasons], separators=(',', ':')),
                json.dumps(a.metadata, separators=(',', ':')),
                a.anomaly_type, a.caller_service, a.target_service,
                a.principal_name, a.operation, a.first_seen, a.last_seen,
            ] for a in anomalies])

    def list_anomalies(
        self,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        service: Optional[str] = None,
        principal: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        clauses = []
        args: List[Any] = []
        if start_ms is not None:
            # Time filters refer to when the anomaly was observed in telemetry,
            # not when a background worker happened to evaluate the window.
            clauses.append("COALESCE(last_seen, detected_at) >= ?")
            args.append(start_ms)
        if end_ms is not None:
            clauses.append("COALESCE(first_seen, detected_at) < ?")
            args.append(end_ms)
        if status:
            clauses.append("status = ?")
            args.append(status)
        if severity:
            clauses.append("severity = ?")
            args.append(severity)
        if service:
            clauses.append("(target_service = ? OR caller_service = ?)")
            args.extend([service, service])
        if principal:
            clauses.append("""(principal_name = ? OR EXISTS (
              SELECT 1 FROM json_each(
                CASE WHEN json_valid(metadata_json) THEN metadata_json ELSE '{}' END,
                '$.principals'
              ) WHERE json_each.value = ?
            ))""")
            args.extend([principal, principal])

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"""
        SELECT * FROM anomaly_events
        WHERE {where}
        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                 detected_at DESC
        LIMIT ?
        """
        args.append(limit)

        with get_connection(self.db_path) as db:
            rows = [dict(r) for r in db.execute(sql, args)]
            for r in rows:
                if r.get("reason_json"):
                    try: r["reasons"] = json.loads(r["reason_json"])
                    except Exception: r["reasons"] = []
                if r.get("metadata_json"):
                    try: r["metadata"] = json.loads(r["metadata_json"])
                    except Exception: r["metadata"] = {}
            return rows

    def get_anomaly(self, anomaly_id: int) -> Optional[Dict[str, Any]]:
        with get_connection(self.db_path) as db:
            row = db.execute("SELECT * FROM anomaly_events WHERE id = ?", (anomaly_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            if res.get("reason_json"):
                try: res["reasons"] = json.loads(res["reason_json"])
                except Exception: res["reasons"] = []
            if res.get("metadata_json"):
                try: res["metadata"] = json.loads(res["metadata_json"])
                except Exception: res["metadata"] = {}
            return res

    def update_status(self, anomaly_id: int, status: str) -> bool:
        with db_transaction(self.db_path) as db:
            db.execute("UPDATE anomaly_events SET status = ? WHERE id = ?", (status, anomaly_id))
            return db.total_changes > 0
