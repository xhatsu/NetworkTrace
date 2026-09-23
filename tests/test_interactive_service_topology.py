from __future__ import annotations

import asyncio
import time
from urllib.parse import quote

import httpx

from backend.main import app
from backend.repository import StorageRepository
from backend.app.repositories.interactive_topology_repository import (
    InteractiveTopologyRepository,
    bandwidth_fields,
    canonical_api,
    canonical_principal,
    decode_cursor,
    encode_cursor,
)
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.repositories.principal_repository import PrincipalRepository
from backend.app.repositories.user_repository import UserRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.normalization import classify_source_ip_role, normalize_otel_record


def _doc(index: int, service: str, peer: str, operation: str, principal: str | None, ip: str, status: int = 200, duration: float = 25.0) -> dict:
    source = {
        "@timestamp": "2026-09-18T10:00:10.000Z",
        "trace": {"id": f"topology-trace-{index:024d}"},
        "transaction": {"id": f"topology-span-{index:016d}", "name": operation, "duration": {"us": int(duration * 1000)}},
        "service": {"name": service, "environment": "production"},
        "peer.service": peer,
        "span.kind": "server",
        "client.ip": ip,
        "http.response.status_code": status,
        "http.request.method": "POST",
        "labels.http_request_content_length": 120,
        "labels.http_response_content_length": 480,
    }
    if principal is not None:
        source["enduser.id"] = principal
    return {"_source": source}


def test_topology_normalization_and_cursor_contracts():
    assert canonical_principal("") == "-anonymous-"
    assert canonical_principal("unknown") == "-anonymous-"
    assert canonical_api("POST /payment/1234567890abcdef", "payment") == "POST /payment/{id}"
    cursor = encode_cursor(["10.0.0.1", "payment", "payment/charge", "orders"])
    assert decode_cursor(cursor) == ["10.0.0.1", "payment", "payment/charge", "orders"]
    assert classify_source_ip_role("10.240.147.249")[0] == "load_balancer"
    assert bandwidth_fields(120, 480, 60) == {
        "request_bytes": 120,
        "response_bytes": 480,
        "total_bytes": 600,
        "request_bytes_per_second": 2.0,
        "response_bytes_per_second": 8.0,
        "bandwidth_bytes_per_second": 10.0,
        "bandwidth_bits_per_second": 80.0,
    }
    assert bandwidth_fields(-1, "invalid", 0)["bandwidth_bits_per_second"] == 0.0


def test_principal_metrics_do_not_fall_back_to_raw_traces(tmp_path):
    db_path = tmp_path / "principal-rollup-only.db"
    StorageRepository(db_path).migrate()
    trace = normalize_otel_record(_doc(901, "billing", "gateway", "POST /pay", "sale", "10.10.10.5"))
    assert trace is not None
    TraceRepository(str(db_path)).insert_traces([trace])
    start_sec = trace.timestamp_ms // 1000 - 60
    end_sec = start_sec + 120
    repo = PrincipalRepository(str(db_path))
    assert repo.list_principals(start_sec, end_sec) == []
    assert repo.get_principal_profile("sale", start_sec, end_sec) is None


