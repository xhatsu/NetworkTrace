"""Store anomaly evidence separately from mutable incident presentation state."""
from __future__ import annotations
import json
import time
import hashlib
from typing import Any, Dict, List, Optional
from backend.app.models.anomaly import AnomalyEvent, AnomalyReason
from backend.app.repositories.db_context import get_connection, db_transaction

def deterministic_anomaly_id(anomaly: AnomalyEvent) -> int:
    """Stable detector+dimensions+window identity for retry-safe replacement."""
    identity = "\x1f".join(str(value or "") for value in (
        anomaly.anomaly_type,
        anomaly.caller_service,
        anomaly.target_service,
        anomaly.principal_name,
        anomaly.source_ip,
        anomaly.operation,
        anomaly.first_seen,
        anomaly.last_seen,
    ))
    raw_hash = int.from_bytes(
        hashlib.blake2b(identity.encode("utf-8"), digest_size=8).digest(), "big"
    )
    # Fit strictly within JavaScript Number.MAX_SAFE_INTEGER (2^53 - 1 = 9007199254740991)
    # Using modulo 9000000000000000 ensures it never suffers IEEE-754 precision truncation in frontend web browsers.
    return (raw_hash % 9_000_000_000_000_000) + 1


class AnomalyRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def save_anomalies(self, anomalies: List[AnomalyEvent]) -> None:
        if not anomalies:
            return

        with get_connection(self.db_path) as db:
            # Query recent open anomalies (within the last 30 minutes) to coalesce continuous episodes
            min_ts = min((a.first_seen or a.detected_at or int(time.time() * 1000)) for a in anomalies) - 1800_000
            try:
                recent_open = db.execute("""
                    SELECT id, anomaly_type, caller_service, target_service, principal_name, source_ip, operation, first_seen, last_seen, metadata_json, status, severity, score
                    FROM anomaly_events FINAL
                    WHERE status IN ('open', 'acknowledged') AND COALESCE(last_seen, detected_at) >= ?
                """, (min_ts,)).fetchall()
            except Exception:
                recent_open = []

        # Index active incidents by dimensional signature
        open_by_dim: Dict[tuple, Any] = {}
        for r in recent_open:
            k = (
                r[1] or "",
                r[2] or "",
                r[3] or "",
                r[4] or "",
                r[5] or "",
                r[6] or "",
            )
            # Retain the most recent active record for each signature
            if k not in open_by_dim or (r[8] or 0) > (open_by_dim[k][8] or 0):
                open_by_dim[k] = r

        coalesced_anomalies: List[AnomalyEvent] = []
        for anomaly in anomalies:
            k = (
                anomaly.anomaly_type or "",
                anomaly.caller_service or "",
                anomaly.target_service or "",
                anomaly.principal_name or "",
                anomaly.source_ip or "",
                anomaly.operation or "",
            )
            existing = open_by_dim.get(k)
            new_first = anomaly.first_seen or anomaly.detected_at or int(time.time() * 1000)
            new_last = anomaly.last_seen or (new_first + 300_000)

            # If an open anomaly exists and the new window is contiguous (within 15 minutes of prior last_seen):
            if existing and existing[8] and (new_first - int(existing[8]) <= 900_000):
                # Coalesce into existing incident
                anomaly.id = int(existing[0])
                anomaly.first_seen = int(existing[7]) if existing[7] else new_first
                anomaly.last_seen = max(int(existing[8]), new_last)

                # Keep highest severity / score
                sev_ranks = {"critical": 4, "high": 3, "medium": 2, "low": 1}
                if sev_ranks.get(existing[11], 0) > sev_ranks.get(anomaly.severity, 0):
                    anomaly.severity = existing[11]
                    anomaly.score = max(anomaly.score, existing[12] or 0)

                # Update metadata with occurrence count and total episode duration
                try:
                    meta = json.loads(existing[9]) if existing[9] else {}
                except Exception:
                    meta = {}
                if anomaly.metadata:
                    meta.update(anomaly.metadata)
                meta["occurrences"] = int(meta.get("occurrences", 1)) + 1
                meta["episode_first_seen"] = anomaly.first_seen
                meta["duration_mins"] = round((anomaly.last_seen - anomaly.first_seen) / 60000, 1)
                anomaly.metadata = meta

                # Update local cache so subsequent anomalies in the same batch continue coalescing
                open_by_dim[k] = (existing[0], existing[1], existing[2], existing[3], existing[4], existing[5], existing[6], anomaly.first_seen, anomaly.last_seen, json.dumps(meta), existing[10], anomaly.severity, anomaly.score)
            else:
                if anomaly.id is None:
                    anomaly.id = deterministic_anomaly_id(anomaly)
                if anomaly.metadata is None:
                    anomaly.metadata = {}
                anomaly.metadata.setdefault("occurrences", 1)
                anomaly.metadata.setdefault("duration_mins", round(((anomaly.last_seen or new_last) - (anomaly.first_seen or new_first)) / 60000, 1))
                open_by_dim[k] = (anomaly.id, anomaly.anomaly_type, anomaly.caller_service, anomaly.target_service, anomaly.principal_name, anomaly.source_ip, anomaly.operation, anomaly.first_seen, anomaly.last_seen, json.dumps(anomaly.metadata), anomaly.status, anomaly.severity, anomaly.score)

            coalesced_anomalies.append(anomaly)

        cols = [
            "id", "detected_at", "anomaly_type", "severity", "score", "confidence",
            "caller_service", "target_service", "principal_name", "source_ip", "operation", "instance",
            "baseline_value", "current_value", "delta_percentage", "first_seen", "last_seen",
            "status", "acknowledged", "reason_json", "metadata_json"
        ]
        sql = f"INSERT INTO anomaly_events ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
        with db_transaction(self.db_path) as db:
            db.executemany(sql, [[
                a.id, a.detected_at, a.anomaly_type, a.severity, a.score, a.confidence,
                a.caller_service, a.target_service, a.principal_name, a.source_ip, a.operation, getattr(a, "instance", None),
                a.baseline_value, a.current_value, a.delta_percentage, a.first_seen, a.last_seen,
                a.status, a.acknowledged,
                json.dumps([r.model_dump() for r in a.reasons], separators=(',', ':')),
                json.dumps(a.metadata, separators=(',', ':')),
            ] for a in coalesced_anomalies])

    def list_anomalies(
        self,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        service: Optional[str] = None,
        principal: Optional[str] = None,
        source_ip: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        clauses = []
        args = []
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
            clauses.append("(principal_name = ? OR metadata_json LIKE ?)")
            args.extend([principal, f'%"{principal}"%'])
        if source_ip:
            clauses.append("source_ip = ?")
            args.append(source_ip)

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"""
        SELECT * FROM anomaly_events FINAL
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
            row = db.execute("SELECT * FROM anomaly_events FINAL WHERE id = ?", (anomaly_id,)).fetchone()
            if not row and anomaly_id > 9_000_000_000_000_000:
                # Browser float64 precision loss fallback for any legacy 64-bit IDs (tolerance window of +/- 4096)
                row = db.execute(
                    """SELECT * FROM anomaly_events FINAL 
                       WHERE id >= ? AND id <= ? 
                       ORDER BY abs(CAST(id, 'Int64') - CAST(?, 'Int64')) ASC LIMIT 1""",
                    (max(0, anomaly_id - 4096), anomaly_id + 4096, anomaly_id)
                ).fetchone()
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
            row = db.execute("SELECT id FROM anomaly_events FINAL WHERE id = ? LIMIT 1", (anomaly_id,)).fetchone()
            resolved_id = row[0] if row else None
            if resolved_id is None and anomaly_id > 9_000_000_000_000_000:
                fallback = db.execute(
                    """SELECT id FROM anomaly_events FINAL 
                       WHERE id >= ? AND id <= ? 
                       ORDER BY abs(CAST(id, 'Int64') - CAST(?, 'Int64')) ASC LIMIT 1""",
                    (max(0, anomaly_id - 4096), anomaly_id + 4096, anomaly_id)
                ).fetchone()
                if fallback:
                    resolved_id = fallback[0]
            if resolved_id is None:
                return False
            db.execute("UPDATE anomaly_events SET status = ? WHERE id = ?", (status, resolved_id))
            return True
