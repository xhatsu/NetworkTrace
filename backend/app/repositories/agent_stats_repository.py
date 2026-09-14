"""Agent statistics repository — persists oldkernel agent health samples.

Implements the AGENT-STATS-PROTOCOL v1 storage contract:
  - Idempotency key: (node, instance_id, sequence)
  - agent_stats_latest: one row per (node, instance_id), upserted on each new sequence
  - agent_stats_history: append-only; UNIQUE constraint rejects exact duplicates
"""
from __future__ import annotations

import json
import time
from typing import Any

from backend.app.repositories.db_context import get_connection, db_transaction


# Bound fleet-history retention so high-frequency health samples cannot crowd out analytical telemetry.
_HISTORY_KEEP_PER_NODE = 2880  # ~24 h at 30-second intervals


def _flatten(body: dict[str, Any]) -> dict[str, Any]:
    """Return all flat columns derived from the protocol body."""
    cap = body.get("capture") or {}
    ship = body.get("shipping") or {}
    res = body.get("resources") or {}
    lim = body.get("limits") or {}
    drop_causes = ship.get("drop_causes") or {}
    return {
        "cap_packets_total":            cap.get("packets_total"),
        "cap_packets_delta":            cap.get("packets_delta"),
        "cap_packet_bytes_total":       cap.get("packet_bytes_total"),
        "cap_packet_bytes_delta":       cap.get("packet_bytes_delta"),
        "cap_kernel_drops_total":       cap.get("kernel_drops_total"),
        "cap_kernel_drops_delta":       cap.get("kernel_drops_delta"),
        "cap_kernel_drop_percent":      cap.get("kernel_drop_percent"),
        "cap_invalid_frames_total":     cap.get("invalid_frames_total"),
        "cap_events_emitted_total":     cap.get("events_emitted_total"),
        "cap_events_emitted_delta":     cap.get("events_emitted_delta"),
        "cap_flows_active":             cap.get("flows_active"),
        "cap_pending_requests":         cap.get("pending_requests"),
        "cap_wsse_body_flows_active":   cap.get("wsse_body_flows_active"),
        "ship_events_in_total":             ship.get("events_in_total"),
        "ship_events_in_delta":             ship.get("events_in_delta"),
        "ship_events_pushed_total":         ship.get("events_pushed_total"),
        "ship_events_pushed_delta":         ship.get("events_pushed_delta"),
        "ship_events_dropped_total":        ship.get("events_dropped_total"),
        "ship_events_dropped_delta":        ship.get("events_dropped_delta"),
        "ship_drop_causes_json":            json.dumps(drop_causes),
        "ship_batches_pushed_total":        ship.get("batches_pushed_total"),
        "ship_batches_pushed_delta":        ship.get("batches_pushed_delta"),
        "ship_batches_failed_total":        ship.get("batches_failed_total"),
        "ship_batches_failed_delta":        ship.get("batches_failed_delta"),
        "ship_bytes_pushed_total":          ship.get("bytes_pushed_total"),
        "ship_bytes_pushed_delta":          ship.get("bytes_pushed_delta"),
        "ship_push_events_per_second":      ship.get("push_events_per_second"),
        "ship_push_kbps":                   ship.get("push_kbps"),
        "ship_drop_events_per_second":      ship.get("drop_events_per_second"),
        "ship_drop_percent":                ship.get("drop_percent"),
        "ship_queue_depth_events":          ship.get("queue_depth_events"),
        "ship_queue_capacity_events":       ship.get("queue_capacity_events"),
        "ship_queue_high_water_events":     ship.get("queue_high_water_events"),
        "ship_last_push_http_status":       ship.get("last_push_http_status"),
        "ship_last_success_at":             ship.get("last_success_at"),
        "ship_consecutive_failures":        ship.get("consecutive_failures"),
        "ship_stats_samples_dropped_total": ship.get("stats_samples_dropped_total"),
        "res_cpu_user_seconds":      res.get("cpu_user_seconds"),
        "res_cpu_system_seconds":    res.get("cpu_system_seconds"),
        "res_cpu_percent_one_core":  res.get("cpu_percent_one_core"),
        "res_rss_bytes":             res.get("rss_bytes"),
        "res_virtual_bytes":         res.get("virtual_bytes"),
        "res_open_fds":              res.get("open_fds"),
        "res_threads":               res.get("threads"),
        "lim_cpu_core":              lim.get("cpu_core"),
        "lim_address_space_bytes":   lim.get("address_space_bytes"),
        "lim_ship_rate_kbps":        lim.get("ship_rate_kbps"),
        "lim_http_body_max_bytes":   lim.get("http_body_max_bytes"),
        "lim_ship_threads_max":      lim.get("ship_threads_max"),
        "lim_wsse_body_bytes":       lim.get("wsse_body_bytes"),
    }


