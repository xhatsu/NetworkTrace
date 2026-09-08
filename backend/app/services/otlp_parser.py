"""Canonical OpenTelemetry OTLP/HTTP receiver and Elastic APM 7.x parser.

Accepts OTLP/HTTP trace exports in application/json and application/x-protobuf
formats on POST /v1/traces, plus Elastic APM 7.x JSON/NDJSON on POST /api/ingest/apm.

SECURITY LAW:
Raw passwords and tokens are immediately discarded in-memory and NEVER stored or logged.
Zero external dependencies: 100% Python standard library.
"""
from __future__ import annotations

import base64
import gzip
import json
import logging
import re
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.app.models.trace import NormalizedTrace
from backend.app.services.wsse import (
    SOAP_BODY_ATTRIBUTES,
    WSSE_USERNAME_ATTRIBUTES,
    extract_wsse_username,
    normalize_wsse_username,
)

log = logging.getLogger("tracescope-hub")


def decompress_payload(raw_body: bytes, content_encoding: Optional[str] = None) -> bytes:
    """Decompress gzip payload if encoded or matching gzip magic bytes."""
    if not raw_body:
        return raw_body
    if (content_encoding and "gzip" in content_encoding.lower()) or raw_body.startswith(b"\x1f\x8b"):
        try:
            return gzip.decompress(raw_body)
        except Exception as exc:
            log.warning("gzip decompression failed: %s", exc)
    return raw_body


def _b64decode_clean(s: str) -> bytes:
    s = s.strip()
    p = len(s) % 4
    if p != 0:
        s += "=" * (4 - p)
    return base64.b64decode(s)


def resolve_auth(raw_header: Any) -> Tuple[str, Optional[str]]:
    """Resolve Authorization header to (username, scheme).
    
    SECURITY LAW:
    Raw passwords and tokens are immediately discarded and NEVER stored or logged.
    """
    if not raw_header:
        return "unknown", None
    if isinstance(raw_header, list):
        raw_header = raw_header[0] if raw_header else ""
    if not isinstance(raw_header, str):
        return "unknown", None

    val = raw_header.strip()
    if not val:
        return "unknown", None

    low = val.lower()

    # 1. Basic Auth: Basic <b64>
    if low.startswith("basic "):
        b64_part = val[6:].strip()
        try:
            raw = _b64decode_clean(b64_part)
            text = raw.decode("utf-8", "replace")
            username, sep, _pwd = text.partition(":")
            if sep and username.strip():
                return username.strip()[:200], "basic"
            if username.strip():
                return username.strip()[:200], "basic"
        except Exception:
            pass
        return "unknown", "basic"

    # 2. Bearer Auth: Bearer <token>
    if low.startswith("bearer "):
        token = val[7:].strip()
        # Check JWT payload claims for identity
        parts = token.split(".")
        if len(parts) == 3:
            try:
                urlb = parts[1].replace("-", "+").replace("_", "/")
                raw_payload = _b64decode_clean(urlb)
                claims = json.loads(raw_payload.decode("utf-8", "replace"))
                if isinstance(claims, dict):
                    for k in ("preferred_username", "username", "sub", "email", "client_id", "user_id"):
                        u = claims.get(k)
                        if u and isinstance(u, str):
                            return u.strip()[:200], "bearer"
            except Exception:
                pass
        return "unknown", "bearer"

    # 3. Digest Auth: Digest username="..."
    if low.startswith("digest "):
        try:
            i = low.find("username=")
            if i >= 0:
                rest = val[i + len("username="):].lstrip()
                if rest.startswith('"'):
                    j = rest.find('"', 1)
                    if j > 0:
                        u = rest[1:j].strip()[:200]
                        if u:
                            return u, "digest"
                else:
                    j = rest.find(",")
                    u = (rest if j < 0 else rest[:j]).strip().strip('"')[:200]
                    if u:
                        return u, "digest"
        except Exception:
            pass
        return "unknown", "digest"

    # 4. API Key Header
    if low.startswith("apikey "):
        return "unknown", "api-key"

    return "unknown", None


