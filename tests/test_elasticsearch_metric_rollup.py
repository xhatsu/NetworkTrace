"""The worker transfers Elasticsearch aggregates, never application trace documents."""
from unittest.mock import MagicMock, patch

from backend.app.repositories.elasticsearch_metric_repository import ElasticsearchMetricRepository
from backend.worker import _run_elasticsearch_metrics


def _response(payload):
    result = MagicMock()
    result.status_code = 200
    result.json.return_value = payload
    return result


def test_elasticsearch_metric_materialization_writes_only_buckets():
    repo = ElasticsearchMetricRepository("test_metrics")
    repo.source.url = "http://elk.test:9200"
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _response({"aggregations": {"buckets": {"buckets": [{
        "key": {"bucket_start_ms": 300000, "caller": "frontend", "service": "billing",
                "principal": "sale", "operation": "POST /pay"},
        "doc_count": 3,
        "errors": {"doc_count": 1},
        "latency": {"sum": 90, "avg": 30, "min": 10, "max": 50},
        "latency_percentiles": {"values": {"50.0": 30, "95.0": 50, "99.0": 50}},
    }]}}})
    with patch.object(repo.source, "_client", return_value=client), \
         patch("backend.app.repositories.elasticsearch_metric_repository.AggregateRepository.save_buckets") as save:
        result = repo.materialize_window(300000, 600000, 300)
    assert result == {"buckets": 1, "pages": 1, "complete": True, "after_key": None}
    body = client.post.call_args.kwargs["json"]
    assert body["size"] == 0
    assert body["aggs"]["buckets"]["composite"]["sources"][0]["bucket_start_ms"]["date_histogram"]["fixed_interval"] == "300s"
    assert {"term": {"processor.event": "transaction"}} in body["query"]["bool"]["filter"][1]["bool"]["should"]
    bucket = save.call_args.args[0][0]
    assert (bucket.bucket_start, bucket.bucket_size, bucket.principal_name, bucket.request_count, bucket.error_count) == (300, 300, "sale", 3, 1)
    assert bucket.latency_p95 == 50


def test_worker_metric_stage_refreshes_recent_and_advances_backfill():
    complete = {"buckets": 1, "pages": 1, "complete": True, "after_key": None}
    with patch("backend.worker._checkpoint", return_value={}), \
         patch("backend.worker._save_stage_checkpoint") as save, \
         patch("backend.worker.time.time", return_value=900), \
         patch("backend.worker.settings") as settings, \
         patch("backend.app.repositories.elasticsearch_metric_repository.ElasticsearchMetricRepository.materialize_window", return_value=complete) as materialize:
        settings.worker_start_time_ms = 0
        result = _run_elasticsearch_metrics()
    assert materialize.call_count == 3
    assert materialize.call_args_list[0].args[:3] == (300000, 900000, 300)
    assert materialize.call_args_list[1].args[:3] == (300000, 900000, 60)
    assert materialize.call_args_list[2].args[:3] == (0, 900000, 300)
    assert result["grain"] == 300
    assert save.call_args.args[1]["metrics"]["grain"] == 60
