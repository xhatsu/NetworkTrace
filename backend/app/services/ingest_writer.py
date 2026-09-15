"""Bounded, coalescing ClickHouse writer for high-throughput HTTP ingestion.

ClickHouse is TraceScope's single live store. Coalescing nearby uploads into
large block inserts amortizes part creation and network overhead; bounded
admission turns overload into explicit retryable backpressure instead of
unbounded memory growth. A response is released only after the block insert
returns, preserving the durable-commit contract for shippers that retry.
"""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.db_context import get_connection
from backend.app.repositories.ingest_batch_repository import IngestBatchRepository


class IngestQueueFull(RuntimeError):
    """Raised when bounded admission control rejects an upload."""


class IngestCommitTimeout(RuntimeError):
    """Raised when a queued upload does not finish within the response deadline."""


@dataclass(frozen=True)
class IngestWriteResult:
    inserted: int
    duplicate: bool = False


@dataclass
class _WriteRequest:
    traces: List[NormalizedTrace]
    batch_id: str = ""
    node: str = "unknown"
    estimated_bytes: int = 0
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[IngestWriteResult] = None
    error: Optional[BaseException] = None

    def __post_init__(self) -> None:
        if self.estimated_bytes <= 0:
            self.estimated_bytes = sum(
                len(trace.model_dump_json().encode("utf-8")) for trace in self.traces
            )


