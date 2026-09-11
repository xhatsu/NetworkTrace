from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx

from backend.app.application import ROLE_AGENT_STATS, ROLE_ALL, ROLE_INGEST, create_app
from backend.app.services.storage_owner_client import storage_owner_client
from backend.repository import SQLiteRepository


def _request(app, method: str, path: str, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def _enable_remote(monkeypatch) -> None:
    monkeypatch.setattr(type(storage_owner_client), "enabled", property(lambda _self: True))


def test_ingestion_edge_normalizes_then_forwards_without_sqlite(monkeypatch):
    _enable_remote(monkeypatch)
    captured = {}

    async def commit(traces, batch_id, node):
        captured.update(traces=traces, batch_id=batch_id, node=node)
        return {"inserted": len(traces), "duplicate": False}

    monkeypatch.setattr(storage_owner_client, "commit_traces", commit)
    response = _request(
        create_app(ROLE_INGEST),
        "POST",
        "/api/v1/ingest",
        headers={"X-Batch-Id": "edge-batch-1"},
        json={
            "ts": 1_787_900_000,
            "service": "edge-service",
            "path": "/edge",
            "trace_id": "a" * 32,
            "span_id": "b" * 16,
            "status": 200,
            "duration_ms": 4,
        },
    )
    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    assert captured["batch_id"] == "edge-batch-1"
    assert captured["traces"][0].service_name == "edge-service"


def test_agent_edge_forwards_lifecycle_operations(monkeypatch):
    _enable_remote(monkeypatch)
    calls: list[str] = []
    sample = {
        "schema_version": 1,
        "type": "agent_stats",
        "node": "edge-node",
        "instance_id": "instance-1",
        "sequence": 7,
        "observed_at": 1_787_900_000,
        "window_seconds": 30,
        "status": "ok",
        "reasons": [],
    }

    async def store(body):
        calls.append("store")
        assert body == sample
        return {"accepted": True}

    async def latest(node=None, instance_id=None):
        calls.append("latest")
        return [sample]

    async def history(node, limit, instance_id=None):
        calls.append("history")
        return [sample]

    async def delete(node, instance_id=None):
        calls.append("delete")
        return {"deleted": True, "deleted_latest": 1, "deleted_history": 1}

    monkeypatch.setattr(storage_owner_client, "store_agent_sample", store)
    monkeypatch.setattr(storage_owner_client, "agent_latest", latest)
    monkeypatch.setattr(storage_owner_client, "agent_history", history)
    monkeypatch.setattr(storage_owner_client, "delete_agent", delete)
    app = create_app(ROLE_AGENT_STATS)
    assert _request(app, "POST", "/api/agent/stats", json=sample).json()["accepted"] is True
    assert _request(app, "GET", "/api/agent/stats").json()["count"] == 1
    assert _request(app, "GET", "/api/agent/stats/edge-node/history").json()["count"] == 1
    assert _request(app, "DELETE", "/api/agent/stats/edge-node").status_code == 200
    assert calls == ["store", "latest", "history", "delete"]


def test_internal_agent_storage_requires_token_and_deduplicates(monkeypatch):
    import backend.app.api.internal_storage as internal_storage

    SQLiteRepository().migrate()
    token = "test-internal-token"
    monkeypatch.setattr(
        internal_storage,
        "settings",
        SimpleNamespace(internal_api_token=token, demo_mode=True),
    )
    sample = {
        "schema_version": 1,
        "type": "agent_stats",
        "node": "internal-{}".format(uuid4().hex),
        "instance_id": "instance-1",
        "sequence": 1,
        "observed_at": 1_787_900_000,
        "window_seconds": 30,
        "status": "ok",
        "reasons": [],
    }
    app = create_app(ROLE_ALL)
    unauthorized = _request(app, "POST", "/internal/v1/agent-stats/samples", json=sample)
    assert unauthorized.status_code == 401
    headers = {"X-TraceScope-Internal-Token": token}
    first = _request(app, "POST", "/internal/v1/agent-stats/samples", json=sample, headers=headers)
    replay = _request(app, "POST", "/internal/v1/agent-stats/samples", json=sample, headers=headers)
    assert first.json() == {"accepted": True}
    assert replay.json() == {"accepted": False}
