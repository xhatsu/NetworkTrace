from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest

from backend.app.services.ingest_writer import (
    IngestQueueFull, IngestWriter, IngestWriteResult, _WriteRequest, ingest_writer,
)
from backend.app.repositories.db_context import get_connection
from backend.app.services.normalization import normalize_otel_record
from backend.main import app
from backend.repository import StorageRepository


@pytest.fixture(scope="module", autouse=True)
def setup_api_database():
    StorageRepository().migrate()


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


def test_trace_ids_are_unique_and_composite_cursor_does_not_skip_large_blocks(tmp_path):
    db_path = tmp_path / "unique-ids.db"
    StorageRepository(db_path).migrate()
    writer = IngestWriter(db_path=db_path, coalesce_ms=0, commit_timeout_seconds=10)
    try:
        assert writer.submit([_trace(i) for i in range(10_001)]).inserted == 10_001
        with get_connection(db_path) as db:
            count, ids, row_uids = db.execute(
                "SELECT count(),uniqExact(id),uniqExact(row_uid) FROM traces"
            ).fetchone()
            assert (count, ids, row_uids) == (10_001, 10_001, 10_001)
            cursor_order = 0
            cursor_uid = "00000000-0000-0000-0000-000000000000"
            seen = 0
            while True:
                rows = db.execute(
                    "SELECT ingest_order,toString(row_uid) FROM traces "
                    "WHERE (ingest_order,row_uid)>(?,toUUID(?)) ORDER BY ingest_order,row_uid LIMIT 10000",
                    (cursor_order, cursor_uid),
                ).fetchall()
                if not rows:
                    break
                seen += len(rows)
                cursor_order, cursor_uid = int(rows[-1][0]), str(rows[-1][1])
            assert seen == 10_001
    finally:
        writer.shutdown()


def test_retry_repairs_marker_after_trace_insert_succeeds(tmp_path, monkeypatch):
    db_path = tmp_path / "marker-recovery.db"
    StorageRepository(db_path).migrate()
    db = get_connection(db_path)
    writer = IngestWriter(db_path=db_path)
    existing = {row[0] for row in db.client.query(f"DESCRIBE TABLE {db.database}.traces").result_rows}
    columns = [column for column in writer._TRACE_COLUMNS if column in existing]
    original_insert = db.client.insert
    failed = False

    def fail_marker_once(table, *args, **kwargs):
        nonlocal failed
        if table == "ingest_batches" and not failed:
            failed = True
            raise RuntimeError("injected marker failure")
        return original_insert(table, *args, **kwargs)

    monkeypatch.setattr(db.client, "insert", fail_marker_once)
    first = _WriteRequest([_trace(55)], batch_id="recoverable-batch", node="node")
    writer._write(db, "", columns, [first])
    assert isinstance(first.error, RuntimeError)

    retry = _WriteRequest([_trace(55)], batch_id="recoverable-batch", node="node")
    writer._write(db, "", columns, [retry])
    assert retry.result == IngestWriteResult(inserted=0, duplicate=True)
    assert db.execute("SELECT count() FROM traces WHERE ingest_batch_id='recoverable-batch'").fetchone()[0] == 1
    assert db.execute("SELECT count() FROM ingest_batches WHERE batch_id='recoverable-batch'").fetchone()[0] == 1


def test_marker_insert_failure_midflight_repairs_every_batch_without_duplicates(tmp_path, monkeypatch):
    db_path = tmp_path / "marker-midflight-recovery.db"
    StorageRepository(db_path).migrate()
    db = get_connection(db_path)
    writer = IngestWriter(db_path=db_path)
    existing = {row[0] for row in db.client.query(f"DESCRIBE TABLE {db.database}.traces").result_rows}
    columns = [column for column in writer._TRACE_COLUMNS if column in existing]
    original_insert = db.client.insert

    def fail_markers(table, *args, **kwargs):
        if table == "ingest_batches":
            raise RuntimeError("injected multi-marker failure")
        return original_insert(table, *args, **kwargs)

    monkeypatch.setattr(db.client, "insert", fail_markers)
    first_jobs = [
        _WriteRequest([_trace(56)], batch_id="recoverable-a", node="node"),
        _WriteRequest([_trace(57)], batch_id="recoverable-b", node="node"),
    ]
    writer._write(db, "", columns, first_jobs)
    assert all(isinstance(job.error, RuntimeError) for job in first_jobs)
    monkeypatch.setattr(db.client, "insert", original_insert)

    retries = [
        _WriteRequest([_trace(56)], batch_id="recoverable-a", node="node"),
        _WriteRequest([_trace(57)], batch_id="recoverable-b", node="node"),
    ]
    writer._write(db, "", columns, retries)
    assert all(job.result == IngestWriteResult(inserted=0, duplicate=True) for job in retries)
    assert db.execute("SELECT count() FROM traces WHERE ingest_batch_id LIKE 'recoverable-%'").fetchone()[0] == 2
    assert db.execute("SELECT count() FROM ingest_batches WHERE batch_id LIKE 'recoverable-%'").fetchone()[0] == 2


