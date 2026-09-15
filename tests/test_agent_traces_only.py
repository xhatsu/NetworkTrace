import pytest
from backend.config import settings
from backend.app.services.normalization import is_agent_trace, normalize_otel_record
from backend.elasticsearch import ElasticsearchReader


@pytest.fixture(autouse=True)
def enable_agent_only_storage(monkeypatch):
    monkeypatch.setenv("OTEL_CLICKHOUSE_ONLY_AGENT_TRACES", "true")
    orig = settings.clickhouse_only_agent_traces
    object.__setattr__(settings, "clickhouse_only_agent_traces", True)
    yield
    object.__setattr__(settings, "clickhouse_only_agent_traces", orig)


def test_is_agent_trace_detection():
    # Agent events
    assert is_agent_trace({"src": "pcap", "caller": "10.0.0.1", "dst_ip": "10.0.0.2", "path": "/api"}) is True
    assert is_agent_trace({"source_probe": "pcap-eth0", "path": "/api"}) is True
    assert is_agent_trace({"source": "agent", "path": "/api"}) is True
    assert is_agent_trace({}, envelope_node="host-node-01") is True

    # Pure OTel trace
    assert is_agent_trace({"name": "GET /api/orders", "service.name": "order-service"}) is False
    assert is_agent_trace({"resourceSpans": []}) is False


def test_normalized_trace_has_is_agent_flag():
    # Agent record
    agent_raw = {"src": "pcap", "caller": "10.0.0.1", "dst_ip": "10.0.0.2", "path": "/test", "timestamp": 1789000000}
    agent_trace = normalize_otel_record(agent_raw)
    assert agent_trace is not None
    assert agent_trace.is_agent_trace is True

    # OTel record
    otel_raw = {"name": "/api/users", "service.name": "user-service", "timestamp": 1789000000}
    otel_trace = normalize_otel_record(otel_raw)
    assert otel_trace is not None
    assert otel_trace.is_agent_trace is False


def test_elasticsearch_sync_skips_when_agent_only():
    reader = ElasticsearchReader()
    result = reader.sync()
    assert result["status"] == "skipped"
    assert result["read"] == 0
    assert result["inserted"] == 0


def test_api_ingest_filters_otel_and_accepts_agent():
    from fastapi.testclient import TestClient
    from backend.app.application import create_app, ROLE_ALL

    app = create_app(ROLE_ALL)
    client = TestClient(app)

    # 1. Direct OTLP JSON is acknowledged without storing to ClickHouse
    otlp_body = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payment"}}]},
                "scopeSpans": [{"spans": [{"traceId": "0102030405060708090a0b0c0d0e0f10", "spanId": "0102030405060708", "name": "pay"}]}]
            }
        ]
    }
    resp = client.post("/api/v1/ingest", json=otlp_body)
    assert resp.status_code == 200
    assert resp.json()["inserted"] == 0
    assert "filtered" in resp.json() or "message" in resp.json()

    # 2. Canonical /v1/traces OTLP endpoint returns partialSuccess without writing to ClickHouse
    resp2 = client.post("/v1/traces", json=otlp_body)
    assert resp2.status_code == 200
    assert resp2.json() == {"partialSuccess": {}}

    # 3. Agent event with node envelope is processed
    agent_body = {
        "node": "vm-host-42",
        "events": [
            {
                "src": "pcap",
                "caller": "10.0.0.5",
                "dst_ip": "10.0.0.10",
                "path": "/api/v1/charge",
                "method": "POST",
                "status": 200,
                "timestamp": 1789000000
            }
        ]
    }
    resp3 = client.post("/api/v1/ingest", json=agent_body)
    assert resp3.status_code == 200
    assert resp3.json()["received"] == 1

