"""The worker transfers Elasticsearch aggregates, never application trace documents."""
from unittest.mock import MagicMock, patch

from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.elasticsearch_metric_repository import ElasticsearchMetricRepository
from backend.app.repositories.interactive_topology_repository import InteractiveTopologyRepository
from backend.worker import _run_elasticsearch_metrics


def _response(payload):
    result = MagicMock()
    result.status_code = 200
    result.json.return_value = payload
    return result


def test_elasticsearch_metric_materialization_writes_only_buckets():
    repo = ElasticsearchMetricRepository("test_metrics")
    repo.url = "http://elk.test:9200"
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _response({"aggregations": {"buckets": {"buckets": [{
        "key": {"bucket_start_ms": 300000, "caller": "frontend", "service": "billing",
                "principal": "sale", "operation": "billing/pay"},
        "doc_count": 3,
        "errors": {"doc_count": 1},
        "latency": {"sum": 90, "avg": 30, "min": 10, "max": 50},
        "latency_percentiles": {"values": {"50.0": 30, "95.0": 50, "99.0": 50}},
        "request_bytes": {"value": 1200},
        "response_bytes": {"value": 2400},
        "request_bytes_samples": {"value": 2},
        "response_bytes_samples": {"value": 3},
    }]}}})
    with patch.object(repo, "_client", return_value=client), \
         patch("backend.app.repositories.elasticsearch_metric_repository.AggregateRepository.save_buckets") as save:
        result = repo.materialize_window(300000, 600000, 300)
    result.pop("edge_resolution")
    assert result == {"buckets": 1, "pages": 1, "complete": True, "after_key": None}
    body = client.post.call_args.kwargs["json"]
    assert body["size"] == 0
    assert body["aggs"]["buckets"]["composite"]["sources"][0]["bucket_start_ms"]["date_histogram"]["fixed_interval"] == "300s"
    assert body["aggs"]["buckets"]["aggs"]["request_bytes"] == {"sum": {"field": "topology.request_bytes"}}
    assert body["aggs"]["buckets"]["aggs"]["request_bytes_samples"] == {"value_count": {"field": "topology.request_bytes"}}
    assert "replaceAll" in body["runtime_mappings"]["topology.metric_operation"]["script"]["source"]
    assert {"term": {"processor.event": "transaction"}} in body["query"]["bool"]["filter"][1]["bool"]["should"]
    bucket = save.call_args.args[0][0]
    assert (bucket.bucket_start, bucket.bucket_size, bucket.principal_name, bucket.request_count, bucket.error_count) == (300, 300, "sale", 3, 1)
    assert bucket.latency_p95 == 50
    assert bucket.operation == "billing/pay"
    assert (bucket.request_bytes, bucket.response_bytes) == (1200, 2400)
    assert (bucket.request_bytes_samples, bucket.response_bytes_samples) == (2, 3)


def test_elasticsearch_ip_metric_materialization_writes_to_tables():
    repo = ElasticsearchMetricRepository("test_metrics")
    repo.url = "http://elk.test:9200"
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _response({"aggregations": {"ips": {"buckets": [{
        "key": {
            "bucket_start_ms": 300000, "source_ip": "10.0.0.1", "service": "billing",
            "api": "POST /pay", "caller_service": "frontend", "principal": "alice_wsse",
        },
        "doc_count": 10,
        "errors": {"doc_count": 2},
        "auth_failures": {"doc_count": 1},
        "http_4xx": {"doc_count": 1},
        "http_5xx": {"doc_count": 1},
        "p95_latency": {"values": {"95.0": 42.5}},
        "request_bytes": {"value": 5000},
        "response_bytes": {"value": 8000},
    }]}}})
    mock_db = MagicMock()
    mock_db.execute.return_value.fetchall.return_value = []
    mock_db.client = MagicMock()
    with patch.object(repo, "_client", return_value=client), \
         patch("backend.app.repositories.elasticsearch_metric_repository.get_connection", return_value=MagicMock(__enter__=MagicMock(return_value=mock_db))):
        result = repo.materialize_ip_window(300000, 600000)
    assert result == {"rows": 1, "pages": 1, "complete": True, "after_key": None}
    body = client.post.call_args.kwargs["json"]
    assert body["size"] == 0
    assert body["aggs"]["ips"]["composite"]["sources"][0]["bucket_start_ms"]["date_histogram"]["fixed_interval"] == "300s"
    assert body["aggs"]["ips"]["composite"]["sources"][1]["source_ip"]["terms"]["field"] == "topology.source_ip"
    assert mock_db.client.insert.call_count == 2
    args_5m = mock_db.client.insert.call_args_list[0]
    assert args_5m.args[0] == "topology_principal_ip_5m"
    row = args_5m.args[1][0]
    # bucket_start, principal, source_ip, service, api, caller_service, request_count, error_count, auth_failure_count
    assert row[0] == 300
    assert row[1] == "alice_wsse"
    assert row[2] == "10.0.0.1"
    assert row[3] == "billing"
    assert row[4] == "POST /pay"
    assert row[5] == "frontend"
    assert row[6] == 10
    assert row[7] == 2
    assert row[8] == 1
    assert row[12] == 42.5