# =========================================================================
# Protobuf Wire-Format Decoder (Zero Dependencies)
# =========================================================================

def _decode_varint(buf: bytes, offset: int) -> Tuple[int, int]:
    res = 0
    shift = 0
    while True:
        if offset >= len(buf):
            raise ValueError("Truncated varint")
        b = buf[offset]
        offset += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
        if shift > 64:
            raise ValueError("Varint too long")
    return res, offset


def _decode_fields(buf: bytes) -> List[Tuple[int, int, Any]]:
    offset = 0
    fields = []
    buf_len = len(buf)
    while offset < buf_len:
        tag, offset = _decode_varint(buf, offset)
        wire_type = tag & 0x07
        field_num = tag >> 3
        if wire_type == 0:  # Varint
            val, offset = _decode_varint(buf, offset)
        elif wire_type == 1:  # 64-bit fixed
            if offset + 8 > buf_len:
                raise ValueError("Truncated 64-bit field")
            val = buf[offset:offset + 8]
            offset += 8
        elif wire_type == 2:  # Length-delimited
            length, offset = _decode_varint(buf, offset)
            if offset + length > buf_len:
                raise ValueError("Truncated length-delimited field")
            val = buf[offset:offset + length]
            offset += length
        elif wire_type == 5:  # 32-bit fixed
            if offset + 4 > buf_len:
                raise ValueError("Truncated 32-bit field")
            val = buf[offset:offset + 4]
            offset += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")
        fields.append((field_num, wire_type, val))
    return fields


def _decode_any_value(buf: bytes) -> Any:
    for field_num, wire_type, val in _decode_fields(buf):
        if field_num == 1:  # string_value
            return val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
        elif field_num == 2:  # bool_value
            return bool(val)
        elif field_num == 3:  # int_value
            return int(val)
        elif field_num == 4:  # double_value
            if isinstance(val, bytes) and len(val) == 8:
                return struct.unpack("<d", val)[0]
        elif field_num == 5:  # array_value
            arr = []
            for f_num, _, f_val in _decode_fields(val):
                if f_num == 1:
                    arr.append(_decode_any_value(f_val))
            return arr
        elif field_num == 6:  # kvlist_value
            kv = {}
            for f_num, _, f_val in _decode_fields(val):
                if f_num == 1:
                    k, v = _decode_key_value(f_val)
                    if k is not None:
                        kv[k] = v
            return kv
        elif field_num == 7:  # bytes_value
            return val
    return None


def _decode_key_value(buf: bytes) -> Tuple[Optional[str], Any]:
    key, value = None, None
    for field_num, _, val in _decode_fields(buf):
        if field_num == 1:
            key = val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
        elif field_num == 2:
            value = _decode_any_value(val)
    return key, value


