from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
import httpx
from urllib.parse import quote
import pytest
from backend.main import app
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.principal_relationships import process_principal_intelligence
from backend.fixtures import synthetic_documents
from backend.repository import StorageRepository
from backend.config import settings
from backend.app.repositories.db_context import db_transaction, get_connection

@pytest.fixture(scope="module", autouse=True)
def populated_database():
    StorageRepository().migrate()
    traces = [trace for doc in synthetic_documents(300, 8) if (trace := normalize_otel_record(doc))]
    TraceRepository().insert_traces(traces)
    aggregate_traces()
    process_principal_intelligence()

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

def test_health_endpoint(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"

def test_overview_endpoint(client):
    res = client.get("/api/v1/overview")
    assert res.status_code == 200
    data = res.json()
    assert "kpis" in data
    assert "series" in data
    assert "top_services" in data
    assert "top_principals" in data
    assert "recent_anomalies" in data

def test_services_endpoints(client):
    res = client.get("/api/v1/services?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert isinstance(data["items"], list)
    if data["items"]:
        svc_name = data["items"][0]["name"]
        res_detail = client.get(f"/api/v1/services/{svc_name}")
        assert res_detail.status_code == 200
        det = res_detail.json()
        assert det["service"] == svc_name
        assert "health" in det
        assert "operations" in det

    # 404 for non-existent service
    res_404 = client.get("/api/v1/services/non-existent-service-12345")
    assert res_404.status_code == 404

def test_principals_endpoints(client):
    res = client.get("/api/v1/principals?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert isinstance(data["items"], list)
    if data["items"]:
        p_name = data["items"][0]["principal_name"]
        res_detail = client.get(f"/api/v1/principals/{p_name}")
        assert res_detail.status_code == 200
        det = res_detail.json()
        assert det["principal_name"] == p_name
        assert "targets" in det
        assert "operations" in det

    # 404 for non-existent principal
    res_404 = client.get("/api/v1/principals/non-existent-principal-xyz")
    assert res_404.status_code == 404

def test_topology_endpoint(client):
    res = client.get("/api/v1/topology")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)
    if data["edges"]:
        edge = data["edges"][0]
        assert "source" in edge
        assert "target" in edge
        assert "requests" in edge

def test_anomalies_and_patch(client):
    res = client.get("/api/v1/anomalies")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    if data["items"]:
        anomaly_id = data["items"][0]["id"]
        res_detail = client.get(f"/api/v1/anomalies/{anomaly_id}")
        assert res_detail.status_code == 200
        det = res_detail.json()
        assert det["id"] == anomaly_id
        assert "blast_radius" in det
        assert "root_cause" in det
        assert "explanation" in det

        # Test patch
        patch_res = client.patch(f"/api/v1/anomalies/{anomaly_id}", json={"status": "investigating"})
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "investigating"

    invalid = client.patch("/api/v1/anomalies/1", json={"status": "arbitrary"})
    assert invalid.status_code == 422

def test_traces_endpoints(client):
    res = client.get("/api/v1/traces?limit=5")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    if data["items"]:
        trace_id = data["items"][0]["trace_id"]
        res_detail = client.get(f"/api/v1/traces/{trace_id}")
        assert res_detail.status_code == 200
        det = res_detail.json()
        assert det["trace_id"] == trace_id
        assert "spans" in det
        assert "waterfall" in det

    # 404 for non-existent trace
    res_404 = client.get("/api/v1/traces/non-existent-trace-id-999")
    assert res_404.status_code == 404

def test_blast_radius_endpoint(client):
    res = client.get("/api/v1/blast-radius/api-gateway")
    assert res.status_code == 200
    data = res.json()
    assert data["root_service"] == "api-gateway"
    assert "direct_callers" in data
    assert "affected_principals" in data
    assert "affected_operations" in data

def test_ingest_alias_validation_and_sanitization(client):
    invalid = client.post("/api/v1/ingest", content=b"not-json", headers={"content-type": "application/json"})
    assert invalid.status_code == 400
    payload = {
        "_source": {
            "@timestamp": "2026-01-01T00:00:00Z",
            "trace": {"id": "api-ingest-trace"},
            "transaction": {"id": "api-ingest-span", "name": "GET /safe", "duration": {"us": 1000}},
            "service": {"name": "api-ingest-service"},
            "labels": {"http_request_header_authorization": "Basic dXNlcjpzdXBlci1zZWNyZXQ="},
        }
    }
    response = client.post("/api/v1/ingest", json=payload)
    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    row = TraceRepository().get_trace("api-ingest-trace")
    assert row is not None
    assert "super-secret" not in repr(row)


def test_ingest_accepts_oldkernel_networktracing_envelope(client):
    payload = {
        "node": "sale-node01",
        "events": [{
            "ts": 1787793510,
            "src": "pcap",
            "service": "port:8010",
            "method": "POST",
            "path": "/SALE_SERVICE/bpm/sale/createOrder",
            "user": "vtp_app",
            "scheme": "basic",
            "caller": "10.207.58.79",
            "caller_port": 39687,
            "dst_ip": "10.240.147.249",
            "dst_port": 8010,
            "status": 200,
            "duration_ms": 14,
            "req_bytes": 482,
            "resp_bytes": 1024,
            "traceparent": "00-ad0d1a24079a814bc0fac5090bdb538b-720eb770ce5a4487-01",
            "source_probe": "pcap-http",
        }],
    }
    # This is the exact path appended by oldkernel/nt-ship.py.
    response = client.post("/api/ingest", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success", "received": 1, "inserted": 1, "rejected": 0}

    stored = TraceRepository().get_trace("ad0d1a24079a814bc0fac5090bdb538b")
    assert stored is not None
    span = stored["spans"][0]
    assert span["span_id"] == "720eb770ce5a4487"
    assert span["service_name"] == "port:8010"
    assert span["service_instance"] == "sale-node01"
    assert span["operation"] == "/SALE_SERVICE/bpm/sale/createOrder"
    assert span["principal_name"] == "vtp_app"
    assert span["caller_ip"] == "10.207.58.79"
    assert span["target_ip"] == "10.240.147.249"
    assert span["target_port"] == 8010
    assert span["duration_us"] == 14000


def test_ingest_oldkernel_event_skips_missing_optional_fields(client):
    response = client.post("/api/v1/ingest", json={
        "node": "minimal-node",
        "events": [{"ts": 1787793511, "src": "pcap", "path": "/health"}],
    })
    assert response.status_code == 200
    assert response.json()["inserted"] == 1


def test_mutations_require_configured_api_key(client):
    previous = settings.api_key
    object.__setattr__(settings, "api_key", "test-api-key")
    try:
        unauthorized = client.post("/api/v1/ingest", json={})
        assert unauthorized.status_code == 401
        authorized = client.post(
            "/api/v1/ingest", json={}, headers={"X-API-Key": "test-api-key"}
        )
        assert authorized.status_code == 200
    finally:
        object.__setattr__(settings, "api_key", previous)


def test_user_intelligence_inventory_profile_and_graph(client):
    inventory = client.get("/api/v1/users?limit=10")
    assert inventory.status_code == 200
    users = inventory.json()["items"]
    assert users and users[0]["principal_type"] == "unknown"
    assert {"unique_callers", "unique_sources", "unique_targets", "behavior_score"} <= users[0].keys()
    principal = users[0]["principal_name"]
    encoded = f"/api/v1/users/{quote(principal, safe='')}"
    profile = client.get(encoded)
    assert profile.status_code == 200
    body = profile.json()
    assert {"normal", "current", "changes", "hourly_activity", "typical_active_window"} <= body.keys()
    for suffix in ("summary", "callers", "sources", "targets", "operations", "timeline", "changes"):
        assert client.get(f"{encoded}/{suffix}").status_code == 200
    graph = client.get(f"/api/v1/user-graph/{principal}")
    assert graph.status_code == 200
    assert {"nodes", "edges", "mode"} <= graph.json().keys()
    assert client.get("/api/v1/user-analytics").status_code == 200
    assert client.get("/api/v1/users/summary").status_code == 200


def test_user_change_lifecycle_and_incremental_cursor(client):
    changes = client.get("/api/v1/user-changes?limit=10")
    assert changes.status_code == 200
    items = changes.json()["items"]
    if items:
        change_id = items[0]["id"]
        updated = client.patch(f"/api/v1/user-changes/{change_id}", json={"status":"expected"})
        assert updated.status_code == 200
        assert updated.json()["status"] == "expected"
    assert client.patch("/api/v1/user-changes/1", json={"status":"invalid"}).status_code == 422
    # HTTP ingestion is durably committed by the hub and analytics are picked up
    # asynchronously by the 60-second worker. The first call may process traces
    # added by earlier API tests; a second incremental pass must be empty.
    assert process_principal_intelligence()["processed"] >= 0
    assert process_principal_intelligence()["processed"] == 0


def test_anomaly_uses_observation_window_and_measured_evidence(client):
    with get_connection() as db:
        bucket = db.execute("""SELECT bucket_start,target_service,SUM(request_count) requests
          FROM metric_buckets WHERE bucket_size=300 GROUP BY bucket_start,target_service
          HAVING requests>0 ORDER BY bucket_start DESC LIMIT 1""").fetchone()
    assert bucket is not None
    start_ms = int(bucket["bucket_start"]) * 1000
    end_ms = start_ms + 300_000
    dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    with db_transaction() as db:
        db.execute("""INSERT INTO baseline_metrics(
          dimension_type,dimension_key,hour_of_day,day_of_week,sample_count,
          rps_median,rps_mad,latency_p50_median,latency_p95_median,latency_p95_mad,
          error_rate_median,error_rate_mad,updated_at) VALUES('service',?,?,?,?,?,?,?,?,?,?,?,?)""",
          (bucket["target_service"], dt.hour, dt.weekday(), 7, 0.1, 0.02, 1, 2, 0.3, 0, 0, end_ms))
        cursor = db.execute("""INSERT INTO anomaly_events(
          detected_at,anomaly_type,severity,score,confidence,target_service,baseline_value,
          current_value,delta_percentage,first_seen,last_seen,status,acknowledged,reason_json,metadata_json)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (end_ms + 86_400_000, "traffic_spike", "high", 80, .9, bucket["target_service"],
           .1, float(bucket["requests"]) / 300, 100, start_ms, end_ms, "open", 0,
           json.dumps([{"text":"Measured observation-window explanation"}]),
           json.dumps({"principals":["checkout-user"]})))
        anomaly_id = cursor.lastrowid
    listing = client.get(f"/api/v1/anomalies?from={start_ms}&to={end_ms + 1}").json()["items"]
    item = next(row for row in listing if row["id"] == anomaly_id)
    assert item["current_samples"] >= 1
    assert item["baseline_samples"] == 7
    detail = client.get(f"/api/v1/anomalies/{anomaly_id}").json()
    assert detail["series"]
    # Trace links are returned only when the worker persisted references on the
    # anomaly row; request-time raw trace searches are intentionally forbidden.
    assert detail["trace_ids"] == []
    assert detail["explanation"] == "Measured observation-window explanation"
    related = client.get("/api/v1/anomalies?principal=checkout-user").json()["items"]
    assert any(row["id"] == anomaly_id for row in related)


def test_user_score_counts_each_change_type_once(client):
    inventory = client.get("/api/v1/users?limit=1").json()["items"]
    assert inventory
    principal = inventory[0]["principal_name"]
    profile = client.get(f"/api/v1/users/{quote(principal, safe='')}").json()
    expected = min(100, sum(max(c["score"] for c in profile["changes"] if c["change_type"] == kind)
                            for kind in {c["change_type"] for c in profile["changes"]
                                         if c["status"] not in {"expected", "ignored"}}))
    assert profile["behavior_score"] == expected
    assert profile["learning_status"] in {"learning", "established"}
