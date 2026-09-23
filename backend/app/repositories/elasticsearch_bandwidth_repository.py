"""Worker-owned five-minute bandwidth rollups stored beside ELK APM data.

Only aggregate counters and dimensions are persisted. Application traces remain
in Elasticsearch and are never copied into ClickHouse by this repository.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Optional

import httpx

from backend.config import settings
from backend.app.repositories.interactive_topology_repository import bandwidth_fields


BUCKET_MS = 300_000
PAGE_SIZE = 250
MAX_PAGES_PER_CYCLE = 8


class ElasticsearchBandwidthRepository:
    def __init__(self) -> None:
        self.url = (os.getenv("OTEL_ES_URL") or settings.elasticsearch_url).rstrip("/")
        self.source_index = os.getenv("OTEL_ES_INDEX") or settings.elasticsearch_index
        self.index = settings.elasticsearch_bandwidth_index
        self.api_key = os.getenv("OTEL_ES_API_KEY") or settings.elasticsearch_api_key
        self.user = os.getenv("OTEL_ES_USER") or settings.elasticsearch_user
        self.password = os.getenv("OTEL_ES_PASSWORD") or settings.elasticsearch_password
        self.verify_tls = settings.elasticsearch_verify_tls
        self.timeout = settings.elasticsearch_timeout

    def _client(self) -> httpx.Client:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        auth = (self.user, self.password) if not self.api_key and self.user and self.password else None
        return httpx.Client(base_url=self.url, verify=self.verify_tls, timeout=self.timeout, headers=headers, auth=auth)

    def _ensure_index(self, client: httpx.Client) -> None:
        response = client.head(f"/{self.index}")
        if response.status_code == 200:
            return
        if response.status_code != 404:
            raise RuntimeError(f"ELK bandwidth index check failed: HTTP {response.status_code}")
        properties = {
            "bucket_start_ms": {"type": "date", "format": "epoch_millis"},
            "principal": {"type": "keyword", "ignore_above": 512},
            "service": {"type": "keyword", "ignore_above": 512},
            "operation": {"type": "keyword", "ignore_above": 1024},
        }
        for field in ("request_count", "request_bytes", "response_bytes", "request_samples", "response_samples"):
            properties[field] = {"type": "long"}
        created = client.put(f"/{self.index}", json={"mappings": {"dynamic": "strict", "properties": properties}})
        if created.status_code not in (200, 201):
            # Another worker can create the same index between HEAD and PUT.
            if created.status_code != 400 or client.head(f"/{self.index}").status_code != 200:
                raise RuntimeError(f"ELK bandwidth index creation failed: HTTP {created.status_code}")

    @staticmethod
    def _source_query(start_ms: int, end_ms: int, after_key: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        # Count each request once: APM transactions, or transaction/server-span
        # envelopes without a processor.event marker. Metric docs are excluded.
        event_filter = {"bool": {"should": [
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
        composite: Dict[str, Any] = {
            "size": PAGE_SIZE,
            "sources": [
                {"bucket_start_ms": {"date_histogram": {"field": "@timestamp", "fixed_interval": "5m"}}},
                {"principal": {"terms": {"field": "topology.principal", "missing_bucket": True}}},
                {"service": {"terms": {"field": "topology.target", "missing_bucket": True}}},
                {"operation": {"terms": {"field": "topology.api", "missing_bucket": True}}},
            ],
        }
        if after_key:
            composite["after"] = after_key
        from backend.app.repositories.interactive_topology_repository import InteractiveTopologyRepository
        runtime = InteractiveTopologyRepository._es_runtime()
        return {
            "size": 0,
            "track_total_hits": False,
            "runtime_mappings": {key: runtime[key] for key in (
                "topology.principal", "topology.target", "topology.api",
                "topology.request_bytes", "topology.response_bytes",
            )},
            "query": {"bool": {"filter": [
                {"range": {"@timestamp": {"gte": start_ms, "lt": end_ms}}},
                event_filter,
                {"bool": {"should": [
                    {"exists": {"field": "topology.request_bytes"}},
                    {"exists": {"field": "topology.response_bytes"}},
                ], "minimum_should_match": 1}},
            ]}},
            "aggs": {"buckets": {"composite": composite, "aggs": {
                "request_bytes": {"sum": {"field": "topology.request_bytes"}},
                "response_bytes": {"sum": {"field": "topology.response_bytes"}},
                "request_samples": {"value_count": {"field": "topology.request_bytes"}},
                "response_samples": {"value_count": {"field": "topology.response_bytes"}},
            }}},
        }

    @staticmethod
    def _document(bucket: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        key = bucket.get("key") or {}
        document = {
            "bucket_start_ms": int(key.get("bucket_start_ms") or 0),
            "principal": str(key.get("principal") or "-anonymous-")[:200],
            "service": str(key.get("service") or "unknown")[:200],
            "operation": str(key.get("operation") or "unknown")[:500],
            "request_count": int(bucket.get("doc_count") or 0),
            "request_bytes": max(0, int((bucket.get("request_bytes") or {}).get("value") or 0)),
            "response_bytes": max(0, int((bucket.get("response_bytes") or {}).get("value") or 0)),
            "request_samples": int((bucket.get("request_samples") or {}).get("value") or 0),
            "response_samples": int((bucket.get("response_samples") or {}).get("value") or 0),
        }
        identity = [document[field] for field in ("bucket_start_ms", "principal", "service", "operation")]
        document_id = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        return document_id, document

    def materialize_window(
        self, start_ms: int, end_ms: int, after_key: Optional[Dict[str, Any]] = None,
        max_pages: int = MAX_PAGES_PER_CYCLE,
    ) -> Dict[str, Any]:
        """Index a bounded page set; return a cursor only after durable bulk success."""
        if not self.url or end_ms <= start_ms:
            return {"documents": 0, "pages": 0, "complete": True, "after_key": None}
        indexed = 0
        pages = 0
        with self._client() as client:
            self._ensure_index(client)
            for _ in range(max_pages):
                response = client.post(f"/{self.source_index}/_search", json=self._source_query(start_ms, end_ms, after_key))
                if response.status_code != 200:
                    raise RuntimeError(f"ELK bandwidth source aggregation failed: HTTP {response.status_code}")
                aggregation = (response.json().get("aggregations") or {}).get("buckets") or {}
                buckets = aggregation.get("buckets") or []
                pages += 1
                if buckets:
                    lines = []
                    for bucket in buckets:
                        document_id, document = self._document(bucket)
                        lines.append(json.dumps({"index": {"_index": self.index, "_id": document_id}}, separators=(",", ":")))
                        lines.append(json.dumps(document, separators=(",", ":")))
                    bulk = client.post(
                        f"/{self.index}/_bulk?refresh=wait_for",
                        content="\n".join(lines) + "\n",
                        headers={"Content-Type": "application/x-ndjson"},
                    )
                    if bulk.status_code != 200 or bulk.json().get("errors"):
                        raise RuntimeError(f"ELK bandwidth bulk index failed: HTTP {bulk.status_code}")
                    indexed += len(buckets)
                after_key = aggregation.get("after_key")
                if not buckets or len(buckets) < PAGE_SIZE or not after_key:
                    return {"documents": indexed, "pages": pages, "complete": True, "after_key": None}
        return {"documents": indexed, "pages": pages, "complete": False, "after_key": after_key}

    def query(self, start_ms: int, end_ms: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Read only the worker's compact rollups, never raw APM documents."""
        filters = filters or {}
        clauses: list[Dict[str, Any]] = [{"range": {"bucket_start_ms": {"gte": start_ms, "lt": end_ms}}}]
        for source_key, field in (("account", "principal"), ("service", "service"), ("operation", "operation")):
            if filters.get(source_key):
                clauses.append({"term": {field: filters[source_key]}})
        empty = {
            "metrics": {**bandwidth_fields(0, 0, max(1, (end_ms - start_ms) / 1000)),
                        "request_count": 0, "request_samples": 0, "response_samples": 0},
            "series": [], "available": False, "backend": "elasticsearch_rollup",
        }
        if not self.url:
            return empty
        measure_aggs = {
            "request_bytes": {"sum": {"field": "request_bytes"}},
            "response_bytes": {"sum": {"field": "response_bytes"}},
            "request_count": {"sum": {"field": "request_count"}},
            "request_samples": {"sum": {"field": "request_samples"}},
            "response_samples": {"sum": {"field": "response_samples"}},
        }
        body = {
            "size": 0, "track_total_hits": False,
            "query": {"bool": {"filter": clauses}},
            "aggs": {**measure_aggs, "buckets": {
                "date_histogram": {"field": "bucket_start_ms", "fixed_interval": "5m", "min_doc_count": 1},
                "aggs": measure_aggs,
            }},
        }
        with self._client() as client:
            response = client.post(f"/{self.index}/_search", json=body)
        if response.status_code == 404:
            return empty
        if response.status_code != 200:
            raise RuntimeError(f"ELK bandwidth rollup query failed: HTTP {response.status_code}")
        aggregations = response.json().get("aggregations") or {}

        def values(part: Dict[str, Any], duration_seconds: float) -> Dict[str, Any]:
            fields = bandwidth_fields(
                (part.get("request_bytes") or {}).get("value"),
                (part.get("response_bytes") or {}).get("value"), duration_seconds,
            )
            return {**fields,
                    "request_count": int((part.get("request_count") or {}).get("value") or 0),
                    "request_samples": int((part.get("request_samples") or {}).get("value") or 0),
                    "response_samples": int((part.get("response_samples") or {}).get("value") or 0)}

        metrics = values(aggregations, max(1, (end_ms - start_ms) / 1000))
        series = [{"timestamp_ms": int(bucket["key"]), **values(bucket, 300)}
                  for bucket in (aggregations.get("buckets") or {}).get("buckets") or []]
        return {
            "metrics": metrics, "series": series,
            "available": metrics["request_samples"] > 0 or metrics["response_samples"] > 0,
            "backend": "elasticsearch_rollup",
        }