def parse_otlp_protobuf(buf: bytes) -> List[Dict[str, Any]]:
    """Parse ExportTraceServiceRequest binary protobuf into span dicts."""
    spans = []
    for f1, _, rs_bytes in _decode_fields(buf):
        if f1 != 1:  # repeated ResourceSpans resource_spans = 1
            continue
        res_attrs = {}
        scope_spans_list = []
        for f2, _, val2 in _decode_fields(rs_bytes):
            if f2 == 1:  # Resource resource = 1
                for f3, _, kv_bytes in _decode_fields(val2):
                    if f3 == 1:  # repeated KeyValue attributes = 1
                        k, v = _decode_key_value(kv_bytes)
                        if k is not None:
                            res_attrs[k] = v
            elif f2 == 2:  # repeated ScopeSpans scope_spans = 2
                scope_spans_list.append(val2)

        for ss_bytes in scope_spans_list:
            for f4, _, val4 in _decode_fields(ss_bytes):
                if f4 == 2:  # repeated Span spans = 2
                    span: Dict[str, Any] = {
                        "resource_attributes": res_attrs,
                        "attributes": {},
                        "kind": 0,
                        "start_time_unix_nano": 0,
                        "end_time_unix_nano": 0,
                    }
                    for f5, w5, val5 in _decode_fields(val4):
                        if f5 == 1:  # trace_id
                            span["trace_id"] = val5.hex() if isinstance(val5, bytes) else str(val5)
                        elif f5 == 2:  # span_id
                            span["span_id"] = val5.hex() if isinstance(val5, bytes) else str(val5)
                        elif f5 == 4:  # parent_span_id
                            span["parent_span_id"] = val5.hex() if isinstance(val5, bytes) else str(val5)
                        elif f5 == 5:  # name
                            span["name"] = val5.decode("utf-8", "replace") if isinstance(val5, bytes) else str(val5)
                        elif f5 == 6:  # kind (SpanKind enum)
                            span["kind"] = int(val5)
                        elif f5 == 7:  # start_time_unix_nano
                            if w5 == 1 and isinstance(val5, bytes) and len(val5) == 8:
                                span["start_time_unix_nano"] = struct.unpack("<Q", val5)[0]
                            else:
                                span["start_time_unix_nano"] = int(val5)
                        elif f5 == 8:  # end_time_unix_nano
                            if w5 == 1 and isinstance(val5, bytes) and len(val5) == 8:
                                span["end_time_unix_nano"] = struct.unpack("<Q", val5)[0]
                            else:
                                span["end_time_unix_nano"] = int(val5)
                        elif f5 == 9:  # attributes
                            k, v = _decode_key_value(val5)
                            if k is not None:
                                span["attributes"][k] = v
                        elif f5 == 15:  # Status status
                            for f6, _, val6 in _decode_fields(val5):
                                if f6 == 2:
                                    span["status_message"] = val6.decode("utf-8", "replace") if isinstance(val6, bytes) else str(val6)
                                elif f6 == 3:
                                    span["status_code"] = int(val6)
                    spans.append(span)
    return spans


# =========================================================================
# OTLP JSON Parser
# =========================================================================

def _extract_json_attr_val(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, list):
        return [_extract_json_attr_val(item) for item in v]
    if isinstance(v, dict):
        for key in ("stringValue", "string_value", "intValue", "int_value", "boolValue", "bool_value", "doubleValue", "double_value"):
            if key in v:
                return _extract_json_attr_val(v[key])
        if "arrayValue" in v or "array_value" in v:
            vals = (v.get("arrayValue") or v.get("array_value") or {}).get("values", [])
            return [_extract_json_attr_val(x) for x in vals]
        if "kvlistValue" in v or "kvlist_value" in v:
            vals = (v.get("kvlistValue") or v.get("kvlist_value") or {}).get("values", [])
            return {x.get("key"): _extract_json_attr_val(x.get("value")) for x in vals if isinstance(x, dict)}
        if "bytesValue" in v or "bytes_value" in v:
            return v.get("bytesValue") or v.get("bytes_value")
        if len(v) == 1:
            return next(iter(v.values()))
    return v