def test_materialized_topology_has_metrics_evidence_anonymous_and_ip_status(tmp_path):
    db_path = tmp_path / "interactive-topology.db"
    StorageRepository(db_path).migrate()
    traces = [
        normalize_otel_record(_doc(1, "payment", "orders", "POST /payment/1234567890abcdef", "partner-a", "10.10.10.5", duration=21)),
        normalize_otel_record(_doc(2, "payment", "orders", "POST /payment/1234567890abcdef", "partner-a", "10.10.10.5", duration=80)),
        normalize_otel_record(_doc(3, "payment", "orders", "POST /payment/1234567890abcdef", None, "10.240.147.249", status=403, duration=44)),
        normalize_otel_record(_doc(4, "payment", "orders", "POST /payment/1234567890abcdef", "partner-a", "10.10.10.6", duration=31)),
    ]
    assert all(traces)
    assert traces[0].request_bytes == 120
    assert traces[0].response_bytes == 480
    assert traces[2].traffic_class == "anonymous"
    TraceRepository(str(db_path)).insert_traces(traces)
    result = aggregate_traces(db_path=str(db_path))
    assert result["1m_buckets"] >= 1

    repo = InteractiveTopologyRepository(str(db_path))
    window = repo.resolve_window("5m", start_ms=traces[0].timestamp_ms - 300_000, end_ms=traces[0].timestamp_ms + 300_000)
    graph = repo.service_graph(window)
    assert graph["nodes"]
    assert graph["edges"]
    edge = graph["edges"][0]
    assert edge["metrics"]["request_count"] == 4
    assert edge["metrics"]["request_bytes"] == 480
    assert edge["metrics"]["response_bytes"] == 1920
    assert edge["metrics"]["http_4xx_rate"] > 0
    assert edge["metrics"]["evidence_type"] in {"direct", "inferred"}
    assert graph["anonymous"]["anonymous_requests"] == 1

    search = repo.search_entities("partner", window)
    assert search["items"]
    assert search["items"][0]["type"] == "principal"
    assert search["items"][0]["service"] == "payment"
    assert search["items"][0]["api"] == "payment/{id}"

    detail = repo.service_metrics("payment", window)
    assert detail["series"]
    assert detail["series"][0]["tps"] > 0
    assert detail["metrics"]["total_bytes"] == 2400
    assert detail["metrics"]["bandwidth_bytes_per_second"] == 4.0
    assert detail["metrics"]["bandwidth_bits_per_second"] == 32.0
    assert detail["series"][0]["bandwidth_bytes_per_second"] == 8.0

    dashboard_bandwidth = repo.bandwidth_metrics(window)
    assert dashboard_bandwidth["metrics"]["bandwidth_bytes_per_second"] == 4.0
    assert dashboard_bandwidth["series"][0]["bandwidth_bytes_per_second"] == 8.0
    account_bandwidth = repo.bandwidth_metrics(window, {"account": "partner-a"})
    assert account_bandwidth["metrics"]["bandwidth_bytes_per_second"] == 3.0

    apis = repo.service_apis("payment", window)
    assert apis["nodes"]
    connections = repo.api_connections("payment", apis["nodes"][0]["api"], window)
    assert connections["edges"]
    assert {edge["source"] for edge in connections["edges"]} == {"service:orders"}
    assert all(edge["target"] == f"api:payment:{apis['nodes'][0]['api']}" for edge in connections["edges"])
    principals = repo.api_principals("payment", apis["nodes"][0]["api"], window)
    assert {node["name"] for node in principals["nodes"]} >= {"partner-a", "-anonymous-"}
    api_detail = repo.api_metrics(apis["nodes"][0]["api"], window, "payment")
    assert api_detail["metrics"]["bandwidth_bytes_per_second"] == 4.0
    principal_detail = repo.principal_metrics("partner-a", window)
    assert principal_detail["metrics"]["total_bytes"] == 1800
    assert principal_detail["metrics"]["bandwidth_bytes_per_second"] == 3.0
    services = repo.principal_services("partner-a", window)
    assert [node["name"] for node in services["nodes"]] == ["payment"]
    assert services["parent"]["type"] == "principal"
    user_apis = repo.principal_service_apis("partner-a", "payment", window)
    assert [node["name"] for node in user_apis["nodes"]] == ["payment/{id}"]
    assert user_apis["parent"]["type"] == "service"
    ips = repo.principal_ips("partner-a", window, 1, None)
    assert ips["items"]
    assert ips["items"][0]["is_load_balancer"] is False
    assert ips["items"][0]["is_new_ip"] is True
    assert ips["next_cursor"] is not None
    page2 = repo.principal_ips("partner-a", window, 1, ips["next_cursor"])
    assert len(page2["items"]) == 1
    if page2["next_cursor"]:
        assert repo.principal_ips("partner-a", window, 1, page2["next_cursor"])["items"] == []

    performance = UserRepository(str(db_path)).performance(
        "partner-a",
        start_ms=window["start_ms"],
        end_ms=window["end_ms"],
        bucket_size=300,
    )
    assert performance["bandwidth"]["total_bytes"] == 1800
    assert performance["bandwidth"]["bandwidth_bytes_per_second"] == 3.0
    assert performance["series"][0]["bandwidth_bytes_per_second"] == 6.0
    assert performance["kpis"]["current_5m"]["bandwidth_bits_per_second"] == 48.0


