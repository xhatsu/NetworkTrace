from __future__ import annotations

import asyncio
import json
import httpx
import pytest

from backend.main import app
from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.normalization import normalize_otel_record
from backend.fixtures import synthetic_documents
from backend.repository import SQLiteRepository


@pytest.fixture(scope="module", autouse=True)
def seed_test_data():
    SQLiteRepository().migrate()
    traces = [trace for doc in synthetic_documents(300, 8) if (trace := normalize_otel_record(doc))]
    TraceRepository().insert_traces(traces)


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

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def patch(self, url, **kwargs):
            return self.request("PATCH", url, **kwargs)

    return Client()


def test_healthz_endpoint(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data.get("ok") is True
    assert data.get("telemetry_source") == "otel"


def test_otel_status_endpoint(client):
    res = client.get("/api/otel/status")
    assert res.status_code == 200
    data = res.json()
    assert data.get("source") == "otel"
    assert data.get("spans") >= 1
    assert data.get("services") >= 1


def test_metrics_prometheus_exposition(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    text = res.text
    assert "# TYPE nt_otel_server_spans_total counter" in text
    assert "# TYPE nt_nodes_reporting gauge" in text
    assert "nt_requests_total{" in text


def test_nodes_and_coverage(client):
    res_nodes = client.get("/api/nodes")
    assert res_nodes.status_code == 200
    nodes_data = res_nodes.json()
    assert "nodes" in nodes_data
    assert len(nodes_data["nodes"]) >= 1

    res_cov = client.get("/api/coverage")
    assert res_cov.status_code == 200
    cov_data = res_cov.json()
    assert cov_data.get("source") == "otel"
    assert len(cov_data["coverage"]) >= 1


def test_users_rpm_callers(client):
    res_users = client.get("/api/users")
    assert res_users.status_code == 200
    users_data = res_users.json()
    assert "users" in users_data

    res_rpm = client.get("/api/rpm?window=86400&anon=1")
    assert res_rpm.status_code == 200
    rpm_data = res_rpm.json()
    assert "rpm" in rpm_data

    res_callers = client.get("/api/callers")
    assert res_callers.status_code == 200
    callers_data = res_callers.json()
    assert "callers" in callers_data


def test_logs_and_export(client):
    res_logs = client.get("/api/logs?limit=5")
    assert res_logs.status_code == 200
    logs_data = res_logs.json()
    assert "logs" in logs_data
    if logs_data["logs"]:
        first_log = logs_data["logs"][0]
        assert "user" in first_log
        assert "@timestamp" in first_log

    res_export = client.get("/api/export/logs?max=5")
    assert res_export.status_code == 200
    lines = [line for line in res_export.text.strip().split("\n") if line]
    if lines:
        parsed = json.loads(lines[0])
        assert "user" in parsed


def test_policy_get_and_post(client):
    res_get = client.get("/api/policy")
    assert res_get.status_code == 200
    pol = res_get.json()
    assert "default_allow_private" in pol

    new_policy = {
        "users": {"admin": ["*"], "guest": ["10.0.0.1"]},
        "allow": ["service-a -> 10.0.1.5:8080"],
        "default_allow_private": True,
    }
    res_post = client.post("/api/policy", json=new_policy)
    assert res_post.status_code == 200
    assert res_post.json().get("ok") is True

    res_get2 = client.get("/api/policy")
    assert res_get2.status_code == 200
    assert "guest" in res_get2.json().get("users", {})


def test_endpoints_diagnostics(client):
    res_slow = client.get("/api/endpoints/slow")
    assert res_slow.status_code == 200
    assert "slow" in res_slow.json()

    res_errors = client.get("/api/endpoints/errors")
    assert res_errors.status_code == 200
    assert "errors" in res_errors.json()

    res_health = client.get("/api/endpoints/health")
    assert res_health.status_code == 200
    assert "endpoints" in res_health.json()

    res_hourly = client.get("/api/traffic/hourly")
    assert res_hourly.status_code == 200
    assert "hourly" in res_hourly.json()


def test_otlp_http_json_traces(client):
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "payment-service"}},
                        {"key": "service.instance.id", "value": {"stringValue": "payment-1"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": "00f067aa0ba902b7",
                                "name": "PaymentService/chargeCard",
                                "kind": 2,
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000050000000",
                                "attributes": [
                                    {"key": "http.status_code", "value": {"intValue": 200}},
                                    {"key": "http.method", "value": {"stringValue": "POST"}},
                                    {"key": "http.route", "value": {"stringValue": "/charge"}},
                                    {"key": "http.request.header.authorization", "value": {"stringValue": "Basic YWxpY2U6c2VjcmV0"}},
                                ],
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            }
        ]
    }
    res = client.post("/v1/traces", json=payload)
    assert res.status_code == 200
    assert "partialSuccess" in res.json()


def test_apm_ndjson_ingest(client):
    doc = {
        "processor": {"name": "transaction", "event": "transaction"},
        "service": {"name": "order-service", "environment": "production", "node": {"configured_name": "order-node-1"}},
        "transaction": {
            "name": "OrderService/createOrder",
            "type": "request",
            "duration": {"us": 32000},
            "result": "HTTP 2xx",
            "sampled": True,
        },
        "context": {
            "request": {
                "method": "POST",
                "url": {"pathname": "/orders"},
                "headers": {"authorization": "Basic Ym9iOnBhc3N3b3JkMTIz"},
            },
            "response": {"status_code": 200},
            "user": {"username": "bob"},
        },
        "trace": {"id": "11112222333344445555666677778888"},
        "@timestamp": "2023-11-14T22:13:20.000Z",
    }
    ndjson_body = json.dumps({"metadata": {}}) + "\n" + json.dumps({"transaction": doc["transaction"], **doc})
    res = client.post("/api/ingest/apm", content=ndjson_body, headers={"Content-Type": "application/x-ndjson"})
    assert res.status_code == 200
    assert res.json().get("ok") is True
    assert res.json().get("accepted") >= 1
