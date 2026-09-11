from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .repository import SQLiteRepository


SENSITIVE_KEYS = {"labels.http_request_header_authorization", "http.request.headers.authorization", "authorization"}


def get_path(document: dict[str, Any], path: str, default: Any = None) -> Any:
    if path in document:
        value = document[path]
    else:
        value: Any = document
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value if value is not None else default


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
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def basic_username(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str) or not value.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(value.split(None, 1)[1], validate=True).decode("utf-8")
        username, separator, _password = decoded.partition(":")
        return username[:300] if separator and username else None
    except (ValueError, UnicodeDecodeError):
        return None


def _otel_attributes(document: dict[str, Any]) -> dict[str, Any]:
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


def normalize(raw: dict[str, Any], source_file: str = "import", offset: int = 0) -> dict[str, Any] | None:
    # Elasticsearch hits are a single event: _source always wins over fields.
    source = raw.get("_source") if isinstance(raw.get("_source"), dict) else raw.get("fields") if isinstance(raw.get("fields"), dict) else raw
    if not isinstance(source, dict): return None
    attrs = _otel_attributes(source)
    def pick(path: str, *alternates: str, default=None):
        value = get_path(source, path)
        if value is None:
            for alt in alternates:
                value = get_path(source, alt)
                if value is not None: break
        if value is None:
            for key in (path, *alternates):
                if key in attrs: value = attrs[key]; break
        return default if value is None else value

    service = str(pick("service.name", "resource.service.name", "serviceName", default="Unknown service"))[:200]
    operation = str(pick("transaction.name", "name", default="Unknown operation"))[:500]
    timestamp_ms = parse_timestamp(pick("@timestamp", "timestamp", "startTimeUnixNano", "start_time_unix_nano"))
    start_nano = pick("startTimeUnixNano", "start_time_unix_nano")
    if start_nano and not pick("@timestamp", "timestamp"):
        try: timestamp_ms = int(int(start_nano) / 1_000_000)
        except (ValueError, TypeError): pass
    duration = pick("transaction.duration.us", "duration_us")
    if duration is None and pick("duration_nano") is not None: duration = int(pick("duration_nano")) / 1000
    if duration is None:
        end_nano = pick("endTimeUnixNano", "end_time_unix_nano")
        if start_nano is not None and end_nano is not None:
            try: duration = max(0, (int(end_nano) - int(start_nano)) / 1000)
            except (ValueError, TypeError): pass
    try: duration_us = max(0, int(float(duration or 0)))
    except (ValueError, TypeError): return None
    auth = pick("labels.http_request_header_authorization", "http.request.headers.authorization", "authorization")
    account = basic_username(auth) or pick("enduser.id", "user.name", "user.id", "account.username")
    if account: account = str(account)[:300]
    status = pick("http.response.status_code", "http.status_code")
    try: status_code = int(status) if status is not None else None
    except (ValueError, TypeError): status_code = None
    event_type = str(pick("processor.event", "event.type", default="transaction"))
    kind = str(pick("span.kind", "span_kind", "kind", default="server" if event_type == "transaction" else "internal")).lower()
    if kind in {"span_kind_server", "server"}: kind = "server"
    elif kind in {"span_kind_client", "client", "producer"}: kind = "client"
    elif kind in {"span_kind_internal", "internal"}: kind = "internal"
    if kind == "server" and event_type == "span": event_type = "transaction"
    transaction_id = str(pick("transaction.id", "span.id", "span_id", "spanId", default="")) or None
    trace_id = str(pick("trace.id", "trace_id", "traceId", default="")) or None
    parent_id = str(pick("parent.id", "parent_span_id", "parentSpanId", default="")) or None
    outcome = str(pick("event.outcome", default="unknown"))[:30]
    if outcome == "unknown":
        status_code_name = str(pick("status.code", default="")).upper()
        if (status_code and status_code >= 400) or status_code_name == "STATUS_CODE_ERROR":
            outcome = "failure"
        elif (status_code and status_code < 400) or status_code_name == "STATUS_CODE_OK":
            outcome = "success"
    canonical = [timestamp_ms, trace_id, transaction_id, service, operation, duration_us, kind]
    supplied_id = raw.get("_id") or pick("event.id")
    event_uid = str(supplied_id) if supplied_id else (f"{trace_id}:{transaction_id}" if trace_id and transaction_id else hashlib.sha256(json.dumps(canonical,separators=(",",":"),ensure_ascii=True).encode()).hexdigest())
    node_name = str(pick("service.node.name", "host.name", "node.name", default=""))[:200] or None
    extra_attrs: dict[str, Any] = {}
    for key, target in [
        ("labels.user_agent_original", "user_agent"),
        ("user_agent.original", "user_agent"),
        ("labels.http_route", "http_route"),
        ("http.route", "http_route"),
        ("labels.thread_name", "thread_name"),
        ("thread.name", "thread_name"),
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
    ]:
        val = pick(key)
        if val is not None and target not in extra_attrs:
            extra_attrs[target] = str(val)[:300]
    for key, target in [
        ("labels.http_request_content_length", "request_bytes"),
        ("http.request.body.size", "request_bytes"),
        ("labels.http_response_content_length", "response_bytes"),
        ("http.response.body.size", "response_bytes"),
        ("labels.net_sock_peer_port", "peer_port"),
        ("labels.thread_id", "thread_id"),
        ("process.pid", "process_pid"),
    ]:
        val = pick(key)
        if val is not None and target not in extra_attrs:
            try: extra_attrs[target] = int(val)
            except (ValueError, TypeError): pass
    attributes_json = json.dumps(extra_attrs, separators=(',', ':')) if extra_attrs else None

    return {
        "event_uid": event_uid, "timestamp_ms": timestamp_ms, "ingested_ms": parse_timestamp(pick("event.ingested", default=timestamp_ms)),
        "trace_id": trace_id, "transaction_id": transaction_id, "parent_id": parent_id,
        "service_name": service, "environment": str(pick("service.environment", default="production"))[:100],
        "node_name": node_name,
        "service_group": str(pick("labels.service_group_id", default="Ungrouped"))[:150],
        "service_module": str(pick("labels.service_module_id", default="Core"))[:150],
        "operation": operation, "duration_us": duration_us,
        "sampled": 1 if pick("transaction.sampled") is True else 0 if pick("transaction.sampled") is False else None,
        "outcome": outcome, "http_method": str(pick("http.request.method", "http.method", default=""))[:20] or None,
        "status_code": status_code, "account_username": account, "account_namespace": str(pick("labels.account_namespace", default=""))[:100],
        "span_kind": kind, "event_type": event_type[:30], "peer_service": str(pick("peer.service", "destination.service.resource", "peer.service.name", default=""))[:200] or None,
        "peer_address": str(pick("labels.net_sock_peer_addr", "net.peer.name", "destination.address", "peer.address", default=""))[:250] or None,
        "host_address": str(pick("labels.net_sock_host_addr", "net.host.name", "server.address", default=""))[:250] or None,
        "url_domain": str(pick("url.domain", default=""))[:250] or None, "url_port": int(pick("url.port", default=0) or 0) or None,
        "url_path": str(pick("url.path", "http.target", default=""))[:1000] or None, "source_file": Path(source_file).name[:300],
        "source_offset": offset, "created_at_ms": int(time.time()*1000),
        "client_ip": str(pick("client.ip", "client.address", default=""))[:100] or None,
        "source_ip": str(pick("source.ip", default=""))[:100] or None,
        "attributes_json": attributes_json,
    }


