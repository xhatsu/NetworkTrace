"""ELK bandwidth is materialized by the worker without copying application traces."""
import json
from unittest.mock import MagicMock, patch

from backend.app.repositories.elasticsearch_bandwidth_repository import ElasticsearchBandwidthRepository
from backend.worker import _run_elasticsearch_bandwidth, _run_elasticsearch_sync


def _response(status, payload=None):
    result = MagicMock()
    result.status_code = status
    result.json.return_value = payload or {}
    return result


def test_rollup_indexes_only_aggregate_documents_and_reads_them():
    repo = ElasticsearchBandwidthRepository()
    repo.url = "http://elk.test:9200"
    client = MagicMock()
    client.__enter__.return_value = client
    client.head.return_value = _response(200)
    client.post.side_effect = [
        _response(200, {"aggregations": {"buckets": {"buckets": [{
            "key": {"bucket_start_ms": 300000, "principal": "sale", "service": "checkout", "operation": "POST /buy"},
            "doc_count": 2,
            "request_bytes": {"value": 120}, "response_bytes": {"value": 180},
            "request_samples": {"value": 2}, "response_samples": {"value": 2},
        }], "after_key": {"bucket_start_ms": 300000}}}}),
        _response(200, {"errors": False}),
        _response(200, {"aggregations": {
            "request_bytes": {"value": 120}, "response_bytes": {"value": 180},
            "request_count": {"value": 2}, "request_samples": {"value": 2}, "response_samples": {"value": 2},
            "buckets": {"buckets": [{"key": 300000,
                "request_bytes": {"value": 120}, "response_bytes": {"value": 180},
                "request_count": {"value": 2}, "request_samples": {"value": 2}, "response_samples": {"value": 2}}]},
        }}),
    ]
    with patch.object(repo, "_client", return_value=client):
        result = repo.materialize_window(300000, 600000)
        queried = repo.query(300000, 600000, {"account": "sale"})
    assert result["documents"] == 1 and result["complete"]
    source_body = client.post.call_args_list[0].kwargs["json"]
    assert source_body["size"] == 0
    assert source_body["aggs"]["buckets"]["composite"]["sources"][0]["bucket_start_ms"]["date_histogram"]["fixed_interval"] == "5m"
    bulk_call = client.post.call_args_list[1]
    assert bulk_call.args[0].endswith("/_bulk?refresh=wait_for")
    lines = bulk_call.kwargs["content"].splitlines()
    assert json.loads(lines[1]) == {
        "bucket_start_ms": 300000, "principal": "sale", "service": "checkout", "operation": "POST /buy",
        "request_count": 2, "request_bytes": 120, "response_bytes": 180,
        "request_samples": 2, "response_samples": 2,
    }
    assert queried["available"] is True
    assert queried["metrics"]["bandwidth_bytes_per_second"] == 1
    assert queried["series"][0]["bandwidth_bytes_per_second"] == 1
    assert {"term": {"principal": "sale"}} in client.post.call_args_list[2].kwargs["json"]["query"]["bool"]["filter"]


def test_rollup_missing_index_is_unavailable():
    repo = ElasticsearchBandwidthRepository()
    repo.url = "http://elk.test:9200"
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _response(404)
    with patch.object(repo, "_client", return_value=client):
        result = repo.query(0, 300000)
    assert result["available"] is False
    assert result["series"] == []


def test_worker_rollup_checkpoints_completed_window_and_skips_raw_sync():
    with patch("backend.worker._checkpoint", return_value={"bandwidth": {"mode": "backfill", "cursor_ms": 900000}}), \
         patch("backend.worker._save_stage_checkpoint") as save, \
         patch("backend.worker.time.time", return_value=900), \
         patch("backend.worker.settings") as worker_settings, \
         patch("backend.app.repositories.elasticsearch_bandwidth_repository.ElasticsearchBandwidthRepository.materialize_window",
               return_value={"documents": 3, "pages": 1, "complete": True, "after_key": None}) as materialize:
        worker_settings.worker_start_time_ms = 0
        worker_settings.clickhouse_only_agent_traces = True
        result = _run_elasticsearch_bandwidth()
        assert result["documents"] == 3
        assert materialize.call_args.args[:2] == (0, 900000)
        assert save.call_args.args[0] == "worker_elasticsearch_sync"
        assert save.call_args.args[1]["bandwidth"]["mode"] == "live"


def test_elasticsearch_stage_is_aggregate_only_for_agent_only_mode():
    with patch("backend.worker.settings") as worker_settings, \
         patch("backend.worker._run_elasticsearch_metrics", return_value={"buckets": 2}) as metrics, \
         patch("backend.worker._run_elasticsearch_bandwidth", return_value={"documents": 2}) as rollup, \
         patch("backend.worker._checkpoint", return_value={"bandwidth": {"mode": "live"}}), \
         patch("backend.worker._save_stage_checkpoint"), \
         patch("backend.elasticsearch.ElasticsearchReader.sync") as raw_sync, \
         patch.dict("os.environ", {"OTEL_ES_URL": "http://elk.test:9200"}):
        worker_settings.clickhouse_only_agent_traces = True
        result = _run_elasticsearch_sync()
    assert result["bandwidth"]["documents"] == 2
    assert result["metrics"]["buckets"] == 2
    assert result["read"] == result["inserted"] == 0
    metrics.assert_called_once()
    rollup.assert_called_once()
    raw_sync.assert_not_called()


def test_bandwidth_api_reads_worker_rollup():
    from backend.app.api.topology import interactive_bandwidth

    rollup = {"metrics": {"bandwidth_bytes_per_second": 3}, "series": [], "available": True,
              "backend": "elasticsearch_rollup"}
    repo = MagicMock()
    repo.bandwidth_metrics.return_value = {**rollup, "window": {"start_ms": 0, "end_ms": 300000}}
    with patch("backend.app.api.topology._interactive_window", return_value=(repo, {"start_ms": 0, "end_ms": 300000})) as window:
        response = interactive_bandwidth(window="5m", from_time=None, to_time=None, account="sale", service=None, operation=None)
    assert response["metrics"]["bandwidth_bytes_per_second"] == 3
    repo.bandwidth_metrics.assert_called_once_with({"start_ms": 0, "end_ms": 300000},
                                  {"service": None, "operation": None, "account": "sale"})
    window.assert_called_once()
