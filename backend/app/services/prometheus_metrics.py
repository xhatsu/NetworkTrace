"""Prometheus exposition metrics registry for TraceScope web & API services.

Provides zero-dependency, thread-safe collection of standard web application metrics
(HTTP request counts, latency histograms, in-flight requests, status codes), process metrics
(memory, CPU, uptime), ingest engine telemetry, and domain estate summaries.
"""
from __future__ import annotations

import json
import os
import re
import resource
import threading
import time
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import settings

# Standard Prometheus HTTP request latency histogram buckets (in seconds)
DEFAULT_BUCKETS: Tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    float("inf"),
)

_UUID_OR_HEX_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{16,64}|\d{4,}"
)


def prom_escape(value: Any) -> str:
    """Escape label values according to Prometheus text exposition spec."""
    s = str(value)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def normalize_handler(raw_path: str, route_path: Optional[str] = None, status_code: int = 200) -> str:
    """Derive bounded, cardinality-safe handler name for Prometheus labels."""
    if route_path:
        return route_path

    path = raw_path.split("?")[0].strip()
    if not path or path == "/":
        return "/"
    if path == "/metrics":
        return "/metrics"
    if path in ("/livez", "/readyz"):
        return path
    if path.startswith("/assets/"):
        return "/assets/*"

    if status_code == 404:
        # Bounded representation for 404 scans
        return "not_found"

    # Replace UUIDs, long hexes, and arbitrary numbers with {id}
    sanitized = _UUID_OR_HEX_RE.sub("{id}", path)
    return sanitized


