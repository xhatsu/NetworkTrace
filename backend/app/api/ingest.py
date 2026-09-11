from __future__ import annotations

import json
from typing import Any, Dict, List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
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
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.repositories.ingest_batch_repository import IngestBatchRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.principal_relationships import process_principal_intelligence

router = APIRouter(prefix="/api/v1", tags=["ingestion"])
legacy_router = APIRouter(tags=["ingestion"])
otlp_router = APIRouter(tags=["otlp"])


def _aggregate_ingested_window(start_ms: int, end_ms: int) -> None:
    try:
        aggregate_traces(start_ms, end_ms)
        process_principal_intelligence()
    except Exception:
        pass


@router.post("/ingest", dependencies=[Depends(require_api_key)])
@router.post("/ingest/traces", dependencies=[Depends(require_api_key)])
@legacy_router.post("/api/ingest", dependencies=[Depends(require_api_key)], include_in_schema=False)
async def ingest_traces(request: Request, bg: BackgroundTasks) -> Dict[str, Any]:
    batch_id = (request.headers.get("x-batch-id") or "").strip()
    batch_repo = IngestBatchRepository()
    if batch_id and batch_repo.is_batch_processed(batch_id):
        return {
            "status": "success",
            "ok": True,
            "duplicate": True,
            "batch_id": batch_id,
            "message": "Batch already processed",
            "received": 0,
            "inserted": 0,
            "rejected": 0,
        }

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
        decompressed = decompress_payload(raw_body, content_encoding)
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
        traces: List[NormalizedTrace] = []
        for s in spans:
            t = otlp_span_to_normalized_trace(s)
            if t:
                traces.append(t)
        repo = TraceRepository()
        inserted = repo.insert_traces(traces)
        if batch_id:
            batch_repo.record_batch(
                batch_id=batch_id,
                node=envelope_node or "otlp",
                record_count=len(traces),
                status="accepted",
            )
        if inserted > 0:
            min_ts = min(t.timestamp_ms for t in traces)
            max_ts = max(t.timestamp_ms for t in traces)
            bg.add_task(_aggregate_ingested_window, min_ts, max_ts + 60_000)
        resp: Dict[str, Any] = {
            "status": "success",
            "received": len(spans),
            "inserted": inserted,
            "rejected": len(spans) - len(traces),
        }
        if batch_id:
            resp["ok"] = True
            resp["duplicate"] = False
            resp["batch_id"] = batch_id
        return resp
    else:
        records = body if isinstance(body, list) else [body]

    if not all(isinstance(record, dict) for record in records):
        raise HTTPException(status_code=422, detail="Each ingestion record must be an object")
    if len(records) > settings.max_ingest_records:
        raise HTTPException(status_code=413, detail="Too many ingestion records")

    traces: List[NormalizedTrace] = []
    rejected = 0
    for record in records:
        r = record
        if envelope_node and "host" not in record:
            r = {**record, "host": envelope_node}
        t = normalize_otel_record(r)
        if t:
            traces.append(t)
        else:
            rejected += 1

    repo = TraceRepository()
    inserted = repo.insert_traces(traces)
    if batch_id:
        batch_repo.record_batch(
            batch_id=batch_id,
            node=envelope_node or "unknown",
            record_count=len(traces),
            status="accepted",
        )

    if inserted > 0:
        min_ts = min(t.timestamp_ms for t in traces)
        max_ts = max(t.timestamp_ms for t in traces)
        bg.add_task(_aggregate_ingested_window, min_ts, max_ts + 60_000)

    resp = {
        "status": "success",
        "received": len(records),
        "inserted": inserted,
        "rejected": rejected,
    }
    if batch_id:
        resp["ok"] = True
        resp["duplicate"] = False
        resp["batch_id"] = batch_id
    return resp


# =========================================================================
# Canonical OTLP/HTTP Trace Receiver (POST /v1/traces)
# =========================================================================

@otlp_router.post("/v1/traces")
async def otlp_v1_traces(request: Request, bg: BackgroundTasks) -> Dict[str, Any]:
    raw_body = await request.body()
    if len(raw_body) > settings.max_ingest_bytes:
        return JSONResponse({"error": "Payload Too Large"}, status_code=413)
    if not raw_body:
        return {"partialSuccess": {}}

    content_type = request.headers.get("content-type", "").lower()
    content_encoding = request.headers.get("content-encoding", "")
    try:
        decompressed = decompress_payload(raw_body, content_encoding)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

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

    traces: List[NormalizedTrace] = []
    for s in spans:
        t = otlp_span_to_normalized_trace(s)
        if t:
            traces.append(t)

    repo = TraceRepository()
    inserted = repo.insert_traces(traces)
    if inserted > 0:
        min_ts = min(t.timestamp_ms for t in traces)
        max_ts = max(t.timestamp_ms for t in traces)
        bg.add_task(_aggregate_ingested_window, min_ts, max_ts + 60_000)

    return {"partialSuccess": {}}


# =========================================================================
# Elastic APM 7.x Transaction Adapter (POST /api/ingest/apm)
# =========================================================================

@legacy_router.post("/api/ingest/apm")
@legacy_router.post("/api/ingest/elastic-apm")
async def elastic_apm_ingest(request: Request, bg: BackgroundTasks) -> Dict[str, Any]:
    raw_body = await request.body()
    if len(raw_body) > settings.max_ingest_bytes:
        return JSONResponse({"error": "Payload Too Large"}, status_code=413)
    if not raw_body:
        return {"ok": True, "accepted": 0, "ignored": 0, "rejected": 0}

    content_type = request.headers.get("content-type", "")
    content_encoding = request.headers.get("content-encoding", "")
    try:
        decompressed = decompress_payload(raw_body, content_encoding)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    documents = parse_apm_body(decompressed, content_type)
    if not documents:
        return JSONResponse({"error": "No Elastic APM transaction documents found"}, status_code=400)

    traces: List[NormalizedTrace] = []
    ignored = 0
    for doc in documents:
        t = apm_document_to_normalized_trace(doc)
        if t:
            traces.append(t)
        else:
            ignored += 1

    repo = TraceRepository()
    inserted = repo.insert_traces(traces)
    if inserted > 0:
        min_ts = min(t.timestamp_ms for t in traces)
        max_ts = max(t.timestamp_ms for t in traces)
        bg.add_task(_aggregate_ingested_window, min_ts, max_ts + 60_000)

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