class IngestWriter:
    """One process-local ClickHouse block writer with bounded request admission."""

    _TRACE_COLUMNS = [
        "ingest_batch_id",
        "event_uid", "timestamp", "timestamp_ms", "trace_id", "span_id", "parent_span_id",
        "service_name", "service_instance", "service_environment",
        "caller_service", "caller_instance", "caller_ip",
        "target_service", "target_instance", "target_ip", "target_port",
        "principal_name", "operation", "http_method", "http_route",
        "http_status", "status_class", "duration_ms", "duration_us", "outcome",
        "protocol", "span_kind", "attributes_json", "created_at",
        "environment", "principal_id", "identity_source",
        "auth_result", "auth_evidence", "caller_resolution_method", "caller_confidence",
        "network_peer_ip", "original_client_ip", "original_client_ip_trusted",
        "source_group", "operation_key", "soap_fault_code", "outcome_class",
        "sampling_context", "dedup_key",
    ]

    def __init__(
        self,
        db_path: Path | str | None = None,
        queue_capacity: Optional[int] = None,
        coalesce_ms: Optional[int] = None,
        transaction_records: Optional[int] = None,
        max_batch_bytes: Optional[int] = None,
        commit_timeout_seconds: Optional[float] = None,
    ) -> None:
        self.db_path = db_path
        self.queue_capacity = queue_capacity or settings.ingest_queue_capacity
        self.coalesce_seconds = (
            settings.ingest_coalesce_ms if coalesce_ms is None else max(0, coalesce_ms)
        ) / 1000.0
        self.transaction_records = transaction_records or settings.ingest_transaction_records
        self.max_batch_bytes = max_batch_bytes or settings.ingest_max_batch_bytes
        self.commit_timeout_seconds = commit_timeout_seconds or settings.ingest_commit_timeout_seconds
        self._queue: queue.Queue[Optional[_WriteRequest]] = queue.Queue(maxsize=self.queue_capacity)
        self._state_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stats: Dict[str, int] = {
            "accepted_requests": 0,
            "rejected_requests": 0,
            "committed_requests": 0,
            "committed_records": 0,
            "duplicate_requests": 0,
            "write_transactions": 0,
            "failed_requests": 0,
        }

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run,
                name="tracescope-ingest-writer",
                daemon=True,
            )
            self._thread.start()

    def shutdown(self, timeout: float = 10.0) -> None:
        with self._state_lock:
            thread = self._thread
            if thread is None or not thread.is_alive():
                self._thread = None
                return
        try:
            self._queue.put(None, timeout=max(0.1, timeout))
        except queue.Full:
            return
        thread.join(timeout=max(0.1, timeout))
        with self._state_lock:
            if not thread.is_alive():
                self._thread = None

    def submit(
        self,
        traces: List[NormalizedTrace],
        batch_id: str = "",
        node: str = "unknown",
    ) -> IngestWriteResult:
        self.start()
        request = _WriteRequest(traces=traces, batch_id=batch_id, node=node)
        try:
            self._queue.put_nowait(request)
        except queue.Full as exc:
            self._increment("rejected_requests")
            raise IngestQueueFull("Ingestion queue is full; retry with backoff") from exc
        self._increment("accepted_requests")
        if not request.done.wait(self.commit_timeout_seconds):
            raise IngestCommitTimeout("Timed out waiting for ingestion commit")
        if request.error is not None:
            raise request.error
        if request.result is None:
            raise RuntimeError("Ingestion writer completed without a result")
        return request.result

    async def submit_async(
        self,
        traces: List[NormalizedTrace],
        batch_id: str = "",
        node: str = "unknown",
    ) -> IngestWriteResult:
        """Queue a write without blocking the ASGI event loop while it awaits durability."""
        self.start()
        request = _WriteRequest(
            traces=traces,
            batch_id=batch_id,
            node=node,
        )
        try:
            self._queue.put_nowait(request)
        except queue.Full as exc:
            self._increment("rejected_requests")
            raise IngestQueueFull("Ingestion queue is full; retry with backoff") from exc
        self._increment("accepted_requests")
        deadline = time.monotonic() + self.commit_timeout_seconds
        poll_delay = 0.001
        while not request.done.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IngestCommitTimeout("Timed out waiting for ingestion commit")
            await asyncio.sleep(min(poll_delay, remaining))
            poll_delay = min(0.01, poll_delay * 2)
        if request.error is not None:
            raise request.error
        if request.result is None:
            raise RuntimeError("Ingestion writer completed without a result")
        return request.result

    def snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            stats: Dict[str, Any] = dict(self._stats)
            stats["writer_alive"] = bool(self._thread and self._thread.is_alive())
        stats["queue_depth"] = self._queue.qsize()
        stats["queue_capacity"] = self.queue_capacity
        stats["coalesce_ms"] = int(self.coalesce_seconds * 1000)
        stats["transaction_record_limit"] = self.transaction_records
        stats["transaction_byte_limit"] = self.max_batch_bytes
        return stats

    def _increment(self, key: str, amount: int = 1) -> None:
        with self._state_lock:
            self._stats[key] += amount

    def _run(self) -> None:
        db = None
        columns: List[str] = []
        pending: Optional[_WriteRequest] = None
        try:
            while True:
                first = pending if pending is not None else self._queue.get()
                pending = None
                if first is None:
                    self._queue.task_done()
                    break

                jobs = [first]
                record_count = len(first.traces)
                estimated_bytes = first.estimated_bytes
                # A short window favors one efficient ClickHouse block without delaying uploads indefinitely.
                deadline = time.monotonic() + self.coalesce_seconds
                should_stop = False
                while record_count < self.transaction_records:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        job = self._queue.get(timeout=remaining)
                    except queue.Empty:
                        break
                    if job is None:
                        self._queue.task_done()
                        should_stop = True
                        break
                    next_record_count = record_count + len(job.traces)
                    next_estimated_bytes = estimated_bytes + job.estimated_bytes
                    if (
                        next_record_count > self.transaction_records
                        or next_estimated_bytes > self.max_batch_bytes
                    ):
                        pending = job
                        break
                    jobs.append(job)
                    record_count = next_record_count
                    estimated_bytes = next_estimated_bytes

                try:
                    if db is None:
                        db = get_connection(self.db_path)
                        existing = {row[0] for row in db.client.query(f"DESCRIBE TABLE {db.database}.traces").result_rows}
                        columns = [column for column in self._TRACE_COLUMNS if column in existing]
                    self._write(db, "", columns, jobs)
                except BaseException as exc:
                    self._increment("failed_requests", len(jobs))
                    for job in jobs:
                        job.error = exc
                        job.done.set()
                    if db is not None:
                        db.close()
                        db = None
                for job in jobs:
                    self._queue.task_done()
                if should_stop:
                    break
        finally:
            if db is not None:
                db.close()

    def _write(self, db, insert_sql: str, columns: List[str], jobs: List[_WriteRequest]) -> None:
        completed: List[tuple[_WriteRequest, IngestWriteResult]] = []
        batch_repo = IngestBatchRepository(self.db_path)
        seen_in_batch: set[str] = set()

        valid_jobs: List[_WriteRequest] = []
        batch_rows: List[list[Any]] = []
        now_ms = int(time.time() * 1000)

        for job in jobs:
            # Remember IDs within this block as well as prior blocks: concurrent retries
            # must observe the same duplicate result without inserting twice.
            if job.batch_id:
                stored_result = db.client.query(
                    "SELECT count() FROM traces WHERE ingest_batch_id = {batch_id:String}",
                    parameters={"batch_id": job.batch_id},
                )
                stored_rows = int(stored_result.result_rows[0][0]) if stored_result.result_rows else 0
                if job.batch_id in seen_in_batch or batch_repo.is_batch_processed(job.batch_id) or stored_rows:
                    if stored_rows and not batch_repo.is_batch_processed(job.batch_id):
                        batch_rows.append([job.batch_id, job.node, int(stored_rows), now_ms, "accepted"])
                    completed.append((job, IngestWriteResult(inserted=0, duplicate=True)))
                    continue
                seen_in_batch.add(job.batch_id)
                batch_rows.append([job.batch_id, job.node, len(job.traces), now_ms, "accepted"])
            valid_jobs.append(job)

        all_trace_rows: List[list[Any]] = []
        for job in valid_jobs:
            for trace in job.traces:
                if settings.clickhouse_only_agent_traces:
                    is_agent = getattr(trace, "is_agent_trace", False) or (job.node not in {"unknown", "otlp", "elastic", "apm", ""})
                    if not is_agent:
                        continue
                all_trace_rows.append(_trace_to_row(trace, columns, job.batch_id))

        try:
            if all_trace_rows:
                # Persist evidence first. A retry can reconstruct a missing marker from ingest_batch_id.
                db.client.insert(
                    "traces",
                    all_trace_rows,
                    column_names=columns,
                    database=db.database,
                )
            if batch_rows:
                db.client.insert(
                    "ingest_batches",
                    batch_rows,
                    column_names=["batch_id", "node", "record_count", "received_at_ms", "status"],
                    database=db.database,
                )
            for job in valid_jobs:
                completed.append((job, IngestWriteResult(inserted=len(job.traces), duplicate=False)))
        except BaseException as exc:
            self._increment("failed_requests", len(jobs))
            for job in jobs:
                job.error = exc
                job.done.set()
            return

        self._increment("write_transactions")
        for job, result in completed:
            if job.batch_id and not result.duplicate:
                IngestBatchRepository.cache_batch(job.batch_id)
            if result.duplicate:
                self._increment("duplicate_requests")
            else:
                self._increment("committed_records", result.inserted)
            self._increment("committed_requests")
            job.result = result
            job.done.set()
        batch_repo._maybe_prune()


_DEFAULTS: Dict[str, Any] = {
    "attributes_json": "{}",
    "service_environment": "production",
    "environment": "production",
    "principal_name": "unknown",
    "principal_id": "",
    "identity_source": "unknown",
    "auth_result": "unknown",
    "auth_evidence": "unknown",
    "caller_resolution_method": "none",
    "caller_confidence": 0.0,
    "original_client_ip_trusted": 0,
    "operation_key": "unknown",
    "outcome_class": "unknown",
    "protocol": "http",
    "span_kind": "server",
    "status_class": "unknown",
    "outcome": "unknown",
}


def _trace_to_row(trace: NormalizedTrace, columns: List[str], batch_id: str = "") -> list[Any]:
    row = []
    for col in columns:
        if col == "ingest_batch_id":
            row.append(batch_id)
            continue
        val = getattr(trace, col, None)
        if val is None and col in _DEFAULTS:
            val = _DEFAULTS[col]
        row.append(val)
    return row


ingest_writer = IngestWriter()
