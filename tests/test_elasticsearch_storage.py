"""Tests for Elasticsearch / ELK trace repository and fallback behavior."""
import json
import pytest
from unittest.mock import MagicMock, patch
from backend.config import settings
from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.elasticsearch_trace_repository import ElasticsearchTraceRepository
from backend.app.repositories.trace_repository import TraceRepository


def test_elasticsearch_trace_repo_is_configured():
    with patch("backend.app.repositories.elasticsearch_trace_repository.settings") as mock_settings:
        mock_settings.trace_storage_backend = "clickhouse"
        mock_settings.elasticsearch_url = ""
        repo = ElasticsearchTraceRepository()
        assert not repo.is_configured()

        mock_settings.trace_storage_backend = "elasticsearch"
        assert repo.is_configured()

        mock_settings.trace_storage_backend = "elk"
        assert repo.is_configured()

        mock_settings.trace_storage_backend = "clickhouse"
        mock_settings.elasticsearch_url = "http://elk.internal:9200"
        assert repo.is_configured()


def test_elasticsearch_get_trace_success():
    fake_hit = {
        "_source": {
            "@timestamp": "2026-09-08T10:00:00.000Z",
            "trace": {"id": "trace-12345"},
            "transaction": {"id": "span-abc", "name": "OrderService/createOrder", "duration": {"us": 45000}},
            "service": {"name": "order-service", "environment": "production"},
            "user": {"name": "sale"},
            "http": {"response": {"status_code": 200}},
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"hits": {"hits": [fake_hit]}}

    repo = ElasticsearchTraceRepository()
    repo.url = "http://localhost:9200"

    with patch("httpx.Client.post", return_value=mock_resp):
        res = repo.get_trace("trace-12345")
        assert res is not None
        assert res["trace_id"] == "trace-12345"
        assert res["count"] == 1
        assert res["backend"] == "elasticsearch"
        span = res["spans"][0]
        assert span["service_name"] == "order-service"
        assert span["principal_name"] == "sale"


def test_elasticsearch_list_traces_success():
    fake_hit = {
        "_source": {
            "@timestamp": "2026-09-08T10:00:00.000Z",
            "trace": {"id": "trace-999"},
            "transaction": {"id": "span-999", "name": "PaymentService/charge", "duration": {"us": 120000}},
            "service": {"name": "payment-service", "environment": "production"},
            "user": {"name": "vtp"},
            "http": {"response": {"status_code": 500}},
            "outcome": "failure",
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"hits": {"hits": [fake_hit]}}

    repo = ElasticsearchTraceRepository()
    repo.url = "http://localhost:9200"

    with patch("httpx.Client.post", return_value=mock_resp):
        rows = repo.list_traces(service="payment-service", status="error", limit=10)
        assert rows is not None
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "trace-999"
        assert rows[0]["service_name"] == "payment-service"
        assert rows[0]["principal_name"] == "vtp"


def test_trace_repository_fallback_to_clickhouse():
    repo = TraceRepository()
    # Mock _es_repo to simulate an error
    with patch.object(repo._es_repo, "is_configured", return_value=True), \
         patch.object(repo._es_repo, "get_trace", side_effect=Exception("Connection refused")):
        # Should catch exception and gracefully query ClickHouse (returning None or matching rows without crashing)
        result = repo.get_trace("non-existent-trace-id")
        assert result is None


def test_elasticsearch_reader_no_empty_apikey_header():
    from backend.elasticsearch import ElasticsearchReader
    with patch.dict("os.environ", {"OTEL_ES_URL": "http://127.0.0.1:32073", "OTEL_ES_API_KEY": ""}):
        reader = ElasticsearchReader()
        assert reader.url == "http://127.0.0.1:32073"
        assert reader.api_key == ""

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"hits": {"hits": []}}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            pages = list(reader.pages())
            assert len(pages) == 0
            # Inspect headers passed to httpx.Client
            _, kwargs = mock_client_cls.call_args
            assert "Authorization" not in kwargs.get("headers", {})


def test_worker_runs_elasticsearch_sync_when_configured():
    from backend.worker import run_jobs

    with patch("backend.elasticsearch.ElasticsearchReader.sync", return_value={"read": 5, "inserted": 5}) as mock_sync, \
         patch("backend.worker.settings") as worker_settings, \
         patch("backend.worker.aggregate_traces", return_value={"1m_buckets": 1, "5m_buckets": 1, "service_edges": 0, "principal_edges": 0}), \
         patch("backend.worker._run_changed_baselines", return_value=0), \
         patch("backend.worker._run_revised_anomalies", return_value=[]), \
         patch("backend.worker.process_principal_intelligence", return_value={"processed": 0, "changes": 0}), \
         patch.dict("os.environ", {"OTEL_ES_URL": "http://127.0.0.1:32073"}):

        worker_settings.clickhouse_only_agent_traces = False
        worker_settings.analytics_stage_budget_seconds = 60

        result = run_jobs()
        assert "elasticsearch_read" in result
        assert result["elasticsearch_read"] == 5
        assert result["elasticsearch_inserted"] == 5
        mock_sync.assert_called_once()
