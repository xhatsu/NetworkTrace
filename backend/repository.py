"""Compatibility repository surface retained while ClickHouse is the live store.

The historical class names let dashboard and migration callers evolve without
changing public API behavior during the single-store cutover.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from .config import settings
from .histogram import Histogram, merged_percentiles
from backend.app.repositories.db_context import get_connection, db_transaction
from backend.app.repositories.clickhouse_migrator import run_clickhouse_migrations


class TraceRepository(Protocol):
    def dashboard_summary(self, start_ms: int, end_ms: int, filters: dict[str, str | None]) -> dict[str, Any]: ...
    def dashboard_series(self, start_ms: int, end_ms: int, filters: dict[str, str | None]) -> list[dict[str, Any]]: ...


class StorageRepository:
    def __init__(self, path: Path | str | None = None):
        # ``path`` selects an isolated ClickHouse database (tests); production uses the settings database.
        self._custom_path = str(path) if path else None

    def connect(self) -> Any:
        return get_connection(self._custom_path)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with db_transaction(self._custom_path) as connection:
            yield connection

    def migrate(self) -> None:
        run_clickhouse_migrations(self._custom_path)

    @staticmethod
    def _where(start_ms: int, end_ms: int, filters: dict[str, str | None], alias: str = "") -> tuple[str, list[Any]]:
        p = f"{alias}." if alias else ""
        clauses = [f"{p}bucket_ms>=?", f"{p}bucket_ms<?"]
        args: list[Any] = [start_ms - start_ms % 60_000, end_ms]
        mapping = {"environment": "environment", "service": "service_name", "operation": "operation", "account": "account_username"}
        for key, column in mapping.items():
            if filters.get(key):
                clauses.append(f"{p}{column}=?")
                args.append(filters[key])
        # Rollup group/module are resolved from service inventory.
        if filters.get("group"):
            clauses.append(f"{p}service_name IN (SELECT name FROM services WHERE service_group=?)")
            args.append(filters["group"])
        if filters.get("module"):
            clauses.append(f"{p}service_name IN (SELECT name FROM services WHERE service_module=?)")
            args.append(filters["module"])
        return " AND ".join(clauses), args

    def dashboard_summary(self, start_ms: int, end_ms: int, filters: dict[str, str | None]) -> dict[str, Any]:
        with self.connect() as db:
            mb_count_row = db.execute("SELECT count() FROM metric_buckets").fetchone()
            use_mb = bool(mb_count_row and mb_count_row[0] > 0)

            if use_mb:
                start_sec = int(start_ms / 1000)
                end_sec = int(end_ms / 1000)
                clauses = ["bucket_size = 60", "bucket_start >= ?", "bucket_start < ?"]
                args: list[Any] = [start_sec, end_sec]
                if filters.get("service"):
                    clauses.append("target_service = ?")
                    args.append(filters["service"])
                if filters.get("operation"):
                    clauses.append("operation = ?")
                    args.append(filters["operation"])
                if filters.get("account"):
                    clauses.append("principal_name = ?")
                    args.append(filters["account"])
                where = " AND ".join(clauses)

                row = db.execute(f"""
                    SELECT
                        COALESCE(SUM(request_count), 0) AS total_requests,
                        COALESCE(SUM(error_count), 0) AS status_5xx,
                        COUNT(DISTINCT target_service) AS active_services,
                        COUNT(DISTINCT principal_name) AS active_accounts,
                        COALESCE(MAX(latency_p95), 0.0) AS p95_latency_ms
                    FROM metric_buckets
                    WHERE {where}
                """, args).fetchone()

                total_requests = int(row[0]) if row else 0
                status_5xx = int(row[1]) if row else 0
                services = int(row[2]) if row else 0
                accounts = int(row[3]) if row else 0
                p95_ms = float(row[4]) if row else 0.0

                duration_s = max(1.0, (end_ms - start_ms) / 1000.0)
                observed_rps = round(total_requests / duration_s, 2)

                anom_row = db.execute(
                    "SELECT COUNT(*) FROM anomalies WHERE status IN ('open','acknowledged') AND window_end_ms>=? AND window_start_ms<?",
                    (start_ms, end_ms)
                ).fetchone()
                active_anomalies = int(anom_row[0]) if anom_row else 0

                latest_row = db.execute("SELECT MAX(created_at) FROM traces").fetchone()
                latest = int(latest_row[0]) if (latest_row and latest_row[0]) else None

                return {
                    "observed_rps": observed_rps,
                    "observed_tps": observed_rps,
                    "total_requests": total_requests,
                    "active_services": services,
                    "active_accounts": accounts,
                    "p95_latency_ms": p95_ms,
                    "http_5xx_rate": round(status_5xx / max(1, total_requests), 4),
                    "slow_request_rate": 0.0,
                    "active_anomalies": active_anomalies,
                    "latest_ingested_ms": latest,
                    "sampling_coverage": "100%",
                    "tps_equals_rps": True,
                    "sample_count": total_requests,
                }

            where, args = self._where(start_ms, end_ms, filters)
            if not filters.get("operation"):
                where += " AND operation=''"
            if not filters.get("account"):
                where += " AND account_username=''"
            rows = db.execute(f"SELECT * FROM latency_rollups WHERE {where}", args).fetchall()
            duration_s = max(1.0, (end_ms - start_ms) / 1000)
            totals = {key: sum(row[key] for row in rows) for key in ("request_count", "server_count", "http_count", "status_5xx", "slow_count")}
            hist = merged_percentiles([row["histogram_json"] for row in rows])
            services = len({row["service_name"] for row in rows if row["server_count"]})
            account_where, account_args = self._where(start_ms,end_ms,{**filters,"operation":None,"account":None})
            accounts = db.execute(f"SELECT COUNT(DISTINCT account_username) FROM latency_rollups WHERE {account_where} AND operation='' AND account_username<>''",account_args).fetchone()[0]
            anomalies = db.execute("SELECT COUNT(*) FROM anomalies WHERE status IN ('open','acknowledged') AND window_end_ms>=? AND window_start_ms<?", (start_ms, end_ms)).fetchone()[0]
            latest = db.execute("SELECT MAX(ingested_ms) FROM events").fetchone()[0]
            all_http = totals["server_count"] == totals["http_count"] and totals["server_count"] > 0
            return {
                "observed_rps": totals["http_count"] / duration_s,
                "observed_tps": totals["server_count"] / duration_s,
                "total_requests": totals["http_count"], "active_services": services,
                "active_accounts": accounts, "p95_latency_ms": hist["p95_ms"],
                "http_5xx_rate": totals["status_5xx"] / max(1, totals["http_count"]),
                "slow_request_rate": totals["slow_count"] / max(1, totals["server_count"]),
                "active_anomalies": anomalies, "latest_ingested_ms": latest,
                "sampling_coverage": "unknown", "tps_equals_rps": all_http,
                "sample_count": totals["server_count"],
            }

    def dashboard_series(self, start_ms: int, end_ms: int, filters: dict[str, str | None]) -> list[dict[str, Any]]:
        with self.connect() as db:
            mb_count_row = db.execute("SELECT count() FROM metric_buckets").fetchone()
            use_mb = bool(mb_count_row and mb_count_row[0] > 0)

            if use_mb:
                start_sec = int(start_ms / 1000)
                end_sec = int(end_ms / 1000)
                clauses = ["bucket_size = 60", "bucket_start >= ?", "bucket_start < ?"]
                args: list[Any] = [start_sec, end_sec]
                if filters.get("service"):
                    clauses.append("target_service = ?")
                    args.append(filters["service"])
                if filters.get("operation"):
                    clauses.append("operation = ?")
                    args.append(filters["operation"])
                if filters.get("account"):
                    clauses.append("principal_name = ?")
                    args.append(filters["account"])
                where = " AND ".join(clauses)

                rows = db.execute(f"""
                    SELECT
                        bucket_start * 1000 AS timestamp_ms,
                        ROUND(SUM(request_count) / 60.0, 2) AS rps,
                        ROUND(SUM(request_count) / 60.0, 2) AS tps,
                        ROUND(AVG(latency_avg), 1) AS p50_ms,
                        ROUND(MAX(latency_p95), 1) AS p95_ms,
                        ROUND(MAX(latency_p99), 1) AS p99_ms,
                        ROUND(CASE WHEN SUM(request_count) > 0 THEN SUM(error_count) * 1.0 / SUM(request_count) ELSE 0 END, 4) AS http_5xx_rate,
                        SUM(request_count) AS sample_count
                    FROM metric_buckets
                    WHERE {where}
                    GROUP BY bucket_start
                    ORDER BY bucket_start ASC
                """, args).fetchall()

                output = []
                for r in rows:
                    rps = float(r["rps"])
                    output.append({
                        "timestamp_ms": int(r["timestamp_ms"]),
                        "rps": rps,
                        "tps": float(r["tps"]),
                        "baseline_rps": rps,
                        "p50_ms": float(r["p50_ms"]),
                        "p95_ms": float(r["p95_ms"]),
                        "p99_ms": float(r["p99_ms"]),
                        "http_4xx_rate": 0.0,
                        "http_5xx_rate": float(r["http_5xx_rate"]),
                        "success_rate": round(1.0 - float(r["http_5xx_rate"]), 4),
                        "failure_rate": float(r["http_5xx_rate"]),
                        "sample_count": int(r["sample_count"]),
                    })
                return output

            where, args = self._where(start_ms, end_ms, filters)
            if not filters.get("operation"): where += " AND operation=''"
            if not filters.get("account"): where += " AND account_username=''"
            rows = db.execute(f"SELECT * FROM latency_rollups WHERE {where} ORDER BY bucket_ms", args).fetchall()
            grouped: dict[int, dict[str, Any]] = {}
            for row in rows:
                item = grouped.setdefault(row["bucket_ms"], {"timestamp_ms": row["bucket_ms"], "server": 0, "http": 0, "count": 0, "4xx": 0, "5xx": 0, "success": 0, "failure": 0, "hist": Histogram.empty()})
                item["server"] += row["server_count"]; item["http"] += row["http_count"]; item["count"] += row["request_count"]; item["4xx"] += row["status_4xx"]; item["5xx"] += row["status_5xx"]; item["success"] += row["success_count"]; item["failure"] += row["failure_count"]
                item["hist"].merge(Histogram.loads(row["histogram_json"]))
            output = []
            rates = [v["http"] / 60 for v in grouped.values()]
            baseline = sorted(rates)[len(rates) // 2] if rates else 0
            for value in grouped.values():
                output.append({"timestamp_ms": value["timestamp_ms"], "rps": value["http"] / 60, "tps": value["server"] / 60,
                    "baseline_rps": baseline, "p50_ms": value["hist"].percentile(.5), "p95_ms": value["hist"].percentile(.95),
                    "p99_ms": value["hist"].percentile(.99), "http_4xx_rate": value["4xx"] / max(1, value["http"]), "http_5xx_rate": value["5xx"] / max(1, value["http"]), "success_rate": value["success"] / max(1,value["server"]), "failure_rate": value["failure"] / max(1,value["server"]), "sample_count": value["server"]})
            return output

    @staticmethod
    def _event_where(start_ms: int, end_ms: int, filters: dict[str, str | None]) -> tuple[str, list[Any]]:
        clauses = ["timestamp_ms>=?", "timestamp_ms<?"]
        args: list[Any] = [start_ms, end_ms]
        mapping = {"environment": "environment", "group": "service_group", "module": "service_module", "service": "service_name", "operation": "operation", "account": "account_username"}
        for key, column in mapping.items():
            if filters.get(key): clauses.append(f"{column}=?"); args.append(filters[key])
        return " AND ".join(clauses), args

    def rankings(self, start_ms: int, end_ms: int, filters: dict[str, str | None]) -> dict[str, Any]:
        with self.connect() as db:
            mb_count_row = db.execute("SELECT count() FROM metric_buckets").fetchone()
            use_mb = bool(mb_count_row and mb_count_row[0] > 0)

            if use_mb:
                start_sec = int(start_ms / 1000)
                end_sec = int(end_ms / 1000)
                services = [dict(r) for r in db.execute("""
                    SELECT
                        target_service AS name,
                        SUM(request_count) AS requests,
                        ROUND(AVG(latency_avg), 1) AS avg_ms,
                        ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) AS failure_rate
                    FROM metric_buckets
                    WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                    GROUP BY target_service ORDER BY requests DESC LIMIT 8
                """, (start_sec, end_sec)).fetchall()]

                operations = [dict(r) for r in db.execute("""
                    SELECT
                        target_service AS service_name,
                        operation AS name,
                        SUM(request_count) AS requests,
                        ROUND(AVG(latency_avg), 1) AS avg_ms,
                        ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) AS slow_rate
                    FROM metric_buckets
                    WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                    GROUP BY target_service, operation ORDER BY requests DESC LIMIT 10
                """, (start_sec, end_sec)).fetchall()]

                accounts = [dict(r) for r in db.execute("""
                    SELECT
                        principal_name AS name,
                        SUM(request_count) AS requests
                    FROM metric_buckets
                    WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ? AND principal_name != ''
                    GROUP BY principal_name ORDER BY requests DESC LIMIT 8
                """, (start_sec, end_sec)).fetchall()]

                duration = max(60, end_sec - start_sec)
                prev_start = start_sec - duration
                prev_end = start_sec
                cur_ops = {
                    (r["service_name"], r["name"]): r
                    for r in db.execute("""
                        SELECT target_service as service_name, operation as name,
                               COALESCE(MAX(latency_p95), 0.0) as current_p95_ms,
                               SUM(request_count) as current_samples
                        FROM metric_buckets
                        WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                        GROUP BY target_service, operation
                    """, (start_sec, end_sec)).fetchall()
                }
                prev_ops = {
                    (r["service_name"], r["name"]): r
                    for r in db.execute("""
                        SELECT target_service as service_name, operation as name,
                               COALESCE(MAX(latency_p95), 0.0) as baseline_p95_ms,
                               SUM(request_count) as baseline_samples
                        FROM metric_buckets
                        WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                        GROUP BY target_service, operation
                    """, (prev_start, prev_end)).fetchall()
                }
                degraded = []
                for key, cur in cur_ops.items():
                    prev = prev_ops.get(key)
                    cur_p95 = float(cur["current_p95_ms"])
                    cur_samples = int(cur["current_samples"])
                    base_p95 = float(prev["baseline_p95_ms"]) if prev else 0.0
                    base_samples = int(prev["baseline_samples"]) if prev else 0
                    if cur_samples < 5 or base_samples < 5:
                        continue
                    abs_change = round(cur_p95 - base_p95, 2)
                    rel_change = round((cur_p95 - base_p95) / max(1.0, base_p95), 4) if base_p95 > 0 else None
                    degraded.append({
                        "service_name": cur["service_name"],
                        "name": cur["name"],
                        "current_p95_ms": cur_p95,
                        "baseline_p95_ms": base_p95,
                        "absolute_change_ms": abs_change,
                        "relative_change": rel_change,
                        "current_samples": cur_samples,
                        "baseline_samples": base_samples,
                    })
                return {
                    "services": services,
                    "operations": operations,
                    "accounts": accounts,
                    "degraded_absolute": sorted(degraded, key=lambda x: x["absolute_change_ms"], reverse=True)[:8],
                    "degraded_relative": sorted([d for d in degraded if d["relative_change"] is not None], key=lambda x: x["relative_change"], reverse=True)[:8],
                }

            where, args = self._where(start_ms,end_ms,filters)
            service_level="" if filters.get("operation") else " AND operation=''"
            service_level+="" if filters.get("account") else " AND account_username=''"
            services = [dict(r) for r in db.execute(f"SELECT service_name AS name,SUM(server_count) requests,ROUND(SUM(duration_sum_us)/1000.0/MAX(1,SUM(server_count)),1) avg_ms,SUM(failure_count)*1.0/MAX(1,SUM(server_count)) failure_rate FROM latency_rollups WHERE {where}{service_level} GROUP BY service_name ORDER BY requests DESC LIMIT 8",args)]
            operation_level="" if filters.get("account") else " AND account_username=''"
            if not filters.get("operation"): operation_level+=" AND operation<>''"
            operations = [dict(r) for r in db.execute(f"SELECT service_name,operation name,SUM(server_count) requests,ROUND(SUM(duration_sum_us)/1000.0/MAX(1,SUM(server_count)),1) avg_ms,SUM(slow_count)*1.0/MAX(1,SUM(server_count)) slow_rate FROM latency_rollups WHERE {where}{operation_level} GROUP BY service_name,operation HAVING requests>0 ORDER BY requests DESC LIMIT 10",args)]
            account_filters={**filters,"account":None};account_where,account_args=self._where(start_ms,end_ms,account_filters)
            account_level="" if filters.get("operation") else " AND operation=''"
            if filters.get("account"): account_level+=" AND account_username=?";account_args.append(filters["account"])
            else: account_level+=" AND account_username<>''"
            accounts = [dict(r) for r in db.execute(f"SELECT account_username name,SUM(server_count) requests FROM latency_rollups WHERE {account_where}{account_level} GROUP BY account_username ORDER BY requests DESC LIMIT 8",account_args)]
            duration=end_ms-start_ms
            def operation_percentiles(window_start:int,window_end:int) -> dict[tuple[str,str],dict[str,Any]]:
                roll_where,roll_args=self._where(window_start,window_end,{**filters,"account":None})
                roll_where += " AND account_username='' AND operation<>''"
                with self.connect() as connection:
                    rollups=connection.execute(f"SELECT service_name,operation,request_count,histogram_json FROM latency_rollups WHERE {roll_where}",roll_args)
                    grouped: dict[tuple[str,str],dict[str,Any]]={}
                    for row in rollups:
                        key=(row["service_name"],row["operation"]);item=grouped.setdefault(key,{"hist":Histogram.empty(),"samples":0})
                        item["hist"].merge(Histogram.loads(row["histogram_json"]));item["samples"]+=row["request_count"]
                return {key:{"p95_ms":item["hist"].percentile(.95),"samples":item["samples"]} for key,item in grouped.items()}
            current_ops=operation_percentiles(start_ms,end_ms)
            previous_start=start_ms-7*86_400_000 if filters.get("comparison")=="week" else start_ms-duration
            previous_end=previous_start+duration
            previous_ops={} if filters.get("comparison")=="none" else operation_percentiles(previous_start,previous_end)
            degraded=[]
            for (service,name),current in current_ops.items():
                previous=previous_ops.get((service,name))
                if not previous or current["samples"]<5 or previous["samples"]<5: continue
                absolute=current["p95_ms"]-previous["p95_ms"];relative=absolute/previous["p95_ms"] if previous["p95_ms"] else None
                degraded.append({"service_name":service,"name":name,"current_p95_ms":current["p95_ms"],"baseline_p95_ms":previous["p95_ms"],"absolute_change_ms":absolute,"relative_change":relative,"current_samples":current["samples"],"baseline_samples":previous["samples"]})
            return {"services": services, "operations": operations, "accounts": accounts,
                "degraded_absolute":sorted(degraded,key=lambda x:x["absolute_change_ms"],reverse=True)[:8],
                "degraded_relative":sorted([x for x in degraded if x["relative_change"] is not None],key=lambda x:x["relative_change"],reverse=True)[:8]}

    def service_detail(self, name: str, start_ms: int, end_ms: int) -> dict[str, Any] | None:
        with self.connect() as db:
            service = db.execute("SELECT * FROM services WHERE name=?", (name,)).fetchone()
            if not service: return None
            rows = db.execute("SELECT operation, COUNT(*) count, SUM(duration_us) duration, SUM(status_code BETWEEN 200 AND 299) status_2xx, SUM(status_code BETWEEN 400 AND 499) status_4xx, SUM(status_code>=500) failures, SUM(duration_us>=?) slow, GROUP_CONCAT(duration_us) durations FROM events WHERE service_name=? AND timestamp_ms>=? AND timestamp_ms<? AND span_kind='server' GROUP BY operation ORDER BY count DESC LIMIT 100", (settings.slow_threshold_us, name, start_ms, end_ms)).fetchall()
            operations = []
            for row in rows:
                values = sorted(int(v) for v in row["durations"].split(","))
                pct = lambda q: values[min(len(values)-1, int((len(values)-1)*q))] / 1000
                operations.append({"name": row["operation"], "requests": row["count"], "p50_ms": pct(.5), "p95_ms": pct(.95), "p99_ms": pct(.99), "slow_rate": row["slow"]/row["count"], "failure_rate": row["failures"]/row["count"], "status_2xx":row["status_2xx"],"status_4xx":row["status_4xx"],"status_5xx":row["failures"]})
            accounts = [dict(r) for r in db.execute("SELECT COALESCE(account_username,'Unknown') username,COUNT(*) requests FROM events WHERE service_name=? AND timestamp_ms>=? AND timestamp_ms<? GROUP BY account_username ORDER BY requests DESC LIMIT 20", (name,start_ms,end_ms))]
            instances = [dict(r) for r in db.execute("SELECT COALESCE(node_name,'Unknown') name,operation,COUNT(*) requests,ROUND(AVG(duration_us)/1000.0,1) avg_ms FROM events WHERE service_name=? AND timestamp_ms>=? AND timestamp_ms<? GROUP BY node_name,operation ORDER BY requests DESC", (name,start_ms,end_ms))]
            incoming = [dict(r) for r in db.execute("SELECT source_service name,SUM(request_count) requests,evidence FROM topology_edges WHERE target_service=? AND bucket_ms>=? AND bucket_ms<? GROUP BY source_service,evidence ORDER BY requests DESC", (name,start_ms,end_ms))]
            outgoing = [dict(r) for r in db.execute("SELECT target_service name,SUM(request_count) requests,evidence FROM topology_edges WHERE source_service=? AND bucket_ms>=? AND bucket_ms<? GROUP BY target_service,evidence ORDER BY requests DESC", (name,start_ms,end_ms))]
        return {"service": dict(service), "operations": operations, "accounts": accounts, "instances": instances, "incoming": incoming, "outgoing": outgoing}

    def account_detail(self, username: str, start_ms: int, end_ms: int) -> dict[str, Any] | None:
        with self.connect() as db:
            account = db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
            if not account: return None
            targets = [dict(r) for r in db.execute("SELECT service_name,operation,COUNT(*) requests,SUM(status_code IN (401,403)) denied FROM events WHERE account_username=? AND timestamp_ms>=? AND timestamp_ms<? GROUP BY service_name,operation ORDER BY requests DESC LIMIT 100", (username,start_ms,end_ms))]
            hourly = [dict(r) for r in db.execute("SELECT CAST(strftime('%H',timestamp_ms/1000,'unixepoch') AS INTEGER) hour,COUNT(*) requests FROM events WHERE account_username=? AND timestamp_ms>=? AND timestamp_ms<? GROUP BY hour ORDER BY hour", (username,start_ms,end_ms))]
            weekday = [dict(r) for r in db.execute("SELECT CAST(strftime('%w',timestamp_ms/1000,'unixepoch') AS INTEGER) day,COUNT(*) requests FROM events WHERE account_username=? AND timestamp_ms>=? AND timestamp_ms<? GROUP BY day ORDER BY day", (username,start_ms,end_ms))]
        return {"account": dict(account), "targets": targets, "hourly": hourly, "weekday": weekday, "identity_caveat": "This username is the identity presented on requests, not proof of a human or caller service."}

    def topology(self, start_ms: int, end_ms: int, evidence: str | None = None, filters: dict[str,str|None] | None = None) -> dict[str, Any]:
        with self.connect() as db:
            args: list[Any] = [start_ms, end_ms]
            extra = ""
            if evidence: extra = " AND e.evidence=?"; args.append(evidence)
            filters=filters or {}
            for key,column in (("environment","environment"),("group","service_group"),("module","service_module")):
                if filters.get(key):
                    extra += f" AND (e.source_service IN (SELECT name FROM services WHERE {column}=?) OR e.target_service IN (SELECT name FROM services WHERE {column}=?))";args.extend([filters[key],filters[key]])
            if filters.get("service"):
                extra += " AND (e.source_service=? OR e.target_service=?)";args.extend([filters["service"],filters["service"]])
            if filters.get("account"):
                extra += " AND EXISTS (SELECT 1 FROM events ae WHERE ae.timestamp_ms>=? AND ae.timestamp_ms<? AND ae.service_name=e.source_service AND ae.peer_service=e.target_service AND ae.account_username=?)";args.extend([start_ms,end_ms,filters["account"]])
            edges = [dict(r) for r in db.execute(f"SELECT e.source_service source,e.target_service target,e.evidence,e.evidence_detail,SUM(e.request_count) requests,SUM(e.failure_count)*1.0/SUM(e.request_count) failure_rate,SUM(e.duration_sum_us)/1000.0/SUM(e.request_count) avg_ms,MAX(e.bucket_ms) freshness_ms FROM topology_edges e WHERE e.bucket_ms>=? AND e.bucket_ms<?{extra} GROUP BY source,target,evidence,evidence_detail ORDER BY requests DESC LIMIT 2000", args)]
            names = sorted({e["source"] for e in edges} | {e["target"] for e in edges})
            nodes = []
            for name in names:
                row = db.execute("SELECT name,service_group,service_module,environment,last_seen_ms FROM services WHERE name=?", (name,)).fetchone()
                nodes.append(dict(row) if row else {"name": name, "service_group": "Unknown", "service_module": "Unknown", "environment": "", "last_seen_ms": None})
        return {"nodes": nodes, "edges": edges, "unknown_callers_preserved": True}

    def anomalies(self, start_ms: int, end_ms: int, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM anomalies WHERE window_end_ms>=? AND window_start_ms<?"
        args: list[Any] = [start_ms,end_ms]
        if status: sql += " AND status=?"; args.append(status)
        sql += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,last_detected_ms DESC LIMIT 500"
        with self.connect() as db: rows = [dict(r) for r in db.execute(sql,args)]
        for row in rows:
            for key in ("limitations_json","contributors_json","trace_ids_json"): row[key.removesuffix("_json")] = json.loads(row.pop(key))
        return rows

    def anomaly_detail(self, anomaly_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM anomalies WHERE id=?", (anomaly_id,)).fetchone()
            if not row: return None
            result = dict(row)
            series = self.dashboard_series(result["training_start_ms"] or result["window_start_ms"], result["window_end_ms"], {"service": result["entity_id"] if result["entity_type"] == "service" else None})
        for key in ("limitations_json","contributors_json","trace_ids_json"): result[key.removesuffix("_json")] = json.loads(result.pop(key))
        result["series"] = series
        return result

    def patch_anomaly(self, anomaly_id: int, status: str, suppressed_until_ms: int | None) -> bool:
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM anomalies FINAL WHERE id=? LIMIT 1", (anomaly_id,)).fetchone() is None:
                return False
            db.execute("UPDATE anomalies SET status=?,suppressed_until_ms=?,updated_at_ms=? WHERE id=?", (status,suppressed_until_ms,int(time.time()*1000),anomaly_id))
        return True