def parse_otlp_json(data: dict) -> List[Dict[str, Any]]:
    """Parse OTLP JSON dictionary (supporting both camelCase and snake_case)."""
    spans = []
    rs_list = data.get("resourceSpans") or data.get("resource_spans") or []
    if not isinstance(rs_list, list):
        return spans

    for rs in rs_list:
        if not isinstance(rs, dict):
            continue
        res = rs.get("resource") or {}
        raw_res_attrs = res.get("attributes") or []
        res_attrs = {}
        if isinstance(raw_res_attrs, list):
            for a in raw_res_attrs:
                if isinstance(a, dict) and "key" in a:
                    res_attrs[a["key"]] = _extract_json_attr_val(a.get("value"))
        elif isinstance(raw_res_attrs, dict):
            res_attrs = {k: _extract_json_attr_val(v) for k, v in raw_res_attrs.items()}

        ss_list = (rs.get("scopeSpans") or rs.get("scope_spans") or
                   rs.get("instrumentationLibrarySpans") or
                   rs.get("instrumentation_library_spans") or [])
        if not isinstance(ss_list, list):
            continue

        for ss in ss_list:
            if not isinstance(ss, dict):
                continue
            span_list = ss.get("spans") or []
            if not isinstance(span_list, list):
                continue
            for sp in span_list:
                if not isinstance(sp, dict):
                    continue
                raw_attrs = sp.get("attributes") or []
                sp_attrs = {}
                if isinstance(raw_attrs, list):
                    for a in raw_attrs:
                        if isinstance(a, dict) and "key" in a:
                            sp_attrs[a["key"]] = _extract_json_attr_val(a.get("value"))
                elif isinstance(raw_attrs, dict):
                    sp_attrs = {k: _extract_json_attr_val(v) for k, v in raw_attrs.items()}

                span = {
                    "trace_id": sp.get("traceId") or sp.get("trace_id"),
                    "span_id": sp.get("spanId") or sp.get("span_id"),
                    "parent_span_id": sp.get("parentSpanId") or sp.get("parent_span_id"),
                    "name": sp.get("name"),
                    "kind": sp.get("kind"),
                    "start_time_unix_nano": sp.get("startTimeUnixNano") or sp.get("start_time_unix_nano"),
                    "end_time_unix_nano": sp.get("endTimeUnixNano") or sp.get("end_time_unix_nano"),
                    "status": sp.get("status") or {},
                    "attributes": sp_attrs,
                    "resource_attributes": res_attrs,
                }
                spans.append(span)
    return spans


