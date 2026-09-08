from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any, Optional

from backend.app.models.trace import NormalizedTrace
from backend.app.services.wsse import (
    SOAP_BODY_ATTRIBUTES,
    WSSE_USERNAME_ATTRIBUTES,
    extract_wsse_username,
    normalize_wsse_username,
)


def _is_networktracing_event(document: dict[str, Any]) -> bool:
    """Return True for the compact event contract emitted by NetworkTracing agents."""
    return (
        document.get("src") == "pcap"
        or str(document.get("source_probe", "")).startswith("pcap-")
        or ("caller" in document and "dst_ip" in document and "path" in document)
    )


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default

def parse_timestamp(value: Any) -> int:
    if value is None:
        return int(time.time() * 1000)
    if isinstance(value, (int, float)):
        if value > 1_000_000_000_000_000:
            return int(value / 1_000_000)
        return int(value if value > 10_000_000_000 else value * 1000)
    try:
        val_int = int(value)
        if val_int > 1_000_000_000_000_000:
            return int(val_int / 1_000_000)
        return int(val_int if val_int > 10_000_000_000 else val_int * 1000)
    except (ValueError, TypeError):
        pass
    text = str(value).replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)

def extract_principal(auth_header: Any, fallback_user: Any = None) -> str:
    if isinstance(auth_header, list):
        auth_header = auth_header[0] if auth_header else None
    if isinstance(auth_header, str) and auth_header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth_header.split(None, 1)[1], validate=True).decode("utf-8")
            username, sep, _pwd = decoded.partition(":")
            if sep and username.strip():
                return username.strip()[:200]
        except Exception:
            pass
    # NOTE: Non-header identity extraction commented out for now (will be implemented later)
    # if fallback_user:
    #     if isinstance(fallback_user, list) and fallback_user:
    #         fallback_user = fallback_user[0]
    #     s = str(fallback_user).strip()
    #     if s:
    #         return s[:200]
    return "unknown"