class PrometheusMetricsRegistry:
    """Thread-safe in-memory Prometheus exposition registry."""

    def __init__(self, buckets: Tuple[float, ...] = DEFAULT_BUCKETS) -> None:
        self.buckets = buckets
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._in_progress = 0

        # (method, handler, status_code) -> count
        self._requests_total: Dict[Tuple[str, str, str], int] = defaultdict(int)

        # (method, handler) -> sum of duration in seconds
        self._duration_sum: Dict[Tuple[str, str], float] = defaultdict(float)

        # (method, handler) -> total count of observations
        self._duration_count: Dict[Tuple[str, str], int] = defaultdict(int)

        # (method, handler) -> {bucket_le: count}
        self._duration_buckets: Dict[Tuple[str, str], Dict[float, int]] = defaultdict(
            lambda: {b: 0 for b in self.buckets}
        )

    def inc_in_progress(self) -> None:
        with self._lock:
            self._in_progress += 1

    def dec_in_progress(self) -> None:
        with self._lock:
            if self._in_progress > 0:
                self._in_progress -= 1

    def record_request(
        self,
        method: str,
        handler: str,
        status_code: int,
        duration_sec: float,
    ) -> None:
        status_str = str(status_code)
        m = method.upper()

        with self._lock:
            self._requests_total[(m, handler, status_str)] += 1
            pair = (m, handler)
            self._duration_sum[pair] += duration_sec
            self._duration_count[pair] += 1

            bucket_map = self._duration_buckets[pair]
            for b in self.buckets:
                if duration_sec <= b:
                    bucket_map[b] += 1

    def get_process_metrics(self) -> Dict[str, float]:
        """Collect standard Linux / POSIX process metrics."""
        metrics: Dict[str, float] = {
            "process_start_time_seconds": self._start_time,
            "process_uptime_seconds": max(0.0, time.time() - self._start_time),
            "process_cpu_seconds_total": time.process_time(),
        }

        # Resident memory in bytes (from Linux /proc/self/statm or getrusage)
        rss_bytes = 0
        try:
            with open("/proc/self/statm", "r") as f:
                rss_pages = int(f.read().split()[1])
                rss_bytes = rss_pages * os.sysconf("SC_PAGE_SIZE")
        except Exception:
            try:
                # getrusage maxrss in KB on Linux
                rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            except Exception:
                rss_bytes = 0

        metrics["process_resident_memory_bytes"] = float(rss_bytes)
        return metrics

    def render(self, repo: Any = None, role: str = "all") -> str:
        """Render complete Prometheus 0.0.4 exposition text."""
        lines: List[str] = []

        # ---------------------------------------------------------------------
        # 1. Web Application HTTP Metrics
        # ---------------------------------------------------------------------
        lines.append("# HELP http_requests_total Total number of HTTP requests processed by web service.")
        lines.append("# TYPE http_requests_total counter")
        with self._lock:
            req_items = sorted(self._requests_total.items())
            cur_in_progress = self._in_progress
            dur_sums = dict(self._duration_sum)
            dur_counts = dict(self._duration_count)
            dur_buckets = {k: dict(v) for k, v in self._duration_buckets.items()}

        for (m, handler, status), count in req_items:
            lines.append(
                f'http_requests_total{{method="{prom_escape(m)}",handler="{prom_escape(handler)}",status="{prom_escape(status)}"}} {count}'
            )

        lines.append("# HELP http_requests_in_progress Current number of HTTP requests being processed.")
        lines.append("# TYPE http_requests_in_progress gauge")
        lines.append(f"http_requests_in_progress {cur_in_progress}")

        lines.append("# HELP http_request_duration_seconds HTTP request latency histogram in seconds.")
        lines.append("# TYPE http_request_duration_seconds histogram")
        for (m, handler), b_map in sorted(dur_buckets.items()):
            m_esc = prom_escape(m)
            h_esc = prom_escape(handler)
            for le in self.buckets:
                le_str = "+Inf" if le == float("inf") else str(le)
                c = b_map.get(le, 0)
                lines.append(
                    f'http_request_duration_seconds_bucket{{method="{m_esc}",handler="{h_esc}",le="{le_str}"}} {c}'
                )
            lines.append(
                f'http_request_duration_seconds_sum{{method="{m_esc}",handler="{h_esc}"}} {dur_sums.get((m, handler), 0.0):.6f}'
            )
            lines.append(
                f'http_request_duration_seconds_count{{method="{m_esc}",handler="{h_esc}"}} {dur_counts.get((m, handler), 0)}'
            )

        # ---------------------------------------------------------------------
        # 2. Process & Runtime Metrics
        # ---------------------------------------------------------------------
        p_metrics = self.get_process_metrics()
        lines.append("# HELP process_resident_memory_bytes Resident memory size in bytes.")
        lines.append("# TYPE process_resident_memory_bytes gauge")
        lines.append(f"process_resident_memory_bytes {p_metrics['process_resident_memory_bytes']:.0f}")

        lines.append("# HELP process_cpu_seconds_total Total user and system CPU time spent in seconds.")
        lines.append("# TYPE process_cpu_seconds_total counter")
        lines.append(f"process_cpu_seconds_total {p_metrics['process_cpu_seconds_total']:.4f}")

        lines.append("# HELP process_start_time_seconds Start time of the process since unix epoch in seconds.")
        lines.append("# TYPE process_start_time_seconds gauge")
        lines.append(f"process_start_time_seconds {p_metrics['process_start_time_seconds']:.2f}")

        lines.append("# HELP process_uptime_seconds Process uptime in seconds.")
        lines.append("# TYPE process_uptime_seconds gauge")
        lines.append(f"process_uptime_seconds {p_metrics['process_uptime_seconds']:.2f}")

        lines.append("# HELP tracescope_service_info TraceScope service build and role information.")
        lines.append("# TYPE tracescope_service_info gauge")
        lines.append(
            f'tracescope_service_info{{version="0.3.3",role="{prom_escape(role)}",backend="{prom_escape(settings.storage_backend)}"}} 1'
        )

        # ---------------------------------------------------------------------
        # 3. High-TPS Ingest Writer Metrics (if active in this process)
        # ---------------------------------------------------------------------
        try:
            from backend.app.services.ingest_writer import ingest_writer
            snap = ingest_writer.snapshot()
            lines.append("# HELP tracescope_ingest_writer_queue_depth Current pending items in ingest writer queue.")
            lines.append("# TYPE tracescope_ingest_writer_queue_depth gauge")
            lines.append(f"tracescope_ingest_writer_queue_depth {snap.get('queue_depth', 0)}")

            lines.append("# HELP tracescope_ingest_writer_alive Ingest writer background worker status.")
            lines.append("# TYPE tracescope_ingest_writer_alive gauge")
            lines.append(f"tracescope_ingest_writer_alive {1 if snap.get('writer_alive') else 0}")

            lines.append("# HELP tracescope_ingest_writer_committed_total Total trace records committed to database.")
            lines.append("# TYPE tracescope_ingest_writer_committed_total counter")
            lines.append(f"tracescope_ingest_writer_committed_total {snap.get('committed_records', 0)}")

            lines.append("# HELP tracescope_ingest_writer_batches_total Total batches successfully committed.")
            lines.append("# TYPE tracescope_ingest_writer_batches_total counter")
            lines.append(f"tracescope_ingest_writer_batches_total {snap.get('batches_committed', 0)}")

            lines.append("# HELP tracescope_ingest_writer_dropped_total Total rejected or dropped requests.")
            lines.append("# TYPE tracescope_ingest_writer_dropped_total counter")
            lines.append(f"tracescope_ingest_writer_dropped_total {snap.get('failed_batches', 0)}")
        except Exception:
            pass

        # ---------------------------------------------------------------------
        # 4. Domain & Worker Telemetry Metrics (updated ONLY on worker cadence)
        # ---------------------------------------------------------------------
        w_snap = get_worker_metrics_snapshot()
        total_spans = w_snap.get("total_spans", 0)
        nodes_reporting = w_snap.get("nodes_reporting", 1)
        c_2xx = w_snap.get("c_2xx", 0)
        c_err = w_snap.get("c_err", 0)
        nodes_rows = w_snap.get("nodes", [])
        rpm_rows_db = w_snap.get("users_rpm", [])
        open_anomalies = w_snap.get("open_anomalies", 0)
        worker_last_run = w_snap.get("worker_last_run_seconds", 0.0)
        worker_duration = w_snap.get("worker_cycle_duration_seconds", 0.0)

        lines.append("# HELP tracescope_worker_last_run_timestamp_seconds Timestamp of the most recent worker cycle.")
        lines.append("# TYPE tracescope_worker_last_run_timestamp_seconds gauge")
        lines.append(f"tracescope_worker_last_run_timestamp_seconds {worker_last_run:.2f}")

        lines.append("# HELP tracescope_worker_cycle_duration_seconds Duration of the most recent worker cycle in seconds.")
        lines.append("# TYPE tracescope_worker_cycle_duration_seconds gauge")
        lines.append(f"tracescope_worker_cycle_duration_seconds {worker_duration:.3f}")

        lines.append("# HELP tracescope_open_anomalies_total Total active open or investigating anomalies.")
        lines.append("# TYPE tracescope_open_anomalies_total gauge")
        lines.append(f"tracescope_open_anomalies_total {open_anomalies}")

        observed_tps = float(w_snap.get("observed_tps", 0.0) or 0.0)
        baseline_tps = float(w_snap.get("baseline_tps", 0.0) or 0.0)

        lines.append("# HELP tracescope_observed_tps Current observed system transaction throughput in transactions per second.")
        lines.append("# TYPE tracescope_observed_tps gauge")
        lines.append(f"tracescope_observed_tps {observed_tps:.4f}")

        lines.append("# HELP tracescope_baseline_tps Current historical baseline throughput in transactions per second for the active hour-of-day.")
        lines.append("# TYPE tracescope_baseline_tps gauge")
        lines.append(f"tracescope_baseline_tps {baseline_tps:.4f}")

        lines.append("# TYPE nt_violations_total counter")
        lines.append("nt_violations_total 0")
        lines.append("# TYPE nt_nodes_reporting gauge")
        lines.append(f"nt_nodes_reporting {nodes_reporting}")
        lines.append("# TYPE nt_overflow_total counter")
        lines.append('nt_overflow_total{reason="dropped"} 0')
        lines.append('nt_overflow_total{reason="db_dropped"} 0')
        lines.append('nt_overflow_total{reason="duplicate_span"} 0')
        lines.append("# TYPE nt_otel_server_spans_total counter")
        lines.append(f'nt_otel_server_spans_total{{receiver="otel-http"}} {total_spans}')
        lines.append("# TYPE nt_requests_total counter")
        lines.append(f'nt_requests_total{{source="otel",probe="agent",status_class="2xx"}} {c_2xx}')
        lines.append(f'nt_requests_total{{source="otel",probe="agent",status_class="5xx"}} {c_err}')
        lines.append("# TYPE nt_policy_violations_total counter")
        lines.append('nt_policy_violations_total{{source="otel"}} 0')
        lines.append("# TYPE nt_duration_samples_total counter")
        lines.append(f'nt_duration_samples_total{{source="otel",probe="agent"}} {total_spans}')

        lines.append("# TYPE nt_user_rpm gauge")
        lines.append("# TYPE nt_user_requests_5m gauge")
        for u_row in rpm_rows_db:
            u_label = prom_escape(u_row.get("user", ""))
            lines.append(f'nt_user_rpm{{user="{u_label}"}} {u_row.get("rpm", 0)}')
            lines.append(f'nt_user_requests_5m{{user="{u_label}"}} {u_row.get("n", 0)}')

        lines.append("# TYPE nt_node_events_total counter")
        lines.append("# TYPE nt_node_up gauge")
        for n_val in nodes_rows:
            n_label = prom_escape(n_val)
            lines.append(f'nt_node_events_total{{node="{n_label}"}} 1')
            lines.append(f'nt_node_up{{node="{n_label}"}} 1')

        return "\n".join(lines) + "\n"