def test_lost_success_response_retry_is_duplicate(tmp_path):
    db_path = tmp_path / "lost-response.db"
    StorageRepository(db_path).migrate()
    db = get_connection(db_path)
    writer = IngestWriter(db_path=db_path)
    existing = {row[0] for row in db.client.query(f"DESCRIBE TABLE {db.database}.traces").result_rows}
    columns = [column for column in writer._TRACE_COLUMNS if column in existing]

    committed = _WriteRequest([_trace(58)], batch_id="lost-response", node="node")
    writer._write(db, "", columns, [committed])
    # The caller discards the successful result, exactly as if the HTTP response
    # were lost after the durable commit, then resubmits the same batch.
    retry = _WriteRequest([_trace(58)], batch_id="lost-response", node="node")
    writer._write(db, "", columns, [retry])
    assert committed.result == IngestWriteResult(inserted=1, duplicate=False)
    assert retry.result == IngestWriteResult(inserted=0, duplicate=True)
    assert db.execute("SELECT count() FROM traces WHERE ingest_batch_id='lost-response'").fetchone()[0] == 1


def test_same_dedup_key_in_different_batches_is_at_least_once(tmp_path):
    db_path = tmp_path / "cross-batch-semantics.db"
    StorageRepository(db_path).migrate()
    writer = IngestWriter(db_path=db_path, coalesce_ms=0)
    trace = _trace(59)
    try:
        first = writer.submit([trace], batch_id="different-a", node="node")
        second = writer.submit([trace], batch_id="different-b", node="node")
        assert first.inserted == second.inserted == 1
        with get_connection(db_path) as db:
            row = db.execute(
                "SELECT count(),uniqExact(dedup_key),uniqExact(ingest_batch_id) "
                "FROM traces WHERE dedup_key=?",
                (trace.dedup_key,),
            ).fetchone()
        # Batch IDs are the idempotency boundary. A repeated span in a different
        # batch is intentionally stored and counted twice under current semantics.
        assert tuple(row) == (2, 1, 2)
    finally:
        writer.shutdown()


def test_retry_in_different_coalesced_insert_block_is_duplicate(tmp_path):
    db_path = tmp_path / "different-block-retry.db"
    StorageRepository(db_path).migrate()
    db = get_connection(db_path)
    writer = IngestWriter(db_path=db_path)
    existing = {row[0] for row in db.client.query(f"DESCRIBE TABLE {db.database}.traces").result_rows}
    columns = [column for column in writer._TRACE_COLUMNS if column in existing]

    original = _WriteRequest([_trace(60)], batch_id="block-retry", node="node")
    companion_a = _WriteRequest([_trace(61)], batch_id="block-a", node="node")
    writer._write(db, "", columns, [original, companion_a])
    retry = _WriteRequest([_trace(60)], batch_id="block-retry", node="node")
    companion_b = _WriteRequest([_trace(62)], batch_id="block-b", node="node")
    writer._write(db, "", columns, [companion_b, retry])

    assert retry.result == IngestWriteResult(inserted=0, duplicate=True)
    assert companion_b.result == IngestWriteResult(inserted=1, duplicate=False)
    assert db.execute("SELECT count() FROM traces WHERE ingest_batch_id='block-retry'").fetchone()[0] == 1


def test_concurrent_uploads_are_coalesced_and_batch_dedup_is_atomic(tmp_path):
    db_path = tmp_path / "coalesced.db"
    StorageRepository(db_path).migrate()
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

        with StorageRepository(db_path).connect() as db:
            assert db.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 21
            assert db.execute(
                "SELECT COUNT(*) FROM ingest_batches WHERE batch_id=?", (shared_batch_id,)
            ).fetchone()[0] == 1
    finally:
        writer.shutdown()


def test_writer_flushes_before_coalesced_byte_cap(tmp_path, monkeypatch):
    db_path = tmp_path / "byte-cap.db"
    StorageRepository(db_path).migrate()
    writer = IngestWriter(
        db_path=db_path,
        coalesce_ms=100,
        transaction_records=100,
        max_batch_bytes=10,
    )
    requests = [
        _WriteRequest([_trace(700)], estimated_bytes=6),
        _WriteRequest([_trace(701)], estimated_bytes=4),
        _WriteRequest([_trace(702)], estimated_bytes=1),
    ]
    written = []

    def capture_write(_db, _insert_sql, _columns, jobs):
        written.append([job.estimated_bytes for job in jobs])

    monkeypatch.setattr(writer, "_write", capture_write)
    for request in requests:
        writer._queue.put(request)
    writer._queue.put(None)

    writer._run()

    assert written == [[6, 4], [1]]
    assert writer.snapshot()["transaction_byte_limit"] == 10


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
    StorageRepository(db_path).migrate()
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