def _extract_attributes(document: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    resource = document.get("resource")
    if isinstance(resource, dict):
        res_attrs = resource.get("attributes", {})
        if isinstance(res_attrs, list):
            for item in res_attrs:
                if isinstance(item, dict) and "key" in item:
                    raw = item.get("value")
                    if isinstance(raw, dict) and raw: raw = next(iter(raw.values()))
                    result[item["key"]] = raw
        elif isinstance(res_attrs, dict):
            result.update(res_attrs)
    attributes = document.get("attributes", {})
    if isinstance(attributes, list):
        for item in attributes:
            if isinstance(item, dict) and "key" in item:
                raw = item.get("value")
                if isinstance(raw, dict) and raw: raw = next(iter(raw.values()))
                result[item["key"]] = raw
    elif isinstance(attributes, dict):
        result.update(attributes)
    return result

def get_field(document: dict[str, Any], path: str, attrs: dict[str, Any], default: Any = None) -> Any:
    if path in document:
        val = document[path]
    else:
        val = document
        for part in path.split("."):
            if not isinstance(val, dict) or part not in val:
                val = None
                break
            val = val[part]
    if val is not None:
        if isinstance(val, list) and len(val) == 1:
            return val[0]
        return val
    if path in attrs:
        return attrs[path]
    return default

def normalize_otel_record(raw: dict[str, Any], source_label: str = "import") -> Optional[NormalizedTrace]:
    source = raw.get("_source") if isinstance(raw.get("_source"), dict) else raw.get("fields") if isinstance(raw.get("fields"), dict) else raw
    if not isinstance(source, dict):
        return None

    attrs = _extract_attributes(source)
    is_network_event = _is_networktracing_event(source)

    def pick(first: str, *alternates: str, default: Any = None) -> Any:
        v = get_field(source, first, attrs)
        if v is not None:
            return v
        for alt in alternates:
            v = get_field(source, alt, attrs)
            if v is not None:
                return v
        return default

    # Service & Instance
    service_name = str(pick("service.name", "resource.service.name", "serviceName", "service", default="unknown"))[:200]
    service_instance = str(pick("service.node.name", "host.name", "node.name", "service.instance.id", "host", default=""))[:200] or None
    environment = str(pick("service.environment", "environment", default="production"))[:100]

    # Operation
    operation = str(pick("transaction.name", "name", "path", default="unknown"))[:500]

    # Timestamps
    start_nano = pick("startTimeUnixNano", "start_time_unix_nano")
    if start_nano and not pick("@timestamp", "timestamp"):
        try:
            timestamp_ms = int(int(start_nano) / 1_000_000)
        except Exception:
            timestamp_ms = int(time.time() * 1000)
    else:
        timestamp_ms = parse_timestamp(pick("@timestamp", "timestamp", "startTimeUnixNano", "ts"))

    # Duration
    duration = pick("transaction.duration.us", "duration_us")
    if duration is None and pick("duration_ms") is not None:
        duration = _safe_number(pick("duration_ms")) * 1000
    if duration is None and pick("duration_nano") is not None:
        duration = int(pick("duration_nano")) / 1000
    if duration is None:
        end_nano = pick("endTimeUnixNano", "end_time_unix_nano")
        if start_nano is not None and end_nano is not None:
            try:
                duration = max(0, (int(end_nano) - int(start_nano)) / 1000)
            except Exception:
                duration = 0
    duration_us = max(0, int(_safe_number(duration)))
    duration_ms = round(duration_us / 1000.0, 3)

    # Identifiers
    traceparent = str(pick("traceparent", default=""))
    traceparent_parts = traceparent.split("-") if traceparent else []
    traceparent_trace_id = traceparent_parts[1] if len(traceparent_parts) == 4 else None
    traceparent_span_id = traceparent_parts[2] if len(traceparent_parts) == 4 else None
    identity_fields = (
        timestamp_ms, service_name, operation, pick("caller"), pick("caller_port"),
        pick("dst_ip"), pick("dst_port"), pick("status"), duration_us,
    )
    generated_id = hashlib.sha256(repr(identity_fields).encode()).hexdigest()
    trace_id = str(pick("trace.id", "trace_id", "traceId", default=traceparent_trace_id or generated_id[:32]))
    span_id = str(pick("transaction.id", "span.id", "span_id", "spanId", default=traceparent_span_id or generated_id[32:48]))
    parent_span_id = str(pick("parent.id", "parent_span_id", "parentSpanId", default="")) or None

    supplied_id = raw.get("_id") or pick("event.id")
    event_uid = str(supplied_id) if supplied_id else f"{trace_id}:{span_id}"

    # Status & Outcome
    status_raw = pick("http.response.status_code", "http.status_code", "status")
    try:
        http_status = int(status_raw) if status_raw is not None else None
    except Exception:
        http_status = None

    status_class = "unknown"
    if http_status:
        if http_status >= 500: status_class = "5xx"
        elif http_status >= 400: status_class = "4xx"
        elif http_status >= 300: status_class = "3xx"
        elif http_status >= 200: status_class = "2xx"

    outcome = str(pick("event.outcome", default="unknown"))[:30]
    if outcome == "unknown":
        status_code_name = str(pick("status.code", default="")).upper()
        if (http_status and http_status >= 400) or status_code_name == "STATUS_CODE_ERROR":
            outcome = "failure"
        elif (http_status and http_status < 400) or status_code_name == "STATUS_CODE_OK":
            outcome = "success"

    # Span Kind & Networking
    event_type = str(pick("processor.event", "event.type", default="transaction"))
    kind_raw = str(pick("span.kind", "span_kind", "kind", default="server" if event_type == "transaction" else "internal")).lower()
    if kind_raw in {"span_kind_server", "server"}: span_kind = "server"
    elif kind_raw in {"span_kind_client", "client", "producer"}: span_kind = "client"
    else: span_kind = "internal"

    peer_service = str(pick("peer.service.name", "peer.service", "destination.service.resource", "parent.service.name", "labels.caller_service", "labels.net_peer_service", "caller.service", "caller_service", default=""))[:200] or None
    peer_address = str(pick("labels.net_sock_peer_addr", "net.peer.name", "destination.address", "peer.address", default=""))[:250] or None
    host_address = str(pick("labels.net_sock_host_addr", "net.host.name", "server.address", "dst_ip", default=""))[:250] or None
    client_ip = str(pick("client.ip", "client.address", "source.ip", "caller", default=""))[:100] or None

    target_port = pick("url.port", "dst_port", default=None)
    try:
        target_port = int(target_port) if target_port else None
    except Exception:
        target_port = None

    # Caller and Target Services
    if span_kind == "client":
        caller_service = service_name
        target_service = peer_service or "unknown"
    else:
        caller_service = peer_service
        target_service = service_name

    # Principal extraction. Credential-bearing inputs are read only in memory and
    # are never copied into attributes_json.
    auth_header = pick("labels.http_request_header_authorization", "http.request.headers.authorization", "authorization")
    # Non-header user attributes will be implemented later:
    # fallback_user = pick("enduser.id", "user.name", "user.id", "account.username")
    principal_name = extract_principal(auth_header, fallback_user=None)
    auth_scheme = "basic" if principal_name != "unknown" else None
    if principal_name == "unknown":
        for key in WSSE_USERNAME_ATTRIBUTES:
            wsse_username = normalize_wsse_username(pick(key))
            if wsse_username:
                principal_name, auth_scheme = wsse_username, "wsse"
                break
    if principal_name == "unknown":
        for key in SOAP_BODY_ATTRIBUTES:
            wsse_username = extract_wsse_username(pick(key))
            if wsse_username:
                principal_name, auth_scheme = wsse_username, "wsse"
                break
    # Legacy agents have already decoded Basic auth and emit only the username.
    if principal_name == "unknown" and is_network_event:
        legacy_user = pick("user")
        if legacy_user is not None and str(legacy_user).strip():
            principal_name = str(legacy_user).strip()[:200]
            supplied_scheme = str(pick("scheme", default="")).strip().lower()
            auth_scheme = supplied_scheme if supplied_scheme in {"basic", "wsse"} else None

    # Secondary / Contextual Attributes
    extra: dict[str, Any] = {}
    for key, tgt in [
        ("labels.user_agent_original", "user_agent"),
        ("labels.http_route", "http_route"),
        ("labels.thread_name", "thread_name"),
        ("service.framework.name", "framework_name"),
        ("service.framework.version", "framework_version"),
        ("service.runtime.name", "runtime_name"),
        ("service.runtime.version", "runtime_version"),
        ("agent.name", "agent_name"),
        ("agent.version", "agent_version"),
        ("host.os.full", "host_os"),
        ("url.original", "url_original"),
        ("url.query", "url_query"),
        ("transaction.result", "transaction_result"),
        ("labels.service_group_id", "service_group_id"),
        ("labels.service_module_id", "service_module_id"),
        ("user_agent", "user_agent"),
        ("source_probe", "source_probe"),
        ("src", "capture_source"),
        ("x_forwarded_for", "x_forwarded_for"),
        ("traceparent", "traceparent"),
    ]:
        v = pick(key)
        if v is not None:
            extra[tgt] = str(v)[:300]

    if auth_scheme:
        extra["auth_scheme"] = auth_scheme

    for key, tgt in [
        ("labels.http_request_content_length", "request_bytes"),
        ("labels.http_response_content_length", "response_bytes"),
        ("labels.net_sock_peer_port", "peer_port"),
        ("labels.thread_id", "thread_id"),
        ("process.pid", "process_pid"),
        ("req_bytes", "request_bytes"),
        ("resp_bytes", "response_bytes"),
        ("caller_port", "peer_port"),
    ]:
        v = pick(key)
        if v is not None:
            try: extra[tgt] = int(v)
            except Exception: pass

    attributes_json = json.dumps(extra, separators=(',', ':')) if extra else None

    return NormalizedTrace(
        event_uid=event_uid,
        timestamp=int(timestamp_ms / 1000),
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
        target_ip=host_address,
        target_port=target_port,
        principal_name=principal_name,
        operation=operation,
        http_method=str(pick("http.request.method", "http.method", "method", default=""))[:20] or None,
        http_route=extra.get("http_route") or (operation if is_network_event and operation != "unknown" else None),
        http_status=http_status,
        status_class=status_class,
        duration_ms=duration_ms,
        duration_us=duration_us,
        outcome=outcome,
        protocol=str(pick("labels.net_protocol_name", default="http")),
        span_kind=span_kind,
        attributes_json=attributes_json,
        created_at=int(time.time() * 1000),
    )
