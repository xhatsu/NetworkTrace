"""Elasticsearch / ELK trace repository for querying traces when deployed in ELK environments.

Downstream analytics and user interfaces transparently read trace data from
Elasticsearch when configured, allowing seamless transition from self-hosted
testbeds to production ELK clusters where trace data is stored.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from backend.config import settings
from backend.app.services.normalization import normalize_otel_record

log = logging.getLogger("tracescope-elk")


class ElasticsearchTraceRepository:
    def __init__(self):
        self.url = settings.elasticsearch_url
        self.index = settings.elasticsearch_index
        self.api_key = settings.elasticsearch_api_key
        self.user = settings.elasticsearch_user
        self.password = settings.elasticsearch_password
        self.verify_tls = settings.elasticsearch_verify_tls
        self.timeout = settings.elasticsearch_timeout

    def is_configured(self) -> bool:
        """Return True if Elasticsearch storage backend is configured."""
        if settings.trace_storage_backend in ("elasticsearch", "elk"):
            return True
        return bool(self.url or settings.elasticsearch_url)

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        return headers

    def _get_auth(self) -> Optional[tuple[str, str]]:
        if not self.api_key and self.user and self.password:
            return (self.user, self.password)
        return None

    def ping(self) -> bool:
        """Ping Elasticsearch cluster to test connectivity."""
        if not self.url:
            return False
        try:
            with httpx.Client(
                base_url=self.url,
                verify=self.verify_tls,
                timeout=5.0,
                headers=self._get_headers(),
                auth=self._get_auth(),
            ) as client:
                r = client.get("/")
                return r.status_code == 200
        except Exception as e:
            log.debug("Elasticsearch ping failed: %s", e)
            return False

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve spans for a specific trace_id from Elasticsearch."""
        if not self.url or not trace_id:
            return None

        query_body = {
            "size": 1000,
            "sort": [{"@timestamp": "asc"}],
            "query": {
                "bool": {
                    "should": [
                        {"term": {"trace.id": trace_id}},
                        {"term": {"trace_id": trace_id}},
                        {"term": {"traceId": trace_id}},
                        {"term": {"_id": trace_id}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }

        try:
            with httpx.Client(
                base_url=self.url,
                verify=self.verify_tls,
                timeout=self.timeout,
                headers=self._get_headers(),
                auth=self._get_auth(),
            ) as client:
                res = client.post(f"/{self.index}/_search", json=query_body)
                if res.status_code != 200:
                    log.warning("Elasticsearch returned HTTP %d for trace_id %s: %s", res.status_code, trace_id, res.text[:200])
                    return None

                hits = res.json().get("hits", {}).get("hits", [])
                if not hits:
                    return None

                spans = []
                for hit in hits:
                    norm = normalize_otel_record(hit)
                    if norm:
                        spans.append(norm.model_dump())
                    else:
                        src = hit.get("_source", {})
                        if src:
                            spans.append(src)

                return {
                    "trace_id": trace_id,
                    "spans": spans,
                    "count": len(spans),
                    "backend": "elasticsearch",
                }
        except Exception as e:
            log.warning("Elasticsearch query failed for trace_id %s: %s", trace_id, e)
            return None

    def list_traces(
        self,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        service: Optional[str] = None,
        caller: Optional[str] = None,
        target: Optional[str] = None,
        principal: Optional[str] = None,
        operation: Optional[str] = None,
        source_ip: Optional[str] = None,
        status: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Optional[List[Dict[str, Any]]]:
        """Search traces in Elasticsearch according to filter criteria."""
        if not self.url:
            return None

        filters: List[Dict[str, Any]] = [
            {
                "bool": {
                    "should": [
                        {"terms": {"processor.event": ["transaction", "span"]}},
                        {"exists": {"field": "trace.id"}},
                        {"exists": {"field": "trace_id"}},
                    ],
                    "minimum_should_match": 1,
                    "must_not": [
                        {"term": {"processor.event": "metric"}},
                        {"term": {"processor.name": "metric"}},
                    ],
                }
            }
        ]

        if start_ms is not None or end_ms is not None:
            time_range: Dict[str, Any] = {}
            if start_ms is not None:
                time_range["gte"] = start_ms
            if end_ms is not None:
                time_range["lt"] = end_ms
            filters.append({"range": {"@timestamp": time_range}})

        if trace_id:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"trace.id": trace_id}},
                        {"term": {"trace_id": trace_id}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if service:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"service.name": service}},
                        {"term": {"service_name": service}},
                        {"term": {"target_service": service}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if caller:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"caller_service": caller}},
                        {"term": {"caller": caller}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if target:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"target_service": target}},
                        {"term": {"service.name": target}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if principal:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"user.name": principal}},
                        {"term": {"principal_name": principal}},
                        {"term": {"principal_id": principal}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if operation:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"transaction.name": operation}},
                        {"term": {"operation": operation}},
                        {"term": {"name": operation}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if source_ip:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"client.ip": source_ip}},
                        {"term": {"caller_ip": source_ip}},
                        {"term": {"source_ip": source_ip}},
                        {"term": {"labels.client_address": source_ip}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if status:
            if status == "error":
                filters.append({
                    "bool": {
                        "should": [
                            {"range": {"http.response.status_code": {"gte": 400}}},
                            {"range": {"labels.http_response_status_code": {"gte": 400}}},
                            {"range": {"http_status": {"gte": 400}}},
                            {"term": {"outcome": "failure"}},
                            {"term": {"transaction.result": "HTTP 4xx"}},
                            {"term": {"transaction.result": "HTTP 5xx"}},
                        ],
                        "minimum_should_match": 1,
                    }
                })
            elif status.isdigit():
                code = int(status)
                filters.append({
                    "bool": {
                        "should": [
                            {"term": {"http.response.status_code": code}},
                            {"term": {"labels.http_response_status_code": code}},
                            {"term": {"labels.http_status_code": code}},
                            {"term": {"http_status": code}},
                        ],
                        "minimum_should_match": 1,
                    }
                })

        query_body = {
            "from": offset,
            "size": limit,
            "sort": [{"@timestamp": "desc"}],
            "query": {
                "bool": {
                    "filter": filters if filters else [{"match_all": {}}]
                }
            },
        }

        try:
            with httpx.Client(
                base_url=self.url,
                verify=self.verify_tls,
                timeout=self.timeout,
                headers=self._get_headers(),
                auth=self._get_auth(),
            ) as client:
                res = client.post(f"/{self.index}/_search", json=query_body)
                if res.status_code != 200:
                    log.warning("Elasticsearch list_traces HTTP %d: %s", res.status_code, res.text[:200])
                    return None

                hits = res.json().get("hits", {}).get("hits", [])
                results = []
                for hit in hits:
                    norm = normalize_otel_record(hit)
                    if norm:
                        results.append(norm.model_dump())
                    else:
                        src = hit.get("_source", {})
                        if src:
                            results.append(src)
                return results
        except Exception as e:
            log.warning("Elasticsearch list_traces request failed: %s", e)
            return None