def stream_documents(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        first = handle.read(1)
        handle.seek(0)
        if first == "[":
            payload = json.load(handle)
            yield from payload
            return
        # Handles Elasticsearch response objects without retaining duplicate fields as events.
        if first == "{":
            position = handle.tell(); first_line = handle.readline()
            try:
                candidate = json.loads(first_line)
                if "hits" in candidate and isinstance(candidate["hits"], dict):
                    yield from candidate["hits"].get("hits", [])
                    for line in handle:
                        if line.strip(): yield json.loads(line)
                    return
                yield candidate
            except json.JSONDecodeError:
                handle.seek(position)
                payload = json.load(handle)
                hits = get_path(payload, "hits.hits")
                if isinstance(hits, list): yield from hits
                else: yield payload
                return
            for line in handle:
                if line.strip(): yield json.loads(line)


@dataclass
class ImportResult:
    read: int = 0
    inserted: int = 0
    duplicates: int = 0
    rejected: int = 0


EVENT_COLUMNS = ("event_uid","timestamp_ms","ingested_ms","trace_id","transaction_id","parent_id","service_name","environment","node_name","service_group","service_module","operation","duration_us","sampled","outcome","http_method","status_code","account_username","account_namespace","span_kind","event_type","peer_service","peer_address","host_address","url_domain","url_port","url_path","source_file","source_offset","created_at_ms","client_ip","source_ip","attributes_json")


def import_documents(repository: SQLiteRepository, documents: Iterable[dict[str, Any]], source: str = "import", batch_size: int = 2000) -> ImportResult:
    result = ImportResult(); batch: list[dict[str, Any]] = []
    def flush() -> None:
        if not batch: return
        with repository.transaction() as db:
            uids = [event["event_uid"] for event in batch]
            existing_uids = set()
            if uids:
                in_ph = ",".join(["?"] * len(uids))
                rows = db.execute(f"SELECT event_uid FROM events WHERE event_uid IN ({in_ph})", uids).fetchall()
                existing_uids = {r[0] for r in rows}
            new_events = [e for e in batch if e["event_uid"] not in existing_uids]
            if new_events:
                db.executemany(f"INSERT INTO events({','.join(EVENT_COLUMNS)}) VALUES ({','.join('?' for _ in EVENT_COLUMNS)})", [[event[c] for c in EVENT_COLUMNS] for event in new_events])
                result.inserted += len(new_events)
                dirty={event["timestamp_ms"]-event["timestamp_ms"]%60_000 for event in new_events}
                now_ms = int(time.time() * 1000)
                db.executemany("INSERT INTO dirty_buckets(bucket_ms,reason,created_at_ms) VALUES (?,?,?)", [(bucket, 'import-or-late-arrival', now_ms) for bucket in dirty])
                service_inventory: dict[str, tuple[dict[str, Any], int, int]] = {}
                account_inventory: dict[tuple[str, str], tuple[dict[str, Any], int, int]] = {}
                for event in new_events:
                    existing=service_inventory.get(event["service_name"])
                    if existing is None: service_inventory[event["service_name"]]=(event,event["timestamp_ms"],event["timestamp_ms"])
                    else: service_inventory[event["service_name"]]=(existing[0],min(existing[1],event["timestamp_ms"]),max(existing[2],event["timestamp_ms"]))
                    if event["account_username"]:
                        key=(event["account_username"],event["account_namespace"])
                        existing_account=account_inventory.get(key)
                        if existing_account is None: account_inventory[key]=(event,event["timestamp_ms"],event["timestamp_ms"])
                        else: account_inventory[key]=(existing_account[0],min(existing_account[1],event["timestamp_ms"]),max(existing_account[2],event["timestamp_ms"]))
                for event,first_seen,last_seen in service_inventory.values():
                    db.execute("INSERT INTO services(name,environment,service_group,service_module,first_seen_ms,last_seen_ms) VALUES (?,?,?,?,?,?)", (event["service_name"],event["environment"],event["service_group"],event["service_module"],first_seen,last_seen))
                for event,first_seen,last_seen in account_inventory.values():
                    db.execute("INSERT INTO accounts(username,namespace,first_seen_ms,last_seen_ms) VALUES (?,?,?,?)", (event["account_username"],event["account_namespace"],first_seen,last_seen))
            result.duplicates += len(batch) - len(new_events)
        batch.clear()
    for offset, raw in enumerate(documents):
        result.read += 1
        try: event = normalize(raw, source, offset)
        except Exception: event = None
        if event is None: result.rejected += 1; continue
        batch.append(event)
        if len(batch) >= batch_size: flush()
    # Duplicate math is clearer when derived from totals after all batches.
    flush(); result.duplicates = result.read - result.rejected - result.inserted
    return result


def import_file(repository: SQLiteRepository, path: Path, batch_size: int = 2000, limit: int | None = None) -> ImportResult:
    docs: Iterable[dict[str, Any]] = stream_documents(path)
    if limit is not None:
        import itertools
        docs = itertools.islice(docs, limit)
    return import_documents(repository, docs, str(path), batch_size)

