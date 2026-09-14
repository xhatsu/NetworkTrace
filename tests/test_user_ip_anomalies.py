from __future__ import annotations

import asyncio
import time
import httpx
import pytest

from backend.main import app
from backend.config import settings
from backend.app.models.trace import NormalizedTrace
from backend.app.models.anomaly import AnomalyEvent, AnomalyReason
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.repositories.anomaly_repository import AnomalyRepository
from backend.app.repositories.db_context import get_connection
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.anomaly_detection import detect_anomalies
from backend.app.services.principal_relationships import process_principal_intelligence
from backend.repository import StorageRepository


@pytest.fixture(scope="module", autouse=True)
def user_ip_env():
    StorageRepository().migrate()

    now = int(time.time() * 1000)
    base_ts = now - 10 * 86_400_000  # 10 days ago

    traces = []
    # 50 historical traces for alice on 10.0.0.1
    for i in range(50):
        ts = base_ts + i * 3600_000
        traces.append(
            NormalizedTrace(
                event_uid=f"hist-alice-{i}",
                timestamp=f"{ts}",
                timestamp_ms=ts,
                trace_id=f"t-alice-{i}",
                span_id=f"s-alice-{i}",
                parent_span_id=None,
                service_name="payment-service",
                service_instance="inst-1",
                service_environment="prod",
                caller_service="order-service",
                caller_instance="inst-0",
                caller_ip="10.0.0.1",
                target_service="payment-service",
                target_instance="inst-1",
                target_ip="10.0.0.50",
                target_port=8080,
                principal_name="alice",
                operation="charge",
                http_method="POST",
                http_route="/charge",
                http_status=200,
                status_class="2xx",
                duration_ms=25.0,
                duration_us=25000,
                outcome="success",
                protocol="http",
                span_kind="SERVER",
                attributes_json="{}",
                created_at=ts,
            )
        )
    # 50 historical traces for bob on 10.0.0.2
    for i in range(50):
        ts = base_ts + i * 3600_000
        traces.append(
            NormalizedTrace(
                event_uid=f"hist-bob-{i}",
                timestamp=f"{ts}",
                timestamp_ms=ts,
                trace_id=f"t-bob-{i}",
                span_id=f"s-bob-{i}",
                parent_span_id=None,
                service_name="payment-service",
                service_instance="inst-1",
                service_environment="prod",
                caller_service="order-service",
                caller_instance="inst-0",
                caller_ip="10.0.0.2",
                target_service="payment-service",
                target_instance="inst-1",
                target_ip="10.0.0.50",
                target_port=8080,
                principal_name="bob",
                operation="charge",
                http_method="POST",
                http_route="/charge",
                http_status=200,
                status_class="2xx",
                duration_ms=25.0,
                duration_us=25000,
                outcome="success",
                protocol="http",
                span_kind="SERVER",
                attributes_json="{}",
                created_at=ts,
            )
        )

    trace_repo = TraceRepository()
    trace_repo.insert_traces(traces)
    aggregate_traces()
    # Bootstrap baseline
    process_principal_intelligence()

    return {"trace_repo": trace_repo, "now": now}


@pytest.fixture
def client():
    class Client:
        @staticmethod
        def request(method, url, **kwargs):
            async def send():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as session:
                    return await session.request(method, url, **kwargs)
            return asyncio.run(send())

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

    return Client()


def test_known_user_known_ip_not_flagged():
    """Case 1: Same user from known IP -> not flagged as an anomaly."""
    trace_repo = TraceRepository()
    now = int(time.time() * 1000)

    t = NormalizedTrace(
        event_uid="test-case-1",
        timestamp=f"{now}",
        timestamp_ms=now,
        trace_id="t-c1",
        span_id="s-c1",
        parent_span_id=None,
        service_name="payment-service",
        service_instance="inst-1",
        service_environment="prod",
        caller_service="order-service",
        caller_instance="inst-0",
        caller_ip="10.0.0.1",
        target_service="payment-service",
        target_instance="inst-1",
        target_ip="10.0.0.50",
        target_port=8080,
        principal_name="alice",
        operation="charge",
        http_method="POST",
        http_route="/charge",
        http_status=200,
        status_class="2xx",
        duration_ms=25.0,
        duration_us=25000,
        outcome="success",
        protocol="http",
        span_kind="SERVER",
        attributes_json="{}",
        created_at=now,
    )
    trace_repo.insert_traces([t])
    aggregate_traces()
    now_sec = int(now / 1000)
    anomalies = detect_anomalies(window_start_sec=now_sec - 300, window_end_sec=now_sec + 300)
    user_ip_anomalies = [a for a in anomalies if a.anomaly_type in {"user_new_source_ip", "ip_new_user"} and a.principal_name == "alice" and a.source_ip == "10.0.0.1"]
    assert len(user_ip_anomalies) == 0


