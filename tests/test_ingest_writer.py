from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest

from backend.app.services.ingest_writer import IngestQueueFull, IngestWriter, ingest_writer
from backend.app.services.normalization import normalize_otel_record
from backend.main import app
from backend.repository import SQLiteRepository


@pytest.fixture(scope="module", autouse=True)
def setup_api_database():
    SQLiteRepository().migrate()


def _trace(index: int):
    trace = normalize_otel_record({
        "ts": 1_787_793_600 + index,
        "service": "load-test-service",
        "path": f"/load/{index}",
        "trace_id": f"{index + 1:032x}",
        "span_id": f"{index + 1:016x}",
        "status": 200,
        "duration_ms": 2,
    })
    assert trace is not None
    return trace


def test_concurrent_uploads_are_coalesced_and_batch_dedup_is_atomic(tmp_path):
    db_path = tmp_path / "coalesced.db"
    SQLiteRepository(db_path).migrate()
    writer = IngestWriter(
        db_path=db_path,
        queue_capacity=64,
        coalesce_ms=30,
        transaction_records=10_000,
        commit_timeout_seconds=5,
    )
    shared_batch_id = f"concurrent-{uuid4()}"

    try:
        with ThreadPoolExecutor(max_workers=24) as pool:
            unique_results = list(pool.map(
                lambda index: writer.submit([_trace(index)], node="load-node"),
                range(20),
            ))
        assert sum(result.inserted for result in unique_results) == 20
        assert writer.snapshot()["write_transactions"] < 20

        with ThreadPoolExecutor(max_workers=8) as pool:
            duplicate_results = list(pool.map(
                lambda index: writer.submit(
                    [_trace(100 + index)], batch_id=shared_batch_id, node="load-node"
                ),
                range(8),
            ))
        assert sum(not result.duplicate for result in duplicate_results) == 1
        assert sum(result.inserted for result in duplicate_results) == 1

        with SQLiteRepository(db_path).connect() as db:
            assert db.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 21
            assert db.execute(
                "SELECT COUNT(*) FROM ingest_batches WHERE batch_id=?", (shared_batch_id,)
            ).fetchone()[0] == 1
    finally:
        writer.shutdown()


def test_saturated_ingest_returns_retryable_429(monkeypatch):
    async def reject(*_args, **_kwargs):
        raise IngestQueueFull("full")

    monkeypatch.setattr(ingest_writer, "submit_async", reject)

    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/ingest", json={"path": "/overload"})

    response = asyncio.run(send())
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert "retry with backoff" in response.json()["detail"]


def test_writer_rejects_when_bounded_queue_is_full(tmp_path, monkeypatch):
    db_path = tmp_path / "backpressure.db"
    SQLiteRepository(db_path).migrate()
    writer = IngestWriter(
        db_path=db_path,
        queue_capacity=1,
        coalesce_ms=0,
        commit_timeout_seconds=5,
    )
    write_started = threading.Event()
    release_write = threading.Event()
    original_write = writer._write

    def blocked_write(*args, **kwargs):
        write_started.set()
        assert release_write.wait(2)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(writer, "_write", blocked_write)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(writer.submit, [_trace(300)])
            assert write_started.wait(2)
            second = pool.submit(writer.submit, [_trace(301)])
            deadline = time.monotonic() + 2
            while writer.snapshot()["queue_depth"] < 1 and time.monotonic() < deadline:
                time.sleep(0.001)
            with pytest.raises(IngestQueueFull):
                writer.submit([_trace(302)])
            release_write.set()
            assert first.result(timeout=3).inserted == 1
            assert second.result(timeout=3).inserted == 1
    finally:
        release_write.set()
        writer.shutdown()


def test_concurrent_http_uploads_share_write_transactions():
    request_count = 32
    records_per_request = 4
    run_id = uuid4().hex
    before = ingest_writer.snapshot()

    async def send_all():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            requests = []
            for request_index in range(request_count):
                records = []
                for record_index in range(records_per_request):
                    index = request_index * records_per_request + record_index
                    records.append({
                        "ts": 1_787_800_000 + index,
                        "service": "http-load-service",
                        "path": f"/http-load/{run_id}/{index}",
                        "trace_id": f"{run_id[:24]}{index:08x}",
                        "span_id": f"{index + 1:016x}",
                        "status": 200,
                        "duration_ms": 3,
                    })
                requests.append(client.post(
                    "/api/v1/ingest",
                    json=records,
                    headers={"X-Batch-Id": f"{run_id}-{request_index}"},
                ))
            responses = await asyncio.gather(*requests)
            status = await client.get("/api/v1/ingestion/status")
            return responses, status

    responses, status = asyncio.run(send_all())
    assert all(response.status_code == 200 for response in responses), [
        (response.status_code, response.text) for response in responses
        if response.status_code != 200
    ]
    assert sum(response.json()["inserted"] for response in responses) == (
        request_count * records_per_request
    )
    after = ingest_writer.snapshot()
    transaction_delta = after["write_transactions"] - before["write_transactions"]
    assert transaction_delta < request_count
    assert status.status_code == 200
    writer_status = status.json()["ingest_writer"]
    assert writer_status["queue_capacity"] >= request_count
    assert writer_status["committed_records"] >= request_count * records_per_request