SNAPSHOT_CACHE_FILE = Path("/tmp/tracescope_worker_metrics.json")
_cached_worker_snapshot: Optional[Dict[str, Any]] = None
_cached_worker_snapshot_time: float = 0.0
_worker_snapshot_lock = threading.Lock()


def compute_domain_metrics_snapshot(db_path=None) -> Dict[str, Any]:
    """Executed ONLY by backend.worker on its periodic derivation cycle."""
    from backend.app.repositories.db_context import get_connection

    total_spans = 0
    nodes_reporting = 1
    c_2xx = 0
    c_err = 0
    nodes_rows: List[str] = []
    rpm_rows: List[Dict[str, Any]] = []
    open_anomalies = 0

    try:
        with get_connection(db_path) as conn:
            t_row = conn.execute("SELECT count() FROM traces").fetchone()
            total_spans = int(t_row[0]) if (t_row and t_row[0] is not None) else 0

            n_rows = conn.execute(
                "SELECT DISTINCT service_instance AS node FROM traces WHERE service_instance IS NOT NULL LIMIT 50"
            ).fetchall()
            nodes_rows = [str(r[0]) for r in n_rows if r and r[0]] if n_rows else []
            nodes_reporting = max(1, len(nodes_rows))

            status_rows = conn.execute(
                "SELECT SUM(request_count - error_count) AS cnt_2xx, SUM(error_count) AS cnt_err "
                "FROM metric_buckets WHERE bucket_size = 60"
            ).fetchone()
            if status_rows:
                c_2xx = int(status_rows["cnt_2xx"] or 0)
                c_err = int(status_rows["cnt_err"] or 0)

            rpm_db = conn.execute(
                """
                SELECT principal_name AS user,
                       SUM(request_count) AS n,
                       ROUND(SUM(request_count) / 5.0, 2) AS rpm
                FROM metric_buckets
                WHERE bucket_size = 300
                  AND bucket_start >= (SELECT COALESCE(MAX(bucket_start), 0) - 300 FROM metric_buckets WHERE bucket_size = 300)
                  AND principal_name IS NOT NULL AND principal_name != '' AND principal_name != 'unknown'
                GROUP BY principal_name
                ORDER BY n DESC
                LIMIT 20
                """
            ).fetchall()
            rpm_rows = [
                {"user": str(r["user"]), "n": int(r["n"]), "rpm": float(r["rpm"])}
                for r in rpm_db
            ] if rpm_db else []

            try:
                ano_row = conn.execute(
                    "SELECT count() FROM anomalies FINAL WHERE status IN ('open', 'investigating')"
                ).fetchone()
                open_anomalies = int(ano_row[0]) if ano_row and ano_row[0] else 0
            except Exception:
                open_anomalies = 0

            observed_tps = 0.0
            try:
                tps_row = conn.execute(
                    """
                    SELECT ROUND(SUM(request_count) / 60.0, 4) AS tps
                    FROM metric_buckets
                    WHERE bucket_size = 60
                      AND bucket_start >= (SELECT COALESCE(MAX(bucket_start), 0) - 60 FROM metric_buckets WHERE bucket_size = 60)
                    """
                ).fetchone()
                if tps_row and tps_row["tps"] is not None:
                    observed_tps = float(tps_row["tps"])
            except Exception:
                observed_tps = 0.0

            baseline_tps = 0.0
            try:
                now_dt = datetime.fromtimestamp(time.time(), tz=timezone.utc)
                b_row = conn.execute(
                    """
                    SELECT round(SUM(rps_median), 4) AS sys_baseline
                    FROM baseline_metrics FINAL
                    WHERE dimension_type = 'service'
                      AND hour_of_day = ? AND day_of_week = ?
                    """,
                    (now_dt.hour, now_dt.weekday()),
                ).fetchone()
                if b_row and b_row["sys_baseline"] is not None and float(b_row["sys_baseline"]) > 0:
                    baseline_tps = float(b_row["sys_baseline"])
                else:
                    fb_rows = conn.execute(
                        """
                        SELECT round(SUM(rps_median), 4) AS sys_baseline
                        FROM baseline_metrics FINAL
                        WHERE dimension_type = 'service'
                        GROUP BY hour_of_day, day_of_week
                        HAVING sys_baseline > 0
                        ORDER BY sys_baseline ASC
                        """
                    ).fetchall()
                    if fb_rows:
                        mid = len(fb_rows) // 2
                        baseline_tps = float(fb_rows[mid][0])
            except Exception:
                baseline_tps = 0.0
    except Exception:
        pass

    return {
        "total_spans": total_spans,
        "nodes_reporting": nodes_reporting,
        "c_2xx": c_2xx,
        "c_err": c_err,
        "nodes": nodes_rows,
        "users_rpm": rpm_rows,
        "open_anomalies": open_anomalies,
        "observed_tps": observed_tps,
        "baseline_tps": baseline_tps,
        "updated_at_ms": int(time.time() * 1000),
    }


