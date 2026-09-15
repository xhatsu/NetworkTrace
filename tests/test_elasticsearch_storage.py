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
        mock_settings.storage_backend = "clickhouse"
        mock_settings.elasticsearch_url = ""
        repo = ElasticsearchTraceRepository()
        assert not repo.is_configured()

        mock_settings.storage_backend = "elasticsearch"
        assert repo.is_configured()

        mock_settings.storage_backend = "elk"
        assert repo.is_configured()

        mock_settings.storage_backend = "clickhouse"
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
