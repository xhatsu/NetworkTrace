"""Normalize diverse telemetry at the trust boundary before one durable ingest path.

The router deliberately turns protocol variation into canonical traces before
the bounded writer applies ClickHouse batching, deduplication, and backpressure.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.app.security import require_api_key
from backend.app.models.trace import NormalizedTrace
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.otlp_parser import (
    decompress_payload,
    parse_otlp_json,
    parse_otlp_protobuf,
    otlp_span_to_normalized_trace,
)
from backend.app.services.apm_parser import (
    parse_apm_body,
    apm_document_to_normalized_trace,
)
from backend.app.services.ingest_writer import (
    IngestCommitTimeout,
    IngestQueueFull,
    IngestWriteResult,
    ingest_writer,
)
from backend.app.services.storage_owner_client import StorageOwnerError, storage_owner_client

router = APIRouter(prefix="/api/v1", tags=["ingestion"])
legacy_router = APIRouter(tags=["ingestion"])
otlp_router = APIRouter(tags=["otlp"])


def _normalize_records(records: List[Dict[str, Any]], envelope_node: Any) -> tuple[List[NormalizedTrace], int]:
    traces: List[NormalizedTrace] = []
    rejected = 0
    for record in records:
        normalized_record = record
        if envelope_node and "host" not in record:
            normalized_record = {**record, "host": envelope_node}
        trace = normalize_otel_record(normalized_record)
        if trace:
            traces.append(trace)
        else:
            rejected += 1
    return traces, rejected


async def _commit_traces(
    traces: List[NormalizedTrace], batch_id: str = "", node: str = "unknown"
):
    try:
        if storage_owner_client.enabled:
            result = await storage_owner_client.commit_traces(traces, batch_id, node)
            return IngestWriteResult(
                inserted=int(result.get("inserted", 0)),
                duplicate=bool(result.get("duplicate", False)),
            )
        return await ingest_writer.submit_async(traces, batch_id, node)
    except IngestQueueFull:
        raise HTTPException(
            status_code=429,
            detail="Ingestion queue is full; retry with backoff",
            headers={"Retry-After": "1"},
        ) from None
    except IngestCommitTimeout:
        raise HTTPException(
            status_code=503,
            detail="Timed out waiting for ingestion commit; retry with the same X-Batch-Id",
            headers={"Retry-After": "1"},
        ) from None
    except Exception as exc:
        if isinstance(exc, (HTTPException, IngestQueueFull, IngestCommitTimeout, StorageOwnerError)):
            raise
        raise HTTPException(
            status_code=503,
            detail="Ingestion store is busy; retry with the same X-Batch-Id",
            headers={"Retry-After": "1"},
        ) from None
    except StorageOwnerError as exc:
        headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
            headers=headers,
        ) from None


@router.post("/ingest", dependencies=[Depends(require_api_key)])
@router.post("/ingest/traces", dependencies=[Depends(require_api_key)])
@legacy_router.post("/api/ingest", dependencies=[Depends(require_api_key)], include_in_schema=False)
async def ingest_traces(request: Request) -> Dict[str, Any]:
    batch_id = (request.headers.get("x-batch-id") or "").strip()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_ingest_bytes:
                raise HTTPException(status_code=413, detail="Ingestion payload is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from None
    raw_body = await request.body()
    if len(raw_body) > settings.max_ingest_bytes:
        raise HTTPException(status_code=413, detail="Ingestion payload is too large")

    content_encoding = request.headers.get("content-encoding")
    try:
        decompressed = decompress_payload(raw_body, content_encoding, settings.max_ingest_bytes * 4)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    if len(decompressed) > settings.max_ingest_bytes * 4:
        raise HTTPException(status_code=413, detail="Decompressed payload is too large")

    try:
        body = json.loads(decompressed)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from None

    envelope_node = None
    if isinstance(body, dict) and "events" in body:
        if not isinstance(body["events"], list):
            raise HTTPException(status_code=422, detail="NetworkTracing events must be an array")
        records = body["events"]
        envelope_node = body.get("node")
    elif isinstance(body, dict) and ("resourceSpans" in body or "resource_spans" in body):
        # Direct OTLP JSON payload sent to generic ingest endpoint
        spans = parse_otlp_json(body)
        if len(spans) > settings.max_ingest_records:
            raise HTTPException(status_code=413, detail="Too many ingestion records")
        traces: List[NormalizedTrace] = []
        for s in spans:
            t = otlp_span_to_normalized_trace(s)
            if t:
                traces.append(t)
        write_result = await _commit_traces(traces, batch_id, envelope_node or "otlp")
        inserted = write_result.inserted
        resp: Dict[str, Any] = {
            "status": "success",
            "received": 0 if write_result.duplicate else len(spans),
            "inserted": inserted,
            "rejected": 0 if write_result.duplicate else len(spans) - len(traces),
        }
        if batch_id:
            resp["ok"] = True
            resp["duplicate"] = write_result.duplicate
            resp["batch_id"] = batch_id
            if write_result.duplicate:
                resp["message"] = "Batch already processed"
        return resp
    else:
        records = body if isinstance(body, list) else [body]

    if not all(isinstance(record, dict) for record in records):
        raise HTTPException(status_code=422, detail="Each ingestion record must be an object")
    if len(records) > settings.max_ingest_records:
        raise HTTPException(status_code=413, detail="Too many ingestion records")

    traces, rejected = _normalize_records(records, envelope_node)
    write_result = await _commit_traces(traces, batch_id, envelope_node or "unknown")
    inserted = write_result.inserted

    resp = {
        "status": "success",
        "received": 0 if write_result.duplicate else len(records),
        "inserted": inserted,
        "rejected": 0 if write_result.duplicate else rejected,
    }
    if batch_id:
        resp["ok"] = True
        resp["duplicate"] = write_result.duplicate
        resp["batch_id"] = batch_id
        if write_result.duplicate:
            resp["message"] = "Batch already processed"
    return resp


# =========================================================================
# Canonical OTLP/HTTP Trace Receiver (POST /v1/traces)
# =========================================================================

@otlp_router.post("/v1/traces")
async def otlp_v1_traces(request: Request) -> Dict[str, Any]:
    raw_body = await request.body()
    if len(raw_body) > settings.max_ingest_bytes:
        return JSONResponse({"error": "Payload Too Large"}, status_code=413)
    if not raw_body:
        return {"partialSuccess": {}}

    content_type = request.headers.get("content-type", "").lower()
    content_encoding = request.headers.get("content-encoding", "")
    try:
        decompressed = decompress_payload(raw_body, content_encoding, settings.max_ingest_bytes * 4)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if len(decompressed) > settings.max_ingest_bytes * 4:
        return JSONResponse({"error": "Decompressed payload is too large"}, status_code=413)

    spans = []
    if "protobuf" in content_type or (not content_type and not decompressed.startswith(b"{")):
        try:
            spans = parse_otlp_protobuf(decompressed)
        except Exception:
            try:
                spans = parse_otlp_json(json.loads(decompressed.decode("utf-8", "replace")))
            except Exception:
                return JSONResponse({"error": "Invalid OTLP protobuf/json"}, status_code=400)
    else:
        try:
            data = json.loads(decompressed.decode("utf-8", "replace"))
            spans = parse_otlp_json(data)
        except Exception:
            return JSONResponse({"error": "Invalid OTLP JSON"}, status_code=400)
    if len(spans) > settings.max_ingest_records:
        return JSONResponse({"error": "Too many ingestion records"}, status_code=413)

    traces: List[NormalizedTrace] = []
    for s in spans:
        t = otlp_span_to_normalized_trace(s)
        if t:
            traces.append(t)

    await _commit_traces(traces)

    return {"partialSuccess": {}}


# =========================================================================
# Elastic APM 7.x Transaction Adapter (POST /api/ingest/apm)
# =========================================================================

@legacy_router.post("/api/ingest/apm")
@legacy_router.post("/api/ingest/elastic-apm")
async def elastic_apm_ingest(request: Request) -> Dict[str, Any]:
    raw_body = await request.body()
    if len(raw_body) > settings.max_ingest_bytes:
        return JSONResponse({"error": "Payload Too Large"}, status_code=413)
    if not raw_body:
        return {"ok": True, "accepted": 0, "ignored": 0, "rejected": 0}

    content_type = request.headers.get("content-type", "")
    content_encoding = request.headers.get("content-encoding", "")
    try:
        decompressed = decompress_payload(raw_body, content_encoding, settings.max_ingest_bytes * 4)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if len(decompressed) > settings.max_ingest_bytes * 4:
        return JSONResponse({"error": "Decompressed payload is too large"}, status_code=413)

    documents = parse_apm_body(decompressed, content_type)
    if not documents:
        return JSONResponse({"error": "No Elastic APM transaction documents found"}, status_code=400)
    if len(documents) > settings.max_ingest_records:
        return JSONResponse({"error": "Too many ingestion records"}, status_code=413)

    traces: List[NormalizedTrace] = []
    ignored = 0
    for doc in documents:
        t = apm_document_to_normalized_trace(doc)
        if t:
            traces.append(t)
        else:
            ignored += 1

    write_result = await _commit_traces(traces)
    inserted = write_result.inserted

    return {
        "ok": True,
        "accepted": inserted,
        "ignored": ignored + (len(traces) - inserted),
        "rejected": 0,
        "source_format": "elastic-apm-7.x-transaction",
    }


# =========================================================================
# OTLP Metrics and Logs Stubs (POST /v1/metrics, POST /v1/logs)
# =========================================================================

@otlp_router.post("/v1/metrics")
async def otlp_v1_metrics(request: Request) -> Dict[str, Any]:
    return {"partialSuccess": {}}


@otlp_router.post("/v1/logs")
async def otlp_v1_logs(request: Request) -> Dict[str, Any]:
    return {"partialSuccess": {}}