def update_worker_prometheus_metrics(db_path=None, duration_sec: float = 0.0) -> Dict[str, Any]:
    """Invoked exclusively by backend.worker to update domain metrics once per worker run."""
    global _cached_worker_snapshot, _cached_worker_snapshot_time
    from backend.app.repositories.db_context import db_transaction

    snapshot = compute_domain_metrics_snapshot(db_path=db_path)
    snapshot["worker_last_run_seconds"] = time.time()
    snapshot["worker_cycle_duration_seconds"] = duration_sec

    with _worker_snapshot_lock:
        _cached_worker_snapshot = snapshot
        _cached_worker_snapshot_time = time.time()

    try:
        SNAPSHOT_CACHE_FILE.write_text(json.dumps(snapshot), encoding="utf-8")
    except Exception:
        pass

    try:
        with db_transaction(db_path) as db:
            db.execute(
                "INSERT INTO checkpoints(source, cursor_json, updated_at_ms) VALUES(?,?,?)",
                ("worker_prometheus_metrics", json.dumps(snapshot, separators=(",", ":")), int(time.time() * 1000)),
            )
    except Exception:
        pass

    return snapshot


def get_worker_metrics_snapshot(db_path=None) -> Dict[str, Any]:
    """Read precomputed snapshot without executing heavy aggregation queries."""
    global _cached_worker_snapshot, _cached_worker_snapshot_time

    now = time.time()
    with _worker_snapshot_lock:
        if _cached_worker_snapshot is not None and (now - _cached_worker_snapshot_time < 15.0):
            return _cached_worker_snapshot

    # Check shared local file cache
    try:
        if SNAPSHOT_CACHE_FILE.is_file():
            data = json.loads(SNAPSHOT_CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                with _worker_snapshot_lock:
                    _cached_worker_snapshot = data
                    _cached_worker_snapshot_time = now
                return data
    except Exception:
        pass

    # Check ClickHouse checkpoint
    try:
        from backend.app.repositories.db_context import get_connection
        with get_connection(db_path) as db:
            row = db.execute(
                "SELECT cursor_json FROM checkpoints FINAL WHERE source='worker_prometheus_metrics' LIMIT 1"
            ).fetchone()
        if row and row[0]:
            data = json.loads(row[0])
            if isinstance(data, dict):
                with _worker_snapshot_lock:
                    _cached_worker_snapshot = data
                    _cached_worker_snapshot_time = now
                return data
    except Exception:
        pass

    # Do not run worker derivation inline on a scrape request. In particular,
    # the worker snapshot may read raw input tables; before the first worker
    # cycle the API reports an empty snapshot until the checkpoint is written.
    return {
        "total_spans": 0,
        "nodes_reporting": 1,
        "c_2xx": 0,
        "c_err": 0,
        "nodes": [],
        "users_rpm": [],
        "open_anomalies": 0,
        "observed_tps": 0.0,
        "baseline_tps": 0.0,
        "updated_at_ms": 0,
        "worker_last_run_seconds": 0.0,
        "worker_cycle_duration_seconds": 0.0,
    }


# Global singleton registry instance
prometheus_registry = PrometheusMetricsRegistry()


class PrometheusMiddleware:
    """Pure ASGI middleware tracking web request counts, durations, and in-flight gauges."""

    def __init__(self, app: Any, registry: PrometheusMetricsRegistry = prometheus_registry) -> None:
        self.app = app
        self.registry = registry

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        raw_path = scope.get("path", "/")
        start = time.perf_counter()
        status_code = 200
        self.registry.inc_in_progress()

        async def send_wrapper(message: Dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status_code = 500
            raise
        finally:
            duration = time.perf_counter() - start
            self.registry.dec_in_progress()
            route = scope.get("route")
            route_path = getattr(route, "path", None) if route else None
            handler = normalize_handler(raw_path, route_path, status_code)
            self.registry.record_request(
                method=method,
                handler=handler,
                status_code=status_code,
                duration_sec=duration,
            )