def test_known_user_new_ip_flagged():
    """Case 2: Same user from new/suspicious IP -> flagged (user_new_source_ip / NEW_SOURCE_IP)."""
    trace_repo = TraceRepository()
    now = int(time.time() * 1000)

    t = NormalizedTrace(
        event_uid="test-case-2",
        timestamp=f"{now}",
        timestamp_ms=now,
        trace_id="t-c2",
        span_id="s-c2",
        parent_span_id=None,
        service_name="payment-service",
        service_instance="inst-1",
        service_environment="prod",
        caller_service="order-service",
        caller_instance="inst-0",
        caller_ip="185.220.101.5",
        target_service="payment-service",
        target_instance="inst-1",
        target_ip="10.0.0.50",
        target_port=8080,
        principal_name="alice",
        operation="charge",
        http_method="POST",
        http_route="/charge",
        http_status=200,
        status_class="2xx",
        duration_ms=25.0,
        duration_us=25000,
        outcome="success",
        protocol="http",
        span_kind="SERVER",
        attributes_json="{}",
        created_at=now,
    )
    trace_repo.insert_traces([t])
    aggregate_traces()
    now_sec = int(now / 1000)
    anomalies = detect_anomalies(window_start_sec=now_sec - 300, window_end_sec=now_sec + 300)
    flagged = [a for a in anomalies if a.anomaly_type == "user_new_source_ip" and a.principal_name == "alice" and a.source_ip == "185.220.101.5"]
    assert len(flagged) >= 1
    assert flagged[0].severity in {"medium", "high"}
    assert flagged[0].source_ip == "185.220.101.5"

    process_principal_intelligence()
    with get_connection() as db:
        change = db.execute(
            "SELECT * FROM principal_change_events WHERE principal_name='alice' AND source_ip='185.220.101.5' AND change_type='NEW_SOURCE_IP'"
        ).fetchone()
        assert change is not None
        assert change["change_type"] == "NEW_SOURCE_IP"


def test_known_ip_new_user_flagged():
    """Case 3: Known IP used by new user -> flagged (ip_new_user / NEW_USER_ON_IP)."""
    trace_repo = TraceRepository()
    now = int(time.time() * 1000)

    # Bob's known IP is 10.0.0.2. Now user 'mallory' appears from 10.0.0.2
    t = NormalizedTrace(
        event_uid="test-case-3",
        timestamp=f"{now}",
        timestamp_ms=now,
        trace_id="t-c3",
        span_id="s-c3",
        parent_span_id=None,
        service_name="payment-service",
        service_instance="inst-1",
        service_environment="prod",
        caller_service="order-service",
        caller_instance="inst-0",
        caller_ip="10.0.0.2",
        target_service="payment-service",
        target_instance="inst-1",
        target_ip="10.0.0.50",
        target_port=8080,
        principal_name="mallory",
        operation="charge",
        http_method="POST",
        http_route="/charge",
        http_status=200,
        status_class="2xx",
        duration_ms=25.0,
        duration_us=25000,
        outcome="success",
        protocol="http",
        span_kind="SERVER",
        attributes_json="{}",
        created_at=now,
    )
    trace_repo.insert_traces([t])
    aggregate_traces()
    now_sec = int(now / 1000)
    anomalies = detect_anomalies(window_start_sec=now_sec - 300, window_end_sec=now_sec + 300)
    flagged = [a for a in anomalies if a.anomaly_type == "ip_new_user" and a.source_ip == "10.0.0.2" and a.principal_name == "mallory"]
    assert len(flagged) >= 1
    assert flagged[0].source_ip == "10.0.0.2"
    assert flagged[0].principal_name == "mallory"

    process_principal_intelligence()
    with get_connection() as db:
        change = db.execute(
            "SELECT * FROM principal_change_events WHERE principal_name='mallory' AND source_ip='10.0.0.2'"
        ).fetchone()
        assert change is not None


