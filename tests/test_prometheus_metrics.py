from __future__ import annotations

import httpx
import pytest

from backend.app.application import ROLE_AGENT_STATS, ROLE_ALL, ROLE_INGEST, create_app
from backend.app.services.prometheus_metrics import (
    PrometheusMetricsRegistry,
    normalize_handler,
    prometheus_registry,
)


def test_normalize_handler():
    assert normalize_handler("/") == "/"
    assert normalize_handler("/metrics") == "/metrics"
    assert normalize_handler("/livez") == "/livez"
    assert normalize_handler("/readyz") == "/readyz"
    assert normalize_handler("/assets/index-abc12345.js") == "/assets/*"
    # Route path takes precedence if provided
    assert normalize_handler("/api/v1/services/order-service", "/api/v1/services/{service}") == "/api/v1/services/{service}"
    # 404 unrouted paths are collapsed
    assert normalize_handler("/random/path/not-existing", None, 404) == "not_found"
    # UUID masking
    assert normalize_handler("/api/v1/traces/12345678-1234-1234-1234-123456789abc") == "/api/v1/traces/{id}"
    assert normalize_handler("/api/v1/anomalies/999999") == "/api/v1/anomalies/{id}"


def test_prometheus_registry_recording():
    reg = PrometheusMetricsRegistry()
    reg.record_request("GET", "/api/v1/overview", 200, 0.045)
    reg.record_request("GET", "/api/v1/overview", 200, 0.080)
    reg.record_request("POST", "/api/v1/ingest", 500, 0.120)

    text = reg.render(role="test")
    assert '# TYPE http_requests_total counter' in text
    assert 'http_requests_total{method="GET",handler="/api/v1/overview",status="200"} 2' in text
    assert 'http_requests_total{method="POST",handler="/api/v1/ingest",status="500"} 1' in text

    assert '# TYPE http_request_duration_seconds histogram' in text
    assert 'http_request_duration_seconds_count{method="GET",handler="/api/v1/overview"} 2' in text
    assert 'http_request_duration_seconds_sum{method="GET",handler="/api/v1/overview"} 0.125000' in text

    assert '# TYPE process_resident_memory_bytes gauge' in text
    assert '# TYPE process_cpu_seconds_total counter' in text
    assert '# TYPE process_start_time_seconds gauge' in text
    assert '# TYPE tracescope_service_info gauge' in text
    assert 'tracescope_service_info{version="0.3.3",role="test",backend="' in text


def test_metrics_endpoint_integration_all_role():
    import asyncio

    async def run():
        app = create_app(ROLE_ALL)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Generate some web traffic
            r1 = await client.get("/api/v1/health")
            assert r1.status_code == 200

            r2 = await client.get("/livez")
            assert r2.status_code == 200

            # Fetch Prometheus metrics
            resp = await client.get("/metrics")
            assert resp.status_code == 200
            assert "text/plain" in resp.headers["content-type"]
            text = resp.text

            # Verify web request metrics recorded by middleware
            assert 'http_requests_total{method="GET",handler="/api/v1/health",status="200"}' in text
            assert 'http_requests_total{method="GET",handler="/livez",status="200"}' in text
            assert "http_request_duration_seconds_bucket" in text
            assert "http_requests_in_progress" in text
            assert "process_resident_memory_bytes" in text
            assert "nt_otel_server_spans_total" in text

    asyncio.run(run())


def test_metrics_endpoint_standalone_roles():
    import asyncio

    async def run():
        for role in (ROLE_INGEST, ROLE_AGENT_STATS):
            app = create_app(role)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                h_resp = await client.get("/api/v1/health")
                assert h_resp.status_code == 200

                m_resp = await client.get("/metrics")
                assert m_resp.status_code == 200
                assert "text/plain" in m_resp.headers["content-type"]
                text = m_resp.text
                assert f'tracescope_service_info{{version="0.3.3",role="{role}"' in text
                assert 'http_requests_total{method="GET",handler="/api/v1/health",status="200"}' in text

    asyncio.run(run())


def test_worker_updates_domain_metrics_snapshot():
    from backend.app.services.prometheus_metrics import (
        update_worker_prometheus_metrics,
        get_worker_metrics_snapshot,
    )

    snap = update_worker_prometheus_metrics(duration_sec=1.234)
    assert "total_spans" in snap
    assert "nodes_reporting" in snap
    assert "worker_last_run_seconds" in snap
    assert snap["worker_cycle_duration_seconds"] == 1.234

    cached = get_worker_metrics_snapshot()
    assert cached["worker_cycle_duration_seconds"] == 1.234
    assert cached["updated_at_ms"] == snap["updated_at_ms"]


def test_render_includes_worker_metrics():
    from backend.app.services.prometheus_metrics import (
        update_worker_prometheus_metrics,
        prometheus_registry,
    )

    update_worker_prometheus_metrics(duration_sec=2.5)
    rendered = prometheus_registry.render(role="all")

    assert "# HELP tracescope_worker_last_run_timestamp_seconds" in rendered
    assert "# HELP tracescope_worker_cycle_duration_seconds" in rendered
    assert "tracescope_worker_cycle_duration_seconds 2.500" in rendered
    assert "# HELP tracescope_open_anomalies_total" in rendered
    assert "# TYPE nt_otel_server_spans_total counter" in rendered
    assert "# TYPE nt_nodes_reporting gauge" in rendered

