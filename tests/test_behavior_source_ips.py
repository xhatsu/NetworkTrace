"""The learning source must attach observed IPs although the IP rollup spells APIs 'service/operation'."""
from __future__ import annotations

from backend.app.repositories.behavior_repository import BehaviorRepository
from backend.app.repositories.db_context import get_connection
from backend.app.services.behavior_sources import sql_day

# Fixed five-minute aligned bucket far from live data; test database is isolated.
BUCKET_S = 1_700_000_100 // 300 * 300
DAY_START_MS = BUCKET_S * 1000 // 86_400_000 * 86_400_000


def _seed():
    with get_connection() as db:
        db.client.insert(
            "metric_buckets",
            [[300, BUCKET_S, "traffic-ui", "alice_wsse", "order-service", "POST /api/v1/orders/process", 5, 0]],
            column_names=["bucket_size", "bucket_start", "caller_service", "principal_name",
                          "target_service", "operation", "request_count", "error_count"],
        )
        db.client.insert(
            "topology_principal_ip_5m",
            [[BUCKET_S, "alice_wsse", "10.1.2.3", "order-service", "order-service/POST /api/v1/orders/process",
              "traffic-ui", 5, "client"]],
            column_names=["bucket_start", "principal", "source_ip", "service", "api",
                          "caller_service", "request_count", "source_ip_role"],
        )


def test_ip_rollup_prefixed_api_joins_bare_metric_operation():
    _seed()
    rows = sql_day(BehaviorRepository(), "legacy_metrics", DAY_START_MS, DAY_START_MS + 86_400_000)
    mine = [r for r in rows if r["target"] == "order-service" and r["principal"] == "alice_wsse"]
    assert len(mine) == 1
    assert mine[0]["requests"] == 5
    assert mine[0]["operation"] == "POST /api/v1/orders/process"
    assert mine[0]["observed_ips"] == [{"address": "10.1.2.3", "role": "client"}]