def test_missing_or_anonymous_safely_ignored():
    """Case 4: Missing or anonymous user/IP must not create phantom combinations."""
    trace_repo = TraceRepository()
    now = int(time.time() * 1000)

    # Unknown user from known IP 10.0.0.1
    t1 = NormalizedTrace(
        event_uid="test-case-4a",
        timestamp=f"{now}",
        timestamp_ms=now,
        trace_id="t-c4a",
        span_id="s-c4a",
        parent_span_id=None,
        service_name="payment-service",
        service_instance="inst-1",
        service_environment="prod",
        caller_service="order-service",
        caller_instance="inst-0",
        caller_ip="10.0.0.1",
        target_service="payment-service",
        target_instance="inst-1",
        target_ip="10.0.0.50",
        target_port=8080,
        principal_name="unknown",
        operation="charge",
        http_method="POST",
        http_route="/charge",
        http_status=200,
        status_class="2xx",
        duration_ms=25.0,
        duration_us=25000,
        outcome="success",
        protocol="http",
        span_kind="SERVER",
        attributes_json="{}",
        created_at=now,
    )
    # Known user alice with missing caller_ip
    t2 = NormalizedTrace(
        event_uid="test-case-4b",
        timestamp=f"{now}",
        timestamp_ms=now,
        trace_id="t-c4b",
        span_id="s-c4b",
        parent_span_id=None,
        service_name="payment-service",
        service_instance="inst-1",
        service_environment="prod",
        caller_service="order-service",
        caller_instance="inst-0",
        caller_ip="",
        target_service="payment-service",
        target_instance="inst-1",
        target_ip="10.0.0.50",
        target_port=8080,
        principal_name="alice",
        operation="charge",
        http_method="POST",
        http_route="/charge",
        http_status=200,
        status_class="2xx",
        duration_ms=25.0,
        duration_us=25000,
        outcome="success",
        protocol="http",
        span_kind="SERVER",
        attributes_json="{}",
        created_at=now,
    )
    trace_repo.insert_traces([t1, t2])
    aggregate_traces()
    now_sec = int(now / 1000)
    anomalies = detect_anomalies(window_start_sec=now_sec - 300, window_end_sec=now_sec + 300)
    phantom = [
        a for a in anomalies
        if (a.principal_name in {"unknown", "", None} and a.anomaly_type in {"user_new_source_ip", "ip_new_user"})
        or (a.source_ip in {"", "unknown", None} and a.anomaly_type in {"user_new_source_ip", "ip_new_user"})
    ]
    assert len(phantom) == 0


def test_existing_user_only_behavior_preserved():
    """Case 5: Existing user-only behavioral detection remains intact."""
    trace_repo = TraceRepository()
    now = int(time.time() * 1000)

    # Alice accesses a new operation "refund" which she has never called before
    t = NormalizedTrace(
        event_uid="test-case-5",
        timestamp=f"{now}",
        timestamp_ms=now,
        trace_id="t-c5",
        span_id="s-c5",
        parent_span_id=None,
        service_name="payment-service",
        service_instance="inst-1",
        service_environment="prod",
        caller_service="order-service",
        caller_instance="inst-0",
        caller_ip="10.0.0.1",
        target_service="payment-service",
        target_instance="inst-1",
        target_ip="10.0.0.50",
        target_port=8080,
        principal_name="alice",
        operation="refund",
        http_method="POST",
        http_route="/refund",
        http_status=200,
        status_class="2xx",
        duration_ms=25.0,
        duration_us=25000,
        outcome="success",
        protocol="http",
        span_kind="SERVER",
        attributes_json="{}",
        created_at=now,
    )
    trace_repo.insert_traces([t])
    process_principal_intelligence()
    with get_connection() as db:
        change = db.execute(
            "SELECT * FROM principal_change_events WHERE principal_name='alice' AND change_type='NEW_OPERATION' ORDER BY detected_at DESC, id DESC"
        ).fetchone()
        assert change is not None
        assert change["new_value"] == "refund" or "refund" in str(change["new_value"])


def test_api_filters_and_serialization(client):
    """Case 6: API endpoints properly serialize source_ip and support source_ip query filter."""
    anomaly_repo = AnomalyRepository()

    now = int(time.time() * 1000)
    anomaly_repo.save_anomalies([
        AnomalyEvent(
            anomaly_type="user_new_source_ip",
            target_service="payment-service",
            caller_service="order-service",
            principal_name="alice",
            source_ip="198.51.100.23",
            score=70,
            severity="high",
            confidence=0.9,
            detected_at=now,
            first_seen=now - 60_000,
            last_seen=now,
            current_value=1.0,
            baseline_value=0.0,
            reasons=[
                AnomalyReason(
                    type="user_new_source_ip",
                    contribution=70,
                    baseline=0.0,
                    current=1.0,
                    text="Known user alice accessed from new IP 198.51.100.23",
                )
            ],
        )
    ])

    # Query anomalies API with source_ip filter
    res = client.get("/api/v1/anomalies?source_ip=198.51.100.23")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 1
    item = [x for x in data["items"] if x.get("source_ip") == "198.51.100.23"][0]
    assert item["principal_name"] == "alice"
    assert item["source_ip"] == "198.51.100.23"

    # Query traces API with source_ip filter
    res_traces = client.get("/api/v1/traces?source_ip=185.220.101.5")
    assert res_traces.status_code == 200
    traces_data = res_traces.json()
    assert traces_data["count"] >= 1
    assert traces_data["items"][0]["caller_ip"] == "185.220.101.5"
