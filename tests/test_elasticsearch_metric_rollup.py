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
    assert result == {"buckets": 1, "pages": 1, "complete": True, "after_key": None}
    body = client.post.call_args.kwargs["json"]
    assert body["size"] == 0
    assert body["aggs"]["buckets"]["composite"]["sources"][0]["bucket_start_ms"]["date_histogram"]["fixed_interval"] == "300s"
    assert body["aggs"]["buckets"]["aggs"]["request_bytes"] == {"sum": {"field": "topology.request_bytes"}}
    assert body["aggs"]["buckets"]["aggs"]["request_bytes_samples"] == {"value_count": {"field": "topology.request_bytes"}}
    assert body["aggs"]["buckets"]["composite"]["sources"][4]["operation"]["terms"]["field"] == "topology.metric_operation"
    assert "lastIndexOf" in body["runtime_mappings"]["topology.metric_operation"]["script"]["source"]
    assert {"term": {"processor.event": "transaction"}} in body["query"]["bool"]["filter"][1]["bool"]["should"]
    bucket = save.call_args.args[0][0]
    assert (bucket.bucket_start, bucket.bucket_size, bucket.principal_name, bucket.request_count, bucket.error_count) == (300, 300, "sale", 3, 1)
    assert bucket.latency_p95 == 50
    assert bucket.operation == "billing/pay"
    assert (bucket.request_bytes, bucket.response_bytes) == (1200, 2400)
    assert (bucket.request_bytes_samples, bucket.response_bytes_samples) == (2, 3)


def test_worker_metric_stage_refreshes_recent_and_advances_backfill():
    complete = {"buckets": 1, "pages": 1, "complete": True, "after_key": None}
    with patch("backend.worker._checkpoint", return_value={"metrics": {"mode": "live", "bytes_schema_version": 0}}), \
         patch("backend.worker._save_stage_checkpoint") as save, \
         patch.object(AggregateRepository, "delete_window") as delete_window, \
         patch("backend.worker.time.time", return_value=900), \
         patch("backend.worker.settings") as settings, \
         patch("backend.app.repositories.elasticsearch_metric_repository.ElasticsearchMetricRepository.materialize_window", return_value=complete) as materialize:
        settings.worker_start_time_ms = 0
        result = _run_elasticsearch_metrics()
    assert materialize.call_count == 3
    assert materialize.call_args_list[0].args[:3] == (300000, 900000, 300)
    assert materialize.call_args_list[1].args[:3] == (300000, 900000, 60)
    assert materialize.call_args_list[2].args[:3] == (0, 900000, 300)
    delete_window.assert_called_once_with(0, 900)
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
