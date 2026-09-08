"""Elasticsearch APM 7.x / ECS transaction ingestion parser.

Accepts Elasticsearch hit documents (_source + optional fields), hit arrays,
search responses {"hits":{"hits":[...]}}, {"documents":[...]}, and NDJSON.
Only transaction documents are ingested into request traces.

SECURITY LAW:
Authorization headers, tokens, and raw passwords are never persisted.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.app.models.trace import NormalizedTrace
from backend.app.services.otlp_parser import decompress_payload, resolve_auth

log = logging.getLogger("tracescope-hub")


def _dig(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return _scalar(value[0]) if value else None
    if isinstance(value, dict):
        for key in ("value", "stringValue", "string_value"):
            if key in value:
                return _scalar(value[key])
        return None
    return value


def _first(source: dict, fields: dict, *paths: str) -> Any:
    for path in paths:
        value = _scalar(_dig(source, path))
        if value not in (None, ""):
            return value
        value = _scalar(fields.get(path)) if isinstance(fields, dict) else None
        if value not in (None, ""):
            return value
    return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _timestamp(source: dict, fields: dict) -> Tuple[int, int]:
    ts_us = _to_int(_first(source, fields, "timestamp.us"))
    if ts_us is not None and ts_us > 0:
        return int(ts_us // 1000), ts_us
    raw = _first(source, fields, "@timestamp", "timestamp", "event.created", "event.ingested")
    if raw:
        try:
            text = str(raw).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            seconds = parsed.timestamp()
            return int(seconds * 1000), int(seconds * 1000000)
        except (TypeError, ValueError, OverflowError):
            pass
    now = int(time.time() * 1000)
    return now, now * 1000


def extract_apm_documents(payload: Any) -> List[Dict[str, Any]]:
    """Flatten supported JSON envelopes into Elasticsearch hit dictionaries."""
    if isinstance(payload, list):
        result = []
        for item in payload:
            result.extend(extract_apm_documents(item))
        return result
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("documents"), list):
        return extract_apm_documents(payload["documents"])
    hits = payload.get("hits")
    if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
        return extract_apm_documents(hits["hits"])
    if "_source" in payload or "processor" in payload or "transaction" in payload:
        return [payload]
    return []


def parse_apm_body(body_bytes: bytes, content_type: str = "application/json") -> List[Dict[str, Any]]:
    decompressed = decompress_payload(body_bytes)
    text = decompressed.decode("utf-8", "replace")
    if "ndjson" in str(content_type).lower() or ("\n" in text and text.strip().startswith("{")):
        documents = []
        for line in text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            try:
                documents.extend(extract_apm_documents(json.loads(line_str)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if documents:
            return documents
    try:
        return extract_apm_documents(json.loads(text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def apm_document_to_normalized_trace(document: Dict[str, Any]) -> Optional[NormalizedTrace]:
    """Map one Elasticsearch APM transaction hit to a NormalizedTrace."""
    if not isinstance(document, dict):
        return None
    source = document.get("_source") if isinstance(document.get("_source"), dict) else document
    fields = document.get("fields") if isinstance(document.get("fields"), dict) else {}

    raw_processor_event = _first(source, fields, "processor.event")
    raw_processor_name = _first(source, fields, "processor.name")
    processor_event = str(raw_processor_event).lower() if raw_processor_event else None
    processor_name = str(raw_processor_name).lower() if raw_processor_name else None
    if ((processor_event and processor_event != "transaction") or
            (not processor_event and processor_name and processor_name != "transaction")):
        return None  # ignore span or metric documents to avoid double-counting

    timestamp_ms, timestamp_us = _timestamp(source, fields)
    service_name = str(_first(source, fields, "service.name", "resource.service.name") or "unknown-service")[:200]
    service_instance = str(_first(source, fields, "service.node.name", "host.name", "host.hostname") or "")[:200] or None
    environment = str(_first(source, fields, "service.environment", "environment") or "production")[:100]

    # Identity extraction
    principal_name = "unknown"
    auth_scheme = None
    explicit_user = _first(source, fields, "user.id", "user.name", "user.username", "user.email", "context.user.username", "context.user.id", "context.user.name", "enduser.id", "labels.principal", "account.username")
    if explicit_user:
        principal_name = str(explicit_user).strip()[:200]
    else:
        auth_header = _first(source, fields, "http.request.headers.authorization", "http.request.header.authorization", "context.request.headers.authorization", "context.request.headers.Authorization", "labels.authorization")
        if auth_header:
            principal_name, auth_scheme = resolve_auth(str(auth_header))

    transaction_name = _first(source, fields, "transaction.name")
    http_route = _first(source, fields, "labels.http_route", "http.route")
    url_path = _first(source, fields, "url.path", "url.original", "context.request.url.pathname", "context.request.url.path")
    operation = str(transaction_name or http_route or url_path or "unknown-operation")[:500]

    method = str(_first(source, fields, "http.request.method", "http.method", "context.request.method") or "GET")[:20].upper()

    duration_us_raw = _to_float(_first(source, fields, "transaction.duration.us", "duration_us"))
    duration_us = max(0, int(duration_us_raw or 0))
    duration_ms = round(duration_us / 1000.0, 3)

    status_code = _to_int(_first(source, fields, "http.response.status_code", "http.status_code", "context.response.status_code"))
    transaction_result = _first(source, fields, "transaction.result")
    if status_code is None and transaction_result:
        match = re.search(r"\b([1-5])xx\b", str(transaction_result), re.I)
        if match:
            status_code = int(match.group(1)) * 100
    outcome = str(_first(source, fields, "event.outcome") or "unknown").lower()
    if status_code is None and outcome == "failure":
        status_code = 500

    status_class = "unknown"
    if status_code:
        if status_code >= 500: status_class = "5xx"
        elif status_code >= 400: status_class = "4xx"
        elif status_code >= 300: status_class = "3xx"
        elif status_code >= 200: status_class = "2xx"

    if outcome == "unknown":
        if status_code and status_code >= 400: outcome = "failure"
        elif status_code and status_code < 400: outcome = "success"

    trace_id = str(_first(source, fields, "trace.id", "trace_id") or "").lower()
    span_id = str(_first(source, fields, "transaction.id", "span.id", "span_id", "id") or document.get("_id") or document.get("id") or "").lower()
    if not span_id and trace_id:
        span_id = trace_id[-16:]
    parent_span_id = str(_first(source, fields, "parent.id", "transaction.parent_id", "parent_span_id") or "").lower() or None
    if not trace_id or not span_id:
        return None

    client_ip = str(_first(source, fields, "client.ip", "source.ip", "network.peer.address") or "")[:100] or None
    caller = _first(source, fields, "labels.net_sock_peer_addr", "labels.caller_service", "network.peer.address")
    caller_service = str(caller)[:200] if caller and not any(c.isdigit() for c in str(caller).split(".")) else None
    dst_ip = str(_first(source, fields, "labels.net_sock_host_addr", "server.address", "dst_ip") or "")[:250] or None
    dst_port = _to_int(_first(source, fields, "labels.net_sock_host_port", "server.port", "dst_port"))

    peer_service = _first(source, fields, "destination.service.name", "span.destination.service.resource", "labels.peer_service")
    target_service = service_name

    labels = source.get("labels") if isinstance(source.get("labels"), dict) else {}
    extra: Dict[str, Any] = {}
    if auth_scheme: extra["auth_scheme"] = auth_scheme
    for k, tgt in [
        ("labels.service_group_id", "service_group_id"),
        ("labels.service_module_id", "service_module_id"),
        ("user_agent.original", "user_agent"),
        ("labels.user_agent_original", "user_agent"),
        ("url.full", "url_full"),
        ("transaction.result", "transaction_result"),
        ("agent.name", "agent_name"),
        ("agent.version", "agent_version"),
    ]:
        v = _first(source, fields, k)
        if v is not None: extra[tgt] = str(v)[:300]

    attributes_json = json.dumps(extra, separators=(',', ':')) if extra else None

    return NormalizedTrace(
        event_uid=document.get("_id") or f"{trace_id}:{span_id}",
        timestamp=int(timestamp_ms // 1000),
        timestamp_ms=timestamp_ms,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        service_name=service_name,
        service_instance=service_instance,
        service_environment=environment,
        caller_service=caller_service,
        caller_instance=None,
        caller_ip=client_ip,
        target_service=target_service,
        target_instance=service_instance,
        target_ip=dst_ip,
        target_port=dst_port,
        principal_name=principal_name,
        operation=operation,
        http_method=method,
        http_route=str(http_route)[:500] if http_route else None,
        http_status=status_code,
        status_class=status_class,
        duration_ms=duration_ms,
        duration_us=duration_us,
        outcome=outcome,
        protocol="http",
        span_kind="server",
        attributes_json=attributes_json,
        created_at=int(time.time() * 1000)
    )