import collections
import threading

_MAX_AGENT_CACHE_ENTRIES = 50_000


class AgentStatsRepository:
    """Persist and query agent health samples directly with ClickHouse."""

    _lock = threading.Lock()
    _seen_cache: collections.OrderedDict[tuple[str, str, int], bool] = collections.OrderedDict()

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path

    def is_duplicate(self, node: str, instance_id: str, sequence: int) -> bool:
        """Return True if this exact (node, instance_id, sequence) was already stored."""
        key = (node, instance_id, sequence)
        # The local cache avoids repeated FINAL reads; ClickHouse remains the durable authority.
        with self._lock:
            if key in self._seen_cache:
                self._seen_cache.move_to_end(key)
                return True

        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM agent_stats_history FINAL WHERE node=? AND instance_id=? AND sequence=?",
                (node, instance_id, sequence),
            ).fetchone()
            if row is not None:
                with self._lock:
                    self._seen_cache[key] = True
                    if len(self._seen_cache) > _MAX_AGENT_CACHE_ENTRIES:
                        self._seen_cache.popitem(last=False)
                return True
            return False
        finally:
            conn.close()

    def upsert(self, body: dict[str, Any]) -> bool:
        """Store a sample atomically and return whether it was newly accepted."""
        node = body["node"]
        instance_id = body["instance_id"]
        sequence = body["sequence"]
        observed_at = body["observed_at"]
        window_seconds = body["window_seconds"]
        mode = body.get("mode")
        status = body["status"]
        reasons_json = json.dumps(body.get("reasons") or [])
        raw_json = json.dumps(body)
        ingested_at = int(time.time() * 1000)

        if self.is_duplicate(node, instance_id, sequence):
            return False

        flat = _flatten(body)

        with db_transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO agent_stats_history
                    (node, instance_id, sequence, observed_at, window_seconds,
                     mode, status, reasons_json, raw_json, ingested_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (node, instance_id, sequence, observed_at, window_seconds,
                 mode, status, reasons_json, raw_json, ingested_at),
            )

            # ReplacingMergeTree can retain versions briefly, so only newer sequences advance the live view.
            existing = conn.execute(
                "SELECT sequence FROM agent_stats_latest FINAL WHERE node=? AND instance_id=?",
                (node, instance_id),
            ).fetchone()

            if existing is None or existing[0] < sequence:
                columns = [
                    "node", "instance_id", "sequence", "observed_at", "window_seconds",
                    "mode", "status", "reasons_json", "raw_json", "ingested_at",
                ] + list(flat.keys())
                values = [
                    node, instance_id, sequence, observed_at, window_seconds,
                    mode, status, reasons_json, raw_json, ingested_at,
                ] + list(flat.values())
                placeholders = ",".join(["?"] * len(columns))
                col_list = ",".join(columns)
                conn.execute(
                    f"INSERT INTO agent_stats_latest ({col_list}) VALUES ({placeholders})",
                    values,
                )

        key = (node, instance_id, sequence)
        with self._lock:
            self._seen_cache[key] = True
            if len(self._seen_cache) > _MAX_AGENT_CACHE_ENTRIES:
                self._seen_cache.popitem(last=False)

        return True

    def get_latest(self, node: str | None = None, instance_id: str | None = None) -> list[dict[str, Any]]:
        """Return the latest sample for each node (or a specific node/instance)."""
        conn = get_connection(self.db_path)
        try:
            if node and instance_id:
                rows = conn.execute(
                    "SELECT * FROM agent_stats_latest FINAL WHERE node=? AND instance_id=? ORDER BY observed_at DESC",
                    (node, instance_id),
                ).fetchall()
            elif node:
                rows = conn.execute(
                    "SELECT * FROM agent_stats_latest FINAL WHERE node=? ORDER BY observed_at DESC",
                    (node,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_stats_latest FINAL ORDER BY observed_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_history(self, node: str, limit: int = 120, instance_id: str | None = None) -> list[dict[str, Any]]:
        """Return recent history rows (newest first) for the given node (optionally filtered by instance_id)."""
        conn = get_connection(self.db_path)
        try:
            if instance_id:
                rows = conn.execute(
                    """
                    SELECT node, instance_id, sequence, observed_at, window_seconds,
                           mode, status, reasons_json, raw_json, ingested_at
                    FROM agent_stats_history FINAL
                    WHERE node=? AND instance_id=?
                    ORDER BY observed_at DESC
                    LIMIT ?
                    """,
                    (node, instance_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT node, instance_id, sequence, observed_at, window_seconds,
                           mode, status, reasons_json, raw_json, ingested_at
                    FROM agent_stats_history FINAL
                    WHERE node=?
                    ORDER BY observed_at DESC
                    LIMIT ?
                    """,
                    (node, limit),
                ).fetchall()
            results: list[dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                try:
                    raw = json.loads(item.get("raw_json") or "{}")
                    flat = _flatten(raw)
                    item.update(flat)
                    item["limits"] = raw.get("limits") or {}
                except Exception:
                    pass
                results.append(item)
            return results
        finally:
            conn.close()

    def delete_instance(self, node: str, instance_id: str | None = None) -> dict[str, Any]:
        """Delete an agent instance (or all instances for the node if instance_id is None)."""
        conn = get_connection(self.db_path)
        try:
            if instance_id:
                row_lat = conn.execute(
                    "SELECT count() FROM agent_stats_latest WHERE node=? AND instance_id=?",
                    (node, instance_id),
                ).fetchone()
                row_his = conn.execute(
                    "SELECT count() FROM agent_stats_history WHERE node=? AND instance_id=?",
                    (node, instance_id),
                ).fetchone()
                deleted_latest = int(row_lat[0]) if row_lat else 0
                deleted_history = int(row_his[0]) if row_his else 0
                if deleted_latest > 0:
                    conn.execute("DELETE FROM agent_stats_latest WHERE node=? AND instance_id=?", (node, instance_id))
                if deleted_history > 0:
                    conn.execute("DELETE FROM agent_stats_history WHERE node=? AND instance_id=?", (node, instance_id))
            else:
                row_lat = conn.execute(
                    "SELECT count() FROM agent_stats_latest WHERE node=?",
                    (node,),
                ).fetchone()
                row_his = conn.execute(
                    "SELECT count() FROM agent_stats_history WHERE node=?",
                    (node,),
                ).fetchone()
                deleted_latest = int(row_lat[0]) if row_lat else 0
                deleted_history = int(row_his[0]) if row_his else 0
                if deleted_latest > 0:
                    conn.execute("DELETE FROM agent_stats_latest WHERE node=?", (node,))
                if deleted_history > 0:
                    conn.execute("DELETE FROM agent_stats_history WHERE node=?", (node,))
            with self._lock:
                to_del = [k for k in self._seen_cache if k[0] == node and (instance_id is None or k[1] == instance_id)]
                for k in to_del:
                    self._seen_cache.pop(k, None)

            return {
                "deleted": (deleted_latest > 0 or deleted_history > 0),
                "deleted_latest": deleted_latest,
                "deleted_history": deleted_history,
                "node": node,
                "instance_id": instance_id,
            }
        finally:
            conn.close()

    def delete_node(self, node: str) -> dict[str, Any]:
        """Delete an agent node and its entire historical telemetry records."""
        return self.delete_instance(node, None)