def test_worker_metric_stage_refreshes_recent_and_advances_backfill():
    complete = {"buckets": 1, "pages": 1, "complete": True, "after_key": None}
    complete_ip = {"rows": 1, "pages": 1, "complete": True, "after_key": None}
    with patch("backend.worker._checkpoint", return_value={"metrics": {"mode": "live", "bytes_schema_version": 0, "ip_bootstrap_complete": True}}), \
         patch("backend.worker._save_stage_checkpoint") as save, \
         patch("backend.worker._mark_elasticsearch_metric_windows", return_value=0), \
         patch.object(AggregateRepository, "delete_window") as delete_window, \
         patch.object(ElasticsearchMetricRepository, "delete_ip_window") as delete_ip_window, \
         patch.object(ElasticsearchMetricRepository, "earliest_timestamp_ms", return_value=1), \
         patch("backend.worker.time.time", return_value=900), \
         patch("backend.worker.settings") as settings, \
         patch("backend.app.repositories.elasticsearch_metric_repository.ElasticsearchMetricRepository.materialize_window", return_value=complete) as materialize, \
         patch("backend.app.repositories.elasticsearch_metric_repository.ElasticsearchMetricRepository.materialize_ip_window", return_value=complete_ip) as materialize_ip:
        settings.worker_start_time_ms = 0
        result = _run_elasticsearch_metrics()
    assert materialize.call_count == 3
    assert materialize_ip.call_count >= 1
    assert materialize.call_args_list[0].args[:3] == (300000, 900000, 300)
    assert materialize.call_args_list[1].args[:3] == (300000, 900000, 60)
    assert materialize.call_args_list[2].args[:3] == (0, 900000, 300)
    # Only the Elasticsearch-retained range (first full bucket after the oldest doc) is rebuilt.
    delete_window.assert_called_once_with(300, 900)
    delete_ip_window.assert_called_once_with(300000, 900000)
    assert result["grain"] == 300
    assert save.call_args.args[1]["metrics"]["grain"] == 60
    assert save.call_args.args[1]["metrics"]["bytes_schema_version"] == 2


def test_bandwidth_response_uses_metric_bucket_bytes_only():
    repo = InteractiveTopologyRepository("test_metric_bucket_bandwidth")
    window = {"start_ms": 300000, "end_ms": 600000, "duration_seconds": 300}
    metric_row = {
        "bucket_start": 300, "requests": 2, "errors": 1, "latency_p95": 25,
        "request_bytes": 0, "response_bytes": 600,
        "request_bytes_samples": 2, "response_bytes_samples": 2,
    }
    with patch.object(AggregateRepository, "query_series", return_value=[metric_row]) as query, \
         patch.object(repo, "_es_request", side_effect=AssertionError("bandwidth must not query raw traces")):
        result = repo.bandwidth_metrics(window, {"account": "sale"})

    query.assert_called_once_with(300, 600, bucket_size=300, service=None, principal="sale", caller=None, operation=None)
    assert result["backend"] == "metric_buckets"
    assert result["available"] is True
    assert result["metrics"]["request_bytes"] == 0
    assert result["metrics"]["response_bytes"] == 600
    assert result["series"][0]["bandwidth_bytes_per_second"] == 2
