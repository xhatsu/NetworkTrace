"""Worker-side Elasticsearch transaction aggregation into ClickHouse metric_buckets.

Only grouped counts, latency summaries, and dimensions cross into ClickHouse.
Application trace documents remain in Elasticsearch.
"""
from __future__ import annotations

import math
import os
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.app.models.aggregate import MetricBucket
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.db_context import get_connection
from backend.app.repositories.interactive_topology_repository import (
    InteractiveTopologyRepository,
    canonical_api,
    canonical_principal,
    canonical_service,
)
from backend.app.services.normalization import classify_source_ip_role
from backend.app.services.trace_edges import (
    DEFAULT_SKEW_US,
    ResolvedSlice,
    doc_from_source,
    parse_ip_map,
    resolve,
)
from backend.config import settings


PAGE_SIZE = 250
# Each slice costs at least one aggregation request, so the budget counts slices too.
MAX_PAGES_PER_CYCLE = 24
# Caller resolution joins documents within a trace, so windows are processed in
# bucket-aligned slices small enough to fetch their trace documents at once.
SLICE_MS = 15 * 60 * 1000
SLICE_ALIGN_MS = 300 * 1000
# Client spans and callers may start before, or be indexed after, the slice.
CONTEXT_MS = 60 * 1000
# Callers of recent slices can change as late documents arrive. Those slices are
# cleared before rewriting so superseded caller keys do not linger; older slices
# are cleared once by the worker's rebackfill.
RECLEAR_RECENT_MS = 2 * 3600 * 1000
FETCH_LIMIT = 10_000
MIN_FETCH_SPLIT_MS = 60 * 1000
# Shared across worker cycles: backfill resolves a window's slices for the 300s
# grain, IP rollups and then the 60s grain in later cycles.
RESOLUTION_CACHE_SIZE = 32
# Slices that may still receive late documents are reused only within one cycle.
RECENT_RESOLUTION_TTL_S = 45
_RESOLUTIONS: "OrderedDict[Tuple[str, int, int], Tuple[float, ResolvedSlice]]" = OrderedDict()

# Painless prelude binding __id to the document's transaction/span ID, matching
# trace_edges.doc_from_source.
_DOC_ID = (
    "def __src=params['_source']; def __id=__src['transaction.id']; "
    "if (__id == null) { def __tx=__src['transaction']; if (__tx instanceof Map) __id=__tx['id']; } "
    "if (__id == null) __id=__src['span.id']; "
    "if (__id == null) { def __sp=__src['span']; if (__sp instanceof Map) __id=__sp['id']; } "
    "if (__id == null) __id=__src['span_id']; "
    "if (__id == null) __id=__src['spanId']; "
    "if (__id != null) __id=__id.toString(); "
)
_FETCH_SOURCE = [
    "@timestamp", "timestamp", "timestamp_ms", "processor.event", "trace", "trace_id", "traceId",
    "parent", "parent_span_id", "parentSpanId", "transaction.id", "transaction.duration",
    "span.id", "span.duration", "span.destination", "span_id", "spanId", "span_kind", "span.kind",
    "kind", "service.name", "service_name", "duration_ms", "peer.service", "client.ip", "source.ip",
    "labels.service_peer_name", "labels.net_peer_service", "labels.server_address", "labels.url_full",
    "labels.net_sock_host_addr", "labels.net_sock_peer_addr", "labels.network_peer_address",
    "labels.client_address",
]


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


class ElasticsearchMetricRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        self.url = (os.getenv("OTEL_ES_URL") or settings.elasticsearch_url).rstrip("/")
        self.source_index = os.getenv("OTEL_ES_INDEX") or settings.elasticsearch_index
        self.api_key = os.getenv("OTEL_ES_API_KEY") or settings.elasticsearch_api_key
        self.user = os.getenv("OTEL_ES_USER") or settings.elasticsearch_user
        self.password = os.getenv("OTEL_ES_PASSWORD") or settings.elasticsearch_password
        self.verify_tls = settings.elasticsearch_verify_tls
        self.timeout = settings.elasticsearch_timeout
        # Operator map for callers that emit no trace context: "10.1.2.3=billing,10.9.0.0/24=batch".
        self.ip_map = parse_ip_map(os.getenv("OTEL_SERVICE_IP_MAP", ""))
        try:
            self.skew_us = max(0, int(float(os.getenv("OTEL_TRACE_EDGE_SKEW_MS", "")) * 1000))
        except ValueError:
            self.skew_us = DEFAULT_SKEW_US
        self.edge_stats: Dict[str, int] = {}

    def _client(self) -> httpx.Client:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        auth = (self.user, self.password) if not self.api_key and self.user and self.password else None
        return httpx.Client(
            base_url=self.url, verify=self.verify_tls, timeout=self.timeout,
            headers=headers, auth=auth,
        )

    @staticmethod
    def _fetch_body(start_ms: int, end_ms: int) -> Dict[str, Any]:
        runtime = InteractiveTopologyRepository._es_runtime()
        return {
            "size": FETCH_LIMIT,
            "track_total_hits": FETCH_LIMIT + 1,
            "_source": _FETCH_SOURCE,
            "runtime_mappings": {"topology.caller": runtime["topology.caller"]},
            "fields": ["topology.caller"],
            "query": {"bool": {"filter": [
                {"range": {"@timestamp": {"gte": start_ms, "lt": end_ms}}},
                {"bool": {"should": [
                    {"term": {"processor.event": "transaction"}},
                    {"term": {"span.type": "external"}},
                    {"exists": {"field": "labels.service_peer_name"}},
                    {"exists": {"field": "span.destination.service.resource"}},
                    {"exists": {"field": "span_kind"}},
                    {"exists": {"field": "span.kind"}},
                ], "minimum_should_match": 1}},
            ]}},
        }

    def _fetch_docs(self, client: httpx.Client, start_ms: int, end_ms: int) -> List[Any]:
        """Fetch minimal caller-resolution fields, halving ranges above FETCH_LIMIT."""
        response = client.post(f"/{self.source_index}/_search", json=self._fetch_body(start_ms, end_ms))
        if response.status_code != 200:
            raise RuntimeError(f"ELK trace edge fetch failed: HTTP {response.status_code}")
        hits = (response.json().get("hits") or {})
        total = (hits.get("total") or {}).get("value", 0) if isinstance(hits.get("total"), dict) else int(hits.get("total") or 0)
        if total > FETCH_LIMIT and end_ms - start_ms > MIN_FETCH_SPLIT_MS:
            middle = start_ms + (end_ms - start_ms) // 2
            return self._fetch_docs(client, start_ms, middle) + self._fetch_docs(client, middle, end_ms)
        if total > FETCH_LIMIT:
            self.edge_stats["fetch_truncated"] = self.edge_stats.get("fetch_truncated", 0) + 1
        docs = []
        for hit in hits.get("hits") or []:
            explicit = ((hit.get("fields") or {}).get("topology.caller"))
            doc = doc_from_source(hit.get("_source") or {}, explicit)
            if doc is not None:
                docs.append(doc)
        return docs

    def _resolve(self, client: httpx.Client, start_ms: int, end_ms: int) -> ResolvedSlice:
        """Resolve callers of documents starting in [start_ms, end_ms), cached per slice."""
        key = (f"{self.url}/{self.source_index}", start_ms, end_ms)
        cached = _RESOLUTIONS.get(key)
        now = time.time()
        if cached is not None:
            settled = end_ms + CONTEXT_MS + SLICE_MS < now * 1000
            if settled or now - cached[0] < RECENT_RESOLUTION_TTL_S:
                _RESOLUTIONS.move_to_end(key)
                return cached[1]
        docs = self._fetch_docs(client, start_ms - CONTEXT_MS, end_ms + CONTEXT_MS)
        wanted = [d.doc_id for d in docs if start_ms * 1000 <= d.start_us < end_ms * 1000]
        resolved = resolve(docs, wanted, self.ip_map, self.skew_us)
        for name, value in resolved.stats.items():
            self.edge_stats[name] = self.edge_stats.get(name, 0) + value
        _RESOLUTIONS[key] = (now, resolved)
        while len(_RESOLUTIONS) > RESOLUTION_CACHE_SIZE:
            _RESOLUTIONS.popitem(last=False)
        return resolved

    @staticmethod
    def _apply_resolution(body: Dict[str, Any], resolved: Optional[ResolvedSlice]) -> Dict[str, Any]:
        """Let trace-resolved callers/targets override attribute-derived runtime fields."""
        if resolved is None or not resolved.resolutions:
            return body
        runtime = body["runtime_mappings"]
        callers = {**resolved.callers(), **resolved.target_callers()}
        targets = resolved.targets()
        skipped = resolved.skipped()
        if "topology.caller" in runtime and callers:
            script = runtime["topology.caller"]["script"]
            runtime["topology.caller"] = {"type": "keyword", "script": {
                "source": _DOC_ID + (
                    "if (__id != null && params['callers'].containsKey(__id)) { "
                    "String __c=params['callers'][__id]; if (__c.length() > 0) emit(__c); return; } "
                ) + script["source"],
                "params": {"callers": callers},
            }}
        if targets:
            if "topology.target" in runtime:
                script = runtime["topology.target"]["script"]
                runtime["topology.target"] = {"type": "keyword", "script": {
                    "source": _DOC_ID + (
                        "if (__id != null && params['targets'].containsKey(__id)) { "
                        "emit(params['targets'][__id]); return; } "
                    ) + script["source"],
                    "params": {"targets": targets},
                }}
            if "topology.metric_operation" in runtime:
                script = runtime["topology.metric_operation"]["script"]
                anchor = "def target=s['target_service']; "
                runtime["topology.metric_operation"] = {"type": "keyword", "script": {
                    "source": script["source"].replace(anchor, anchor + _DOC_ID + (
                        "if (__id != null && params['targets'].containsKey(__id)) target=params['targets'][__id]; "
                    ), 1),
                    "params": {"targets": targets},
                }}
        if skipped:
            runtime["topology.trace_skip"] = {"type": "boolean", "script": {
                "source": _DOC_ID + "emit(__id != null && params['skip'].containsKey(__id));",
                "params": {"skip": skipped},
            }}
            body["query"]["bool"]["must_not"] = [{"term": {"topology.trace_skip": True}}]
        return body

    @staticmethod
    def _slices(start_ms: int, end_ms: int, after_key: Optional[Dict[str, Any]]):
        """Yield (slice_start, slice_end, composite_after) aligned to five-minute buckets."""
        cursor, inner = start_ms, None
        if after_key and "slice_start_ms" in after_key:
            cursor = max(start_ms, int(after_key["slice_start_ms"]))
            inner = after_key.get("after")
        while cursor < end_ms:
            slice_end = ((cursor + SLICE_MS) // SLICE_ALIGN_MS) * SLICE_ALIGN_MS
            slice_end = min(end_ms, slice_end if slice_end > cursor else cursor + SLICE_MS)
            yield cursor, slice_end, inner
            cursor, inner = slice_end, None

    def _clear(self, table: str, start_ms: int, end_ms: int, bucket_size: Optional[int] = None) -> None:
        """Remove a recent slice's rows before rewriting them with resolved callers."""
        if end_ms < time.time() * 1000 - RECLEAR_RECENT_MS:
            return
        where = "bucket_start >= {start:Int64} AND bucket_start < {end:Int64}"
        params: Dict[str, Any] = {"start": start_ms // 1000, "end": end_ms // 1000}
        if bucket_size is not None:
            where += " AND bucket_size = {size:UInt32}"
            params["size"] = bucket_size
        with get_connection(self.db_path) as db:
            if hasattr(db, "client") and hasattr(db.client, "command"):
                # Lightweight delete masks rows instead of rewriting whole parts.
                db.client.command(f"DELETE FROM {table} WHERE {where}", parameters=params)
            else:
                sql = f"DELETE FROM {table} WHERE bucket_start >= ? AND bucket_start < ?"
                args: List[Any] = [params["start"], params["end"]]
                if bucket_size is not None:
                    sql += " AND bucket_size = ?"
                    args.append(bucket_size)
                db.execute(sql, tuple(args))

    def earliest_timestamp_ms(self) -> Optional[int]:
        """Oldest retained transaction timestamp, or None when the index is empty."""
        if not self.url:
            return None
        with self._client() as client:
            response = client.post(f"/{self.source_index}/_search", json={
                "size": 0, "track_total_hits": False,
                "query": {"term": {"processor.event": "transaction"}},
                "aggs": {"oldest": {"min": {"field": "@timestamp"}}},
            })
        if response.status_code != 200:
            raise RuntimeError(f"ELK retention probe failed: HTTP {response.status_code}")
        value = ((response.json().get("aggregations") or {}).get("oldest") or {}).get("value")
        return int(value) if value is not None else None

    def delete_ip_window(self, start_ms: int, end_ms: int) -> None:
        """Remove five-minute IP rollups in a range before a full rematerialization."""
        if end_ms <= start_ms:
            return
        with get_connection(self.db_path) as db:
            db.execute(
                "DELETE FROM topology_principal_ip_5m WHERE bucket_start >= ? AND bucket_start < ?",
                (start_ms // 1000, end_ms // 1000),
            )

    def _run_sliced(self, start_ms: int, end_ms: int, after_key: Optional[Dict[str, Any]],
                    max_pages: int, request, handle, clear=None) -> Dict[str, Any]:
        """Page composite aggregations slice by slice with a resumable cursor."""
        saved = 0
        pages = 0
        with self._client() as client:
            for slice_start, slice_end, inner in self._slices(start_ms, end_ms, after_key):
                resolved = self._resolve(client, slice_start, slice_end)
                if inner is None and clear is not None and pages < max_pages:
                    clear(slice_start, slice_end)
                while True:
                    if pages >= max_pages:
                        return {"saved": saved, "pages": pages, "complete": False,
                                "after_key": {"slice_start_ms": slice_start, "after": inner}}
                    body = self._apply_resolution(request(slice_start, slice_end, inner), resolved)
                    response = client.post(f"/{self.source_index}/_search", json=body)
                    aggregation, count = handle(response)
                    pages += 1
                    saved += count
                    buckets = aggregation.get("buckets") or []
                    inner = aggregation.get("after_key")
                    if not buckets or len(buckets) < PAGE_SIZE or not inner:
                        break
        return {"saved": saved, "pages": pages, "complete": True, "after_key": None}

    @staticmethod
    def _query(start_ms: int, end_ms: int, bucket_size: int, after_key: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        runtime = InteractiveTopologyRepository._es_runtime()
        runtime["topology.metric_operation"] = {"type": "keyword", "script": {"source": (
            "def s=params['_source']; def target=s['target_service']; "
            "if (target == null) { def svc=s['service']; if (svc instanceof Map) target=svc['name']; } "
            "def v=s['operation_key']; if (v == null || v.toString().length() == 0 || v.toString() == 'unknown') { "
            "def t=s['transaction']; if (t instanceof Map) v=t['name']; } "
            "if (v == null) v=s['name']; if (v != null) { String op=v.toString().trim(); "
            "op=op.replaceAll(/\\/[0-9a-fA-F-]{16,}/, m -> '/{id}'); op=op.replaceAll(/\\/[0-9]+/, m -> '/{id}'); "
            "if (op.length() > 0) emit(op); "
            "else if (target != null && target.toString() != 'unknown') emit(target.toString() + '/unknown'); "
            "else emit('unknown'); } "
            "else if (target != null && target.toString() != 'unknown') emit(target.toString() + '/unknown'); "
            "else emit('unknown');"
        )}}
        fields = (
            "topology.caller", "topology.target", "topology.api",
            "topology.metric_operation",
            "topology.principal", "topology.duration_ms",
            "topology.request_bytes", "topology.response_bytes",
        )
        composite: Dict[str, Any] = {
            "size": PAGE_SIZE,
            "sources": [
                {"bucket_start_ms": {"date_histogram": {"field": "@timestamp", "fixed_interval": f"{bucket_size}s"}}},
                {"caller": {"terms": {"field": "topology.caller", "missing_bucket": True}}},
                {"service": {"terms": {"field": "topology.target", "missing_bucket": True}}},
                {"principal": {"terms": {"field": "topology.principal", "missing_bucket": True}}},
                {"operation": {"terms": {"field": "topology.metric_operation", "missing_bucket": True}}},
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
                "request_bytes": {"sum": {"field": "topology.request_bytes"}},
                "response_bytes": {"sum": {"field": "topology.response_bytes"}},
                "request_bytes_samples": {"value_count": {"field": "topology.request_bytes"}},
                "response_bytes_samples": {"value_count": {"field": "topology.response_bytes"}},
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
        target = str(key.get("service") or "unknown").strip()[:200] or "unknown"
        caller = str(key.get("caller") or "").strip()[:200]
        if caller.lower() in ("unknown", "-anonymous-") or caller == target:
            caller = ""
        return MetricBucket(
            bucket_start=int(key.get("bucket_start_ms") or 0) // 1000,
            bucket_size=bucket_size,
            caller_service=caller,
            target_service=target,
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
            request_bytes=max(0, int(_finite((source.get("request_bytes") or {}).get("value")))),
            response_bytes=max(0, int(_finite((source.get("response_bytes") or {}).get("value")))),
            request_bytes_samples=max(0, int(_finite((source.get("request_bytes_samples") or {}).get("value")))),
            response_bytes_samples=max(0, int(_finite((source.get("response_bytes_samples") or {}).get("value")))),
        )

    def materialize_window(
        self, start_ms: int, end_ms: int, bucket_size: int,
        after_key: Optional[Dict[str, Any]] = None, max_pages: int = MAX_PAGES_PER_CYCLE,
    ) -> Dict[str, Any]:
        if bucket_size not in (60, 300):
            raise ValueError("bucket_size must be 60 or 300 seconds")
        if not self.url or end_ms <= start_ms:
            return {"buckets": 0, "pages": 0, "complete": True, "after_key": None}

        def handle(response):
            if response.status_code != 200:
                raise RuntimeError(f"ELK metric aggregation failed: HTTP {response.status_code}")
            aggregation = (response.json().get("aggregations") or {}).get("buckets") or {}
            buckets = aggregation.get("buckets") or []
            if buckets:
                AggregateRepository(self.db_path).save_buckets(
                    [self._bucket(bucket, bucket_size) for bucket in buckets]
                )
            return aggregation, len(buckets)

        result = self._run_sliced(
            start_ms, end_ms, after_key, max_pages,
            lambda s, e, after: self._query(s, e, bucket_size, after), handle,
            lambda s, e: self._clear("metric_buckets", s, e, bucket_size),
        )
        return {"buckets": result["saved"], "pages": result["pages"],
                "complete": result["complete"], "after_key": result["after_key"],
                "edge_resolution": dict(self.edge_stats)}

    @staticmethod
    def _ip_query(start_ms: int, end_ms: int, after_key: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        runtime = InteractiveTopologyRepository._es_runtime()
        fields = (
            "topology.caller", "topology.target", "topology.api",
            "topology.principal", "topology.source_ip", "topology.duration_ms",
            "topology.request_bytes", "topology.response_bytes",
        )
        composite: Dict[str, Any] = {
            "size": PAGE_SIZE,
            "sources": [
                {"bucket_start_ms": {"date_histogram": {"field": "@timestamp", "fixed_interval": "300s"}}},
                {"source_ip": {"terms": {"field": "topology.source_ip", "missing_bucket": False}}},
                {"service": {"terms": {"field": "topology.target", "missing_bucket": True}}},
                {"api": {"terms": {"field": "topology.api", "missing_bucket": True}}},
                {"caller_service": {"terms": {"field": "topology.caller", "missing_bucket": True}}},
                {"principal": {"terms": {"field": "topology.principal", "missing_bucket": True}}},
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
            "aggs": {"ips": {"composite": composite, "aggs": {
                "p95_latency": {"percentiles": {"field": "topology.duration_ms", "percents": [95]}},
                "request_bytes": {"sum": {"field": "topology.request_bytes"}},
                "response_bytes": {"sum": {"field": "topology.response_bytes"}},
                "errors": {"filter": {"bool": {"should": [
                    {"range": {"http.response.status_code": {"gte": 400}}},
                    {"range": {"http_status": {"gte": 400}}},
                    {"term": {"event.outcome": "failure"}},
                ], "minimum_should_match": 1}}},
                "http_4xx": {"filter": {"bool": {"should": [
                    {"range": {"http.response.status_code": {"gte": 400, "lt": 500}}},
                    {"range": {"http_status": {"gte": 400, "lt": 500}}},
                ], "minimum_should_match": 1}}},
                "http_5xx": {"filter": {"bool": {"should": [
                    {"range": {"http.response.status_code": {"gte": 500}}},
                    {"range": {"http_status": {"gte": 500}}},
                ], "minimum_should_match": 1}}},
                "auth_failures": {"filter": {"bool": {"should": [
                    {"term": {"http.response.status_code": 401}},
                    {"term": {"http.response.status_code": 403}},
                    {"term": {"http_status": 401}},
                    {"term": {"http_status": 403}},
                ], "minimum_should_match": 1}}},
            }}},
        }

    def _ip_row(
        self, bucket: Dict[str, Any], start_ms: int, end_ms: int,
        prior_ips: set[Tuple[str, str]], now_ms: int,
    ) -> Optional[List[Any]]:
        key = bucket.get("key") or {}
        source_ip = str(key.get("source_ip") or "").strip()
        if not source_ip or source_ip.lower() in ("unavailable", "unknown", "none"):
            return None
        bucket_start = (int(key.get("bucket_start_ms") or start_ms) // 300000) * 300
        service = canonical_service(key.get("service") or "unknown")
        raw_api = str(key.get("api") or "unknown")
        api = canonical_api(raw_api, service)
        caller = str(key.get("caller_service") or "").strip()[:200]
        if caller.lower() in ("unknown", "-anonymous-") or caller == service:
            caller = ""
        principal = canonical_principal(key.get("principal"))
        requests = int(bucket.get("doc_count") or 0)
        errors = int((bucket.get("errors") or {}).get("doc_count") or 0)
        auth_failures = int((bucket.get("auth_failures") or {}).get("doc_count") or 0)
        http_4xx = int((bucket.get("http_4xx") or {}).get("doc_count") or 0)
        http_5xx = int((bucket.get("http_5xx") or {}).get("doc_count") or 0)
        p95 = _finite((bucket.get("p95_latency") or {}).get("values", {}).get("95.0"))
        req_bytes = max(0, int(_finite((bucket.get("request_bytes") or {}).get("value"))))
        resp_bytes = max(0, int(_finite((bucket.get("response_bytes") or {}).get("value"))))
        first_seen_ms = int(key.get("bucket_start_ms") or start_ms)
        last_seen_ms = min(end_ms, first_seen_ms + 300000)
        role, label, confidence = classify_source_ip_role(source_ip)
        is_lb = 1 if role in ("load_balancer", "reverse_proxy", "nat_gateway") else 0
        is_new = 0 if (principal, source_ip) in prior_ips else 1

        return [
            bucket_start, principal, source_ip[:100], service, api, caller,
            requests, errors, auth_failures, http_4xx, http_5xx, 0,
            p95, req_bytes, resp_bytes, first_seen_ms, last_seen_ms,
            is_lb, role, label, confidence, is_new, now_ms,
        ]

    def materialize_ip_window(
        self, start_ms: int, end_ms: int,
        after_key: Optional[Dict[str, Any]] = None, max_pages: int = MAX_PAGES_PER_CYCLE,
    ) -> Dict[str, Any]:
        if not self.url or end_ms <= start_ms:
            return {"rows": 0, "pages": 0, "complete": True, "after_key": None}

        prior_ips: set[Tuple[str, str]] = set()
        with get_connection(self.db_path) as db:
            try:
                prior_rows = db.execute(
                    "SELECT DISTINCT principal, source_ip FROM topology_principal_ip_5m FINAL WHERE bucket_start < ?",
                    (start_ms // 1000,),
                ).fetchall()
                prior_ips = {(str(r[0]), str(r[1])) for r in prior_rows}
            except Exception:
                pass

        now_ms = int(time.time() * 1000)
        cols = [
            "bucket_start", "principal", "source_ip", "service", "api", "caller_service",
            "request_count", "error_count", "auth_failure_count", "http_4xx_count",
            "http_5xx_count", "timeout_count", "p95_latency_ms", "request_bytes",
            "response_bytes", "first_seen_ms", "last_seen_ms", "is_load_balancer",
            "source_ip_role", "role_label", "attribution_confidence", "is_new_ip",
            "updated_at_ms",
        ]

        def handle(response):
            if response.status_code != 200:
                raise RuntimeError(f"ELK IP metric aggregation failed: HTTP {response.status_code}")
            aggregation = (response.json().get("aggregations") or {}).get("ips") or {}
            rows_to_save = []
            for b in aggregation.get("buckets") or []:
                row = self._ip_row(b, start_ms, end_ms, prior_ips, now_ms)
                if row:
                    rows_to_save.append(row)
            if rows_to_save:
                with get_connection(self.db_path) as db:
                    if hasattr(db, "client") and hasattr(db.client, "insert"):
                        db.client.insert("topology_principal_ip_5m", rows_to_save, column_names=cols)
                        db.client.insert("topology_principal_ip_current", rows_to_save, column_names=cols)
                    else:
                        placeholders = ",".join("?" for _ in cols)
                        db.executemany(f"INSERT INTO topology_principal_ip_5m ({','.join(cols)}) VALUES ({placeholders})", rows_to_save)
                        db.executemany(f"INSERT INTO topology_principal_ip_current ({','.join(cols)}) VALUES ({placeholders})", rows_to_save)
            return aggregation, len(rows_to_save)

        result = self._run_sliced(
            start_ms, end_ms, after_key, max_pages, self._ip_query, handle,
            lambda s, e: self._clear("topology_principal_ip_5m", s, e),
        )
        return {"rows": result["saved"], "pages": result["pages"],
                "complete": result["complete"], "after_key": result["after_key"]}
