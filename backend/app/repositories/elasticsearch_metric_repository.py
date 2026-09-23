"""Worker-side Elasticsearch transaction aggregation into ClickHouse metric_buckets.

Only grouped counts, latency summaries, and dimensions cross into ClickHouse.
Application trace documents remain in Elasticsearch.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from backend.app.models.aggregate import MetricBucket
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.elasticsearch_bandwidth_repository import ElasticsearchBandwidthRepository
from backend.app.repositories.interactive_topology_repository import InteractiveTopologyRepository


PAGE_SIZE = 250
MAX_PAGES_PER_CYCLE = 4


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


class ElasticsearchMetricRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        self.source = ElasticsearchBandwidthRepository()

    @staticmethod
    def _query(start_ms: int, end_ms: int, bucket_size: int, after_key: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        runtime = InteractiveTopologyRepository._es_runtime()
        fields = ("topology.caller", "topology.target", "topology.api", "topology.principal", "topology.duration_ms")
        composite: Dict[str, Any] = {
            "size": PAGE_SIZE,
            "sources": [
                {"bucket_start_ms": {"date_histogram": {"field": "@timestamp", "fixed_interval": f"{bucket_size}s"}}},
                {"caller": {"terms": {"field": "topology.caller", "missing_bucket": True}}},
                {"service": {"terms": {"field": "topology.target", "missing_bucket": True}}},
                {"principal": {"terms": {"field": "topology.principal", "missing_bucket": True}}},
                {"operation": {"terms": {"field": "topology.api", "missing_bucket": True}}},
            ],
        }
        if after_key:
            composite["after"] = after_key
        transaction = {"bool": {"should": [
            {"term": {"processor.event": "transaction"}},
            {"bool": {"filter": [
                {"bool": {"must_not": [{"exists": {"field": "processor.event"}}]}},
                {"bool": {"should": [
                    {"exists": {"field": "transaction.name"}},
                    {"term": {"span_kind": "server"}},
                    {"term": {"span.kind": "server"}},
                ], "minimum_should_match": 1}},
            ]}},
        ], "minimum_should_match": 1}}
        return {
            "size": 0,
            "track_total_hits": False,
            "runtime_mappings": {field: runtime[field] for field in fields},
            "query": {"bool": {"filter": [
                {"range": {"@timestamp": {"gte": start_ms, "lt": end_ms}}},
                transaction,
            ]}},
            "aggs": {"buckets": {"composite": composite, "aggs": {
                "latency": {"stats": {"field": "topology.duration_ms"}},
                "latency_percentiles": {"percentiles": {"field": "topology.duration_ms", "percents": [50, 95, 99]}},
                "errors": {"filter": {"bool": {"should": [
                    {"range": {"http.response.status_code": {"gte": 400}}},
                    {"range": {"http_status": {"gte": 400}}},
                    {"term": {"event.outcome": "failure"}},
                ], "minimum_should_match": 1}}},
            }}},
        }

    @staticmethod
    def _bucket(source: Dict[str, Any], bucket_size: int) -> MetricBucket:
        key = source.get("key") or {}
        stats = source.get("latency") or {}
        percentile = (source.get("latency_percentiles") or {}).get("values") or {}
        requests = int(source.get("doc_count") or 0)
        return MetricBucket(
            bucket_start=int(key.get("bucket_start_ms") or 0) // 1000,
            bucket_size=bucket_size,
            caller_service=str(key.get("caller") or "")[:200],
            target_service=str(key.get("service") or "unknown")[:200],
            principal_name=str(key.get("principal") or "-anonymous-")[:200],
            operation=str(key.get("operation") or "unknown")[:500],
            request_count=requests,
            error_count=min(requests, int((source.get("errors") or {}).get("doc_count") or 0)),
            latency_sum=_finite(stats.get("sum")),
            latency_avg=_finite(stats.get("avg")),
            latency_min=_finite(stats.get("min")),
            latency_max=_finite(stats.get("max")),
            latency_p50=_finite(percentile.get("50.0")),
            latency_p95=_finite(percentile.get("95.0")),
            latency_p99=_finite(percentile.get("99.0")),
        )

    def materialize_window(
        self, start_ms: int, end_ms: int, bucket_size: int,
        after_key: Optional[Dict[str, Any]] = None, max_pages: int = MAX_PAGES_PER_CYCLE,
    ) -> Dict[str, Any]:
        if bucket_size not in (60, 300):
            raise ValueError("bucket_size must be 60 or 300 seconds")
        if not self.source.url or end_ms <= start_ms:
            return {"buckets": 0, "pages": 0, "complete": True, "after_key": None}
        saved = 0
        pages = 0
        with self.source._client() as client:
            for _ in range(max_pages):
                response = client.post(
                    f"/{self.source.source_index}/_search",
                    json=self._query(start_ms, end_ms, bucket_size, after_key),
                )
                if response.status_code != 200:
                    raise RuntimeError(f"ELK metric aggregation failed: HTTP {response.status_code}")
                aggregation = (response.json().get("aggregations") or {}).get("buckets") or {}
                buckets = aggregation.get("buckets") or []
                pages += 1
                if buckets:
                    AggregateRepository(self.db_path).save_buckets(
                        [self._bucket(bucket, bucket_size) for bucket in buckets]
                    )
                    saved += len(buckets)
                after_key = aggregation.get("after_key")
                if not buckets or len(buckets) < PAGE_SIZE or not after_key:
                    return {"buckets": saved, "pages": pages, "complete": True, "after_key": None}
        return {"buckets": saved, "pages": pages, "complete": False, "after_key": after_key}