def test_topology_api_rejects_invalid_window_without_store_access():
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/topology/services?window=invalid")

    response = asyncio.run(request())
    assert response.status_code == 422


def test_elasticsearch_topology_series_uses_worker_rollups_only(tmp_path, monkeypatch):
    from backend.app.repositories.aggregate_repository import AggregateRepository
    from backend.app.repositories.elasticsearch_bandwidth_repository import ElasticsearchBandwidthRepository

    repo = InteractiveTopologyRepository(str(tmp_path / "unused.db"))
    captured = []
    timestamp_ms = 1_789_699_800_000
    def metric_query(_self, start, end, **filters):
        captured.append((start, end, filters))
        return [{"bucket_start": timestamp_ms // 1000, "requests": 600, "errors": 6, "latency_p95": 42}]
    def bandwidth_query(_self, start, end, filters):
        captured.append((start, end, filters))
        return {"series": [{"timestamp_ms": timestamp_ms, "request_bytes": 3000, "response_bytes": 6000}]}
    monkeypatch.setattr(AggregateRepository, "query_series", metric_query)
    monkeypatch.setattr(ElasticsearchBandwidthRepository, "query", bandwidth_query)
    repo._es_request = lambda _body: (_ for _ in ()).throw(AssertionError("raw APM query"))
    series = repo._es_series({"start_ms": 1_789_000_000_000, "end_ms": 1_789_700_000_000, "duration_seconds": 700_000}, {"target_service": "payment"})

    metric_call = next(call for call in captured if "bucket_size" in call[2])
    bandwidth_call = next(call for call in captured if "bucket_size" not in call[2])
    assert metric_call[2]["bucket_size"] == 300
    assert metric_call[2]["service"] == "payment"
    assert bandwidth_call[2]["service"] == "payment"
    assert series[0]["tps"] == 2.0
    assert series[0]["total_bytes"] == 9000
    assert series[0]["bandwidth_bytes_per_second"] == 30.0


def test_topology_api_surface_is_bounded_and_backward_compatible():
    paths = [
        "/api/v1/topology/search?q=payment&window=7d",
        "/api/v1/topology/services?window=5m",
        "/api/v1/topology/bandwidth?window=30d&from=1789700000000&to=1789700300000",
        "/api/v1/topology/services/payment/apis?window=5m",
        f"/api/v1/topology/services/payment/api-connections?api={quote('payment/charge', safe='')}&window=5m",
        f"/api/v1/topology/services/payment/apis/{quote('payment/charge', safe='')}/principals?window=5m",
        "/api/v1/topology/services/payment/metrics?window=5m",
        f"/api/v1/topology/apis/{quote('payment/charge', safe='')}/metrics?service=payment&window=5m",
        "/api/v1/topology/principals/partner-a/metrics?window=5m",
        "/api/v1/topology/principals/partner-a/services?window=5m",
        "/api/v1/topology/principals/partner-a/services/payment/apis?window=5m",
        "/api/v1/services/payment/bandwidth?from=1789700000000&to=1789700300000",
        "/api/v1/topology/principals/partner-a/ips?window=5m&page_size=1",
    ]

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return [await client.get(path) for path in paths]

    responses = asyncio.run(request())
    assert all(response.status_code == 200 for response in responses), [response.text for response in responses]
    assert {"query", "items", "window"} <= responses[0].json().keys()
    assert {"nodes", "edges", "window"} <= responses[1].json().keys()
    assert {"metrics", "series", "window", "backend"} <= responses[2].json().keys()
    for response in responses[6:9]:
        assert {
            "request_bytes_per_second",
            "response_bytes_per_second",
            "bandwidth_bytes_per_second",
            "bandwidth_bits_per_second",
        } <= response.json()["metrics"].keys()
    assert {"metrics", "series", "window", "backend"} <= responses[-2].json().keys()
    assert {"items", "next_cursor", "window"} <= responses[-1].json().keys()
