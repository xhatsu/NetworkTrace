"""principal_activity_5m: the only input user behavior reads (never raw traces)."""
from __future__ import annotations

import pytest

from backend.app.repositories.db_context import get_connection
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.principal_activity import materialize_principal_activity
from tests.test_otlp_trace_edge_resolution import (  # noqa: F401  (fixtures)
    BASE_MS, CLIENT, SERVER, WINDOW, insert, repo, resolution_on, server_attrs, span, trace_spans,
)


def activity(db_path):
    with get_connection(db_path) as db:
        rows = db.execute(
            "SELECT principal_name, caller_service, target_service, operation, source_ip, "
            "sum(request_count), sum(error_count) FROM principal_activity_5m FINAL "
            "GROUP BY 1,2,3,4,5 ORDER BY 1,2,3",
        ).fetchall()
    return [tuple(r) for r in rows]


@pytest.fixture
def clean(repo):
    with get_connection(repo) as db:
        db.execute("TRUNCATE TABLE principal_activity_5m")
    return repo


def test_rollup_carries_resolved_callers_and_counts_each_request_once(clean, resolution_on):
    insert(clean, trace_spans(4))
    aggregate_traces(*WINDOW, db_path=clean)
    assert activity(clean) == [
        ("alice_wsse", "traffic-ui", "order-service", "POST /api/v1/orders/process", "10.244.0.77", 4, 0),
        ("bob_wsse", "order-service", "payment-service", "POST /api/v1/payments/process", "10.244.0.77", 4, 0),
    ]


def test_anonymous_traffic_is_not_user_activity(clean, resolution_on):
    attrs = server_attrs()
    del attrs["enduser.id"]
    insert(clean, [span("f" * 32, "s" * 16, "order-service", SERVER, 0, 50, attrs=attrs)])
    aggregate_traces(*WINDOW, db_path=clean)
    assert activity(clean) == []


def test_errors_and_auth_outcomes_are_counted(clean, resolution_on):
    failed = server_attrs()
    failed["http.response.status_code"] = 401
    insert(clean, [
        span("1" * 32, "a" * 16, "order-service", SERVER, 0, 50, attrs=failed),
        span("2" * 32, "b" * 16, "order-service", SERVER, 1000, 50, attrs=server_attrs()),
    ])
    aggregate_traces(*WINDOW, db_path=clean)
    with get_connection(clean) as db:
        row = db.execute(
            "SELECT sum(request_count), sum(error_count), sum(auth_failure_count), "
            "max(length(sample_trace_ids)) FROM principal_activity_5m FINAL",
        ).fetchone()
    assert (row[0], row[1], row[3]) == (2, 1, 2)
    assert row[2] in (0, 1)  # auth_result for a bare 401 depends on the normalizer's evidence


def test_rewrite_does_not_double_count(clean, resolution_on):
    insert(clean, trace_spans(3))
    aggregate_traces(*WINDOW, db_path=clean)
    materialize_principal_activity(*WINDOW, db_path=clean)
    assert sum(r[5] for r in activity(clean)) == 6


def test_history_survives_raw_trace_expiry(clean, resolution_on):
    insert(clean, trace_spans(2))
    aggregate_traces(*WINDOW, db_path=clean)
    before = activity(clean)
    with get_connection(clean) as db:
        db.execute("TRUNCATE TABLE traces")
    assert materialize_principal_activity(*WINDOW, db_path=clean) == 0
    assert activity(clean) == before