def otlp_span_to_normalized_trace(span: Dict[str, Any]) -> Optional[NormalizedTrace]:
    """Convert an OTLP span dictionary into a NormalizedTrace model."""
    res_attrs = span.get("resource_attributes") or {}
    sp_attrs = span.get("attributes") or {}

    def get_attr(*keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in sp_attrs and sp_attrs[k] is not None:
                return sp_attrs[k]
            if k in res_attrs and res_attrs[k] is not None:
                return res_attrs[k]
        return default

    # WORKLOAD IDENTITY
    service_name = str(get_attr("service.name", "serviceName", "resource.service.name", default="unknown-service"))[:200]
    service_instance = str(get_attr("service.node.name", "host.name", "k8s.node.name", "service.instance.id", "node.name", default=""))[:200] or None
    environment = str(get_attr("service.environment", "deployment.environment", "environment", default="production"))[:100]

    # OPERATION & ROUTE
    name = str(span.get("name") or "unknown-operation")[:500]
    http_route = str(get_attr("http.route", "url.path", "http.target", default="") or "")[:500] or None
    operation = http_route or name

    # TIMESTAMPS & DURATION
    start_nano = span.get("start_time_unix_nano") or 0
    end_nano = span.get("end_time_unix_nano") or 0
    try:
        start_nano = int(start_nano)
        end_nano = int(end_nano)
    except (TypeError, ValueError):
        start_nano = 0
        end_nano = 0

    if start_nano > 0:
        timestamp_ms = int(start_nano // 1_000_000)
    else:
        timestamp_ms = int(time.time() * 1000)

    if start_nano > 0 and end_nano >= start_nano:
        duration_us = max(0, int((end_nano - start_nano) // 1_000))
    else:
        duration_us = 0
    duration_ms = round(duration_us / 1000.0, 3)

    # TRACE & SPAN IDS
    trace_id = str(span.get("trace_id") or "").lower()
    span_id = str(span.get("span_id") or "").lower()
    parent_span_id = str(span.get("parent_span_id") or "").lower() or None
    if not trace_id or not span_id:
        return None

    # SPAN KIND (1=INTERNAL, 2=SERVER, 3=CLIENT, 4=PRODUCER, 5=CONSUMER)
    kind_raw = span.get("kind")
    if isinstance(kind_raw, int):
        kind_map = {1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer"}
        span_kind = kind_map.get(kind_raw, "server")
    elif isinstance(kind_raw, str):
        k_lower = kind_raw.lower()
        if "server" in k_lower: span_kind = "server"
        elif "client" in k_lower: span_kind = "client"
        else: span_kind = "internal"
    else:
        span_kind = "server"

    # HTTP STATUS & OUTCOME
    status_code_raw = get_attr("http.response.status_code", "http.status_code", "status_code")
    status_code = None
    if status_code_raw is not None:
        try: status_code = int(status_code_raw)
        except (TypeError, ValueError): pass

    status_class = "unknown"
    if status_code:
        if status_code >= 500: status_class = "5xx"
        elif status_code >= 400: status_class = "4xx"
        elif status_code >= 300: status_class = "3xx"
        elif status_code >= 200: status_class = "2xx"

    status_dict = span.get("status") or {}
    status_code_enum = status_dict.get("code") if isinstance(status_dict, dict) else span.get("status_code")
    outcome = "unknown"
    if (status_code and status_code >= 400) or status_code_enum in (2, "STATUS_CODE_ERROR", "ERROR"):
        outcome = "failure"
    elif (status_code and status_code < 400) or status_code_enum in (1, "STATUS_CODE_OK", "OK"):
        outcome = "success"

    # CALLER & TARGET SERVICES
    peer_service = str(get_attr("peer.service", "client.service.name", "destination.service.resource", "caller_service", default=""))[:200] or None
    client_ip = str(get_attr("client.address", "client.ip", "net.peer.ip", "source.ip", default=""))[:100] or None
    server_ip = str(get_attr("server.address", "net.host.ip", "dst_ip", default=""))[:250] or None
    target_port = get_attr("server.port", "net.host.port", "dst_port")
    try: target_port = int(target_port) if target_port else None
    except (TypeError, ValueError): target_port = None

    if span_kind == "client":
        caller_service = service_name
        target_service = peer_service or "unknown-downstream"
    else:
        caller_service = peer_service
        target_service = service_name

    # USER IDENTITY & CREDENTIAL SANITIZATION
    auth_header = get_attr("http.request.header.authorization", "labels.http_request_header_authorization", "authorization")
    principal_name, auth_scheme = resolve_auth(auth_header)
    if principal_name == "unknown":
        for key in WSSE_USERNAME_ATTRIBUTES:
            wsse_username = normalize_wsse_username(get_attr(key))
            if wsse_username:
                principal_name, auth_scheme = wsse_username, "wsse"
                break
    if principal_name == "unknown":
        for key in SOAP_BODY_ATTRIBUTES:
            wsse_username = extract_wsse_username(get_attr(key))
            if wsse_username:
                principal_name, auth_scheme = wsse_username, "wsse"
                break
    if principal_name == "unknown":
        explicit_user = get_attr("enduser.id", "user.id", "user.name", "account.username")
        if explicit_user:
            principal_name = str(explicit_user).strip()[:200]

    # EXTRA ATTRIBUTES
    extra: Dict[str, Any] = {}
    if auth_scheme: extra["auth_scheme"] = auth_scheme
    for k, tgt in [
        ("user_agent.original", "user_agent"),
        ("http.user_agent", "user_agent"),
        ("http.request.method", "http_method"),
        ("http.method", "http_method"),
        ("labels.service_group_id", "service_group_id"),
        ("labels.service_module_id", "service_module_id"),
        ("url.full", "url_full"),
        ("url.original", "url_original"),
    ]:
        v = get_attr(k)
        if v is not None: extra[tgt] = str(v)[:300]

    http_method = str(get_attr("http.request.method", "http.method", default="GET"))[:20].upper() or None
    attributes_json = json.dumps(extra, separators=(',', ':')) if extra else None

    return NormalizedTrace(
        event_uid=f"{trace_id}:{span_id}",
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
        target_ip=server_ip,
        target_port=target_port,
        principal_name=principal_name,
        operation=operation,
        http_method=http_method,
        http_route=http_route,
        http_status=status_code,
        status_class=status_class,
        duration_ms=duration_ms,
        duration_us=duration_us,
        outcome=outcome,
        protocol="http",
        span_kind=span_kind,
        attributes_json=attributes_json,
        created_at=int(time.time() * 1000)
    )
