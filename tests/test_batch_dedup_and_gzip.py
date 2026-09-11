from __future__ import annotations

import asyncio
import gzip
import json
import time
import httpx
import pytest

from backend.main import app
from backend.repository import SQLiteRepository
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.repositories.ingest_batch_repository import IngestBatchRepository


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    SQLiteRepository().migrate()


@pytest.fixture
def client():
    class Client:
        @staticmethod
        def request(method, url, **kwargs):
            async def send():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as session:
                    return await session.request(method, url, **kwargs)
            return asyncio.run(send())

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

    return Client()


def test_batch_repository_unit_operations(tmp_path):
    db_file = str(tmp_path / "test_batches.db")
    SQLiteRepository(db_file).migrate()
    repo = IngestBatchRepository(db_file)
    IngestBatchRepository.clear_cache()

    batch_id = "test-node-inst1-100"
    assert repo.is_batch_processed(batch_id) is False

    ok = repo.record_batch(batch_id, node="node-1", record_count=5)
    assert ok is True

    # Immediate check via cache
    assert repo.is_batch_processed(batch_id) is True

    # Clear cache and check via DB query
    IngestBatchRepository.clear_cache()
    assert repo.is_batch_processed(batch_id) is True

    batch_meta = repo.get_batch(batch_id)
    assert batch_meta is not None
    assert batch_meta["batch_id"] == batch_id
    assert batch_meta["node"] == "node-1"
    assert batch_meta["record_count"] == 5
    assert batch_meta["status"] == "accepted"

    # Prune test
    pruned = repo.prune_batches(older_than_ms=int(time.time() * 1000) + 1000)
    assert pruned == 1
    IngestBatchRepository.clear_cache()
    assert repo.is_batch_processed(batch_id) is False


def test_gzip_ingest_and_deduplication(client):
    batch_id = f"test-cpp-shipper-{int(time.time() * 1000)}"
    payload = {
        "node": "payment-node01",
        "events": [{
            "ts": int(time.time()),
            "path": "/api/v1/checkout",
            "method": "POST",
            "user": "shipper_test_user",
            "scheme": "wsse",
            "caller": "10.10.10.5",
            "caller_port": 40123,
            "dst_ip": "10.20.20.10",
            "dst_port": 8080,
            "status": 200,
            "duration_ms": 25,
            "traceparent": "00-11223344556677889900aabbccddeeff-0123456789abcdef-01",
        }]
    }

    body_bytes = json.dumps(payload).encode("utf-8")
    gzipped_bytes = gzip.compress(body_bytes)

    # First request: uncompressed body check or gzipped
    headers = {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
        "X-Batch-Id": batch_id,
    }
    resp1 = client.post("/api/ingest", content=gzipped_bytes, headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["status"] == "success"
    assert data1["ok"] is True
    assert data1["duplicate"] is False
    assert data1["batch_id"] == batch_id
    assert data1["inserted"] >= 1

    # Second request: identical X-Batch-Id (simulating shipper retry)
    resp2 = client.post("/api/ingest", content=gzipped_bytes, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "success"
    assert data2["ok"] is True
    assert data2["duplicate"] is True
    assert data2["batch_id"] == batch_id
    assert data2["inserted"] == 0
    assert data2["received"] == 0


def test_corrupted_gzip_returns_http_400(client):
    bad_bytes = b"\x1f\x8b\x08\x00corrupted-junk-payload"
    headers = {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
        "X-Batch-Id": f"corrupt-{int(time.time() * 1000)}"
    }
    resp = client.post("/api/ingest", content=bad_bytes, headers=headers)
    assert resp.status_code == 400
    assert "Invalid gzip" in resp.text or "gzip" in resp.text.lower()


def test_magic_bytes_gzip_without_header(client):
    batch_id = f"magic-test-{int(time.time() * 1000)}"
    payload = {
        "node": "magic-node",
        "events": [{
            "ts": int(time.time()),
            "path": "/magic/health",
            "status": 200
        }]
    }
    gzipped_bytes = gzip.compress(json.dumps(payload).encode("utf-8"))
    # No Content-Encoding header provided, only magic bytes \x1f\x8b
    headers = {
        "Content-Type": "application/json",
        "X-Batch-Id": batch_id
    }
    resp = client.post("/api/v1/ingest", content=gzipped_bytes, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["inserted"] == 1
