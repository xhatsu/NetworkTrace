from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from backend.app.models.topology import ServiceEdge, PrincipalServiceEdge, TopologyGraph, TopologyNode, TopologyEdge
from backend.app.repositories.db_context import get_connection, db_transaction

class TopologyRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def save_edges(self, edges: List[ServiceEdge], principal_edges: List[PrincipalServiceEdge]) -> None:
        if edges:
            sql_edge = """
            INSERT INTO service_edges (
              caller_service, target_service, first_seen, last_seen, request_count,
              error_count, error_rate, avg_latency, p95_latency, principal_count, operation_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(caller_service, target_service) DO UPDATE SET
              first_seen=MIN(service_edges.first_seen, excluded.first_seen),
              last_seen=MAX(service_edges.last_seen, excluded.last_seen),
              request_count=service_edges.request_count + excluded.request_count,
              error_count=service_edges.error_count + excluded.error_count,
              error_rate=ROUND((service_edges.error_count + excluded.error_count)*1.0/(service_edges.request_count + excluded.request_count), 4),
              avg_latency=excluded.avg_latency,
              p95_latency=excluded.p95_latency,
              principal_count=MAX(service_edges.principal_count, excluded.principal_count),
              operation_count=MAX(service_edges.operation_count, excluded.operation_count)
            """
            with db_transaction(self.db_path) as db:
                db.executemany(sql_edge, [[
                    e.caller_service, e.target_service, e.first_seen, e.last_seen,
                    e.request_count, e.error_count, e.error_rate, e.avg_latency,
                    e.p95_latency, e.principal_count, e.operation_count
                ] for e in edges])

        if principal_edges:
            sql_pe = """
            INSERT INTO principal_service_edges (
              principal_name, caller_service, target_service, first_seen, last_seen,
              request_count, error_rate, p95_latency
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(principal_name, caller_service, target_service) DO UPDATE SET
              first_seen=MIN(principal_service_edges.first_seen, excluded.first_seen),
              last_seen=MAX(principal_service_edges.last_seen, excluded.last_seen),
              request_count=principal_service_edges.request_count + excluded.request_count,
              error_rate=excluded.error_rate,
              p95_latency=excluded.p95_latency
            """
            with db_transaction(self.db_path) as db:
                db.executemany(sql_pe, [[
                    p.principal_name, p.caller_service, p.target_service,
                    p.first_seen, p.last_seen, p.request_count, p.error_rate, p.p95_latency
                ] for p in principal_edges])

    def get_topology(self, start_sec: int, end_sec: int) -> Dict[str, Any]:
        time_span = max(1, end_sec - start_sec)
        with get_connection(self.db_path) as db:
            # Query edges from metric_buckets within time range
            edge_rows = db.execute("""
                SELECT
                  caller_service,
                  target_service,
                  SUM(request_count) as total_requests,
                  SUM(error_count) as total_errors,
                  ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count), 0), 4) as error_rate,
                  ROUND(SUM(latency_sum) / NULLIF(SUM(request_count), 0), 2) as avg_latency,
                  ROUND(MAX(latency_p95), 2) as p95_latency,
                  COUNT(DISTINCT principal_name) as principal_count,
                  COUNT(DISTINCT operation) as operation_count
                FROM metric_buckets
                WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                  AND caller_service != '' AND target_service != ''
                GROUP BY caller_service, target_service
                ORDER BY total_requests DESC
            """, (start_sec, end_sec)).fetchall()

            # If metric_buckets is empty, fallback to service_edges table
            if not edge_rows:
                edge_rows = db.execute("""
                    SELECT
                      caller_service,
                      target_service,
                      request_count as total_requests,
                      error_count as total_errors,
                      error_rate,
                      avg_latency,
                      p95_latency,
                      principal_count,
                      operation_count
                    FROM service_edges
                    ORDER BY request_count DESC
                    LIMIT 200
                """).fetchall()

            edges = []
            service_stats: Dict[str, Dict[str, Any]] = {}

            # Prefetch top principals per edge in 1 grouped query
            p_rows = db.execute("""
                SELECT caller_service, target_service, principal_name, SUM(request_count) as requests
                FROM metric_buckets
                WHERE bucket_size=60 AND bucket_start >= ? AND bucket_start < ?
                  AND caller_service != '' AND target_service != '' AND principal_name != ''
                GROUP BY caller_service, target_service, principal_name
                ORDER BY requests DESC
            """, (start_sec, end_sec)).fetchall()
            edge_principals: Dict[tuple, List[Dict[str, Any]]] = {}
            for pr in p_rows:
                key = (pr["caller_service"], pr["target_service"])
                cur = edge_principals.setdefault(key, [])
                if len(cur) < 3:
                    cur.append({"principal_name": pr["principal_name"], "requests": pr["requests"]})

            # Prefetch top operations per edge in 1 grouped query
            op_rows = db.execute("""
                SELECT caller_service, target_service, operation, SUM(request_count) as requests
                FROM metric_buckets
                WHERE bucket_size=60 AND bucket_start >= ? AND bucket_start < ?
                  AND caller_service != '' AND target_service != '' AND operation != ''
                GROUP BY caller_service, target_service, operation
                ORDER BY requests DESC
            """, (start_sec, end_sec)).fetchall()
            edge_operations: Dict[tuple, List[Dict[str, Any]]] = {}
            for opr in op_rows:
                key = (opr["caller_service"], opr["target_service"])
                cur = edge_operations.setdefault(key, [])
                if len(cur) < 3:
                    cur.append({"operation": opr["operation"], "requests": opr["requests"]})

            for r in edge_rows:
                c = r["caller_service"]
                t = r["target_service"]
                reqs = r["total_requests"] or 0
                errs = r["total_errors"] or 0
                rps = round(reqs / time_span, 2)
                p95 = r["p95_latency"] or 0.0
                err_rate = r["error_rate"] or 0.0

                top_p = edge_principals.get((c, t), [])
                top_op = edge_operations.get((c, t), [])

                edges.append({
                    "caller_service": c,
                    "source": c,
                    "target_service": t,
                    "target": t,
                    "rps": rps,
                    "request_count": reqs,
                    "requests": reqs,
                    "p95_latency": p95,
                    "avg_ms": r["avg_latency"] or p95,
                    "error_rate": err_rate,
                    "failure_rate": err_rate,
                    "evidence": "confirmed",
                    "evidence_detail": "OTel Trace parent-child relationship",
                    "freshness_ms": int(time.time() * 1000),
                    "principal_count": r["principal_count"] or 1,
                    "operation_count": r["operation_count"] or 1,
                    "top_principals": top_p,
                    "top_operations": top_op,
                    "anomaly_score": 0
                })

                for svc in (c, t):
                    if svc not in service_stats:
                        service_stats[svc] = {"requests": 0, "errors": 0, "p95": 0.0}
                    service_stats[svc]["requests"] += reqs
                    service_stats[svc]["errors"] += errs
                    service_stats[svc]["p95"] = max(service_stats[svc]["p95"], p95)

            # Query anomaly status per service
            anomaly_services = {row[0] for row in db.execute("""
                SELECT target_service FROM anomaly_events
                WHERE status = 'open'
            """).fetchall() if row[0]}

            # Metadata from services table
            meta_rows = {r["name"]: dict(r) for r in db.execute("SELECT name, environment, service_group, service_module, last_seen_ms FROM services").fetchall()}

            nodes = []
            for svc, stats in service_stats.items():
                reqs = stats["requests"]
                meta = meta_rows.get(svc, {})
                nodes.append({
                    "name": svc,
                    "service_group": meta.get("service_group") or "Core",
                    "service_module": meta.get("service_module") or "Default",
                    "last_seen_ms": meta.get("last_seen_ms") or (end_sec * 1000),
                    "type": "database" if any(db_word in svc.lower() for db_word in ("db", "sql", "cache", "redis", "oracle")) else "service",
                    "rps": round(reqs / time_span, 2),
                    "p95_ms": stats["p95"],
                    "error_rate": round(stats["errors"] / max(1, reqs), 4),
                    "anomaly_status": "abnormal" if svc in anomaly_services else "normal",
                    "environment": meta.get("environment") or "production"
                })

            return {"nodes": nodes, "edges": edges, "unknown_callers_preserved": True}

    def get_service_dependencies(self, service: str, start_sec: int, end_sec: int) -> Dict[str, Any]:
        with get_connection(self.db_path) as db:
            callers = [dict(r) for r in db.execute("""
                SELECT caller_service as name, SUM(request_count) as requests,
                       ROUND(MAX(latency_p95), 2) as p95_latency,
                       ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count), 0), 4) as error_rate
                FROM metric_buckets
                WHERE target_service = ? AND bucket_size=60 AND bucket_start >= ? AND bucket_start < ?
                GROUP BY caller_service ORDER BY requests DESC
            """, (service, start_sec, end_sec)).fetchall()]

            downstreams = [dict(r) for r in db.execute("""
                SELECT target_service as name, SUM(request_count) as requests,
                       ROUND(MAX(latency_p95), 2) as p95_latency,
                       ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count), 0), 4) as error_rate
                FROM metric_buckets
                WHERE caller_service = ? AND bucket_size=60 AND bucket_start >= ? AND bucket_start < ?
                GROUP BY target_service ORDER BY requests DESC
            """, (service, start_sec, end_sec)).fetchall()]

            return {"service": service, "callers": callers, "dependencies": downstreams}
