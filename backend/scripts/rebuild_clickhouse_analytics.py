#!/usr/bin/env python3
"""Rebuild all ClickHouse derived analytics from the canonical traces table.

This intentionally preserves raw ``traces`` and ``ingest_batches``.  ELK is
never queried for metrics or topology; the worker's ClickHouse aggregation path
is the sole producer of the analytical read model.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.repositories.db_context import db_transaction, get_connection
from backend.worker import run_jobs


# principal_activity_5m is deliberately NOT listed: it keeps up to 35 days of user
# behavior that raw traces (1-day TTL) can no longer rebuild. Its consumption ledger is
# reset with the principal checkpoint, so the next bootstrap replays the kept rollup.
DERIVED_TABLES = (
    "principal_activity_consumed", "accounts", "anomalies", "anomaly_events", "anomaly_occurrences",
    "baseline_metrics", "behavior_contracts", "behavior_daily",
    "behavior_deviations", "behavior_graph_models", "behavior_observations",
    "behavior_profiles", "behavior_state", "behavior_windows",
    "candidate_behaviors", "dirty_buckets", "established_baselines", "events",
    "historical_registry", "incidents", "jobs", "latency_rollups",
    "llm_investigations", "metric_buckets", "metric_buckets_agg",
    "operator_overrides", "principal_baselines", "principal_callers",
    "principal_change_events", "principal_daily_stats", "principal_hourly_activity",
    "principal_operations", "principal_relationships", "principal_service_edges",
    "principal_sources", "principal_targets", "principals", "semantic_assessments",
    "security_policy", "service_edges", "service_instance_edges_5m", "services",
    "telemetry_quality_windows", "topology_api_current", "topology_api_edges_5m",
    "topology_edges", "topology_principal_current", "topology_principal_edges_5m",
    "topology_principal_ip_5m", "topology_principal_ip_current",
    "topology_service_current", "topology_service_edges_5m", "trace_edge_resolutions",
)


def reset_derived() -> None:
    with get_connection() as db:
        available = {str(row[0]) for row in db.execute("SHOW TABLES FROM tracescope").fetchall()}
    with db_transaction() as db:
        for table in DERIVED_TABLES:
            if table in available:
                db.execute(f"TRUNCATE TABLE tracescope.{table}")
        # Keep the ELK source cursor and schema migrations. Every analytical
        # cursor is rebuilt from the preserved canonical ClickHouse traces.
        db.execute(
            "DELETE FROM checkpoints WHERE source NOT IN "
            "('elasticsearch', 'worker_elasticsearch_sync')"
        )


if __name__ == "__main__":
    reset_derived()
    print("ClickHouse derived tables reset; raw traces preserved.", flush=True)
    result = run_jobs()
    print(result, flush=True)
