from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx

from backend.app.application import ROLE_AGENT_STATS, ROLE_ALL, ROLE_INGEST, create_app
from backend.app.services.ingest_writer import ingest_writer
from backend.app.services.storage_owner_client import storage_owner_client
from backend.repository import StorageRepository


def test_split_apps_use_authenticated_storage_boundary_end_to_end(monkeypatch):
    """Exercise all three ASGI workloads with the real SQLite repositories."""
    import backend.app.api.internal_storage as internal_storage
    import backend.app.services.storage_owner_client as client_module

    StorageRepository().migrate()
    token = "integration-internal-token"
    monkeypatch.setattr(
        internal_storage,
        "settings",
        SimpleNamespace(internal_api_token=token, demo_mode=True),
    )
    monkeypatch.setattr(
        client_module,
        "settings",
        SimpleNamespace(
            storage_owner_url="http://storage-owner",
            internal_api_token=token,
            internal_request_timeout_seconds=10,
        ),
    )

    storage_app = create_app(ROLE_ALL)
    ingest_app = create_app(ROLE_INGEST)
    agent_app = create_app(ROLE_AGENT_STATS)

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=storage_app)
        storage_owner_client._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://storage-owner",
            timeout=10,
        )
        ingest_writer.start()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ingest_app), base_url="http://ingest"
            ) as ingest:
                trace_id = uuid4().hex
                batch_id = "split-integration-{}".format(uuid4().hex)
                trace = {
                    "ts": 1_787_900_100,
                    "service": "split-integration-service",
                    "path": "/split",
                    "trace_id": trace_id,
                    "span_id": uuid4().hex[:16],
                    "status": 200,
                    "duration_ms": 5,
                }
                headers = {"X-Batch-Id": batch_id}
                first = await ingest.post("/api/v1/ingest", json=trace, headers=headers)
                replay = await ingest.post("/api/v1/ingest", json=trace, headers=headers)
                assert first.status_code == 200
                assert first.json()["inserted"] == 1
                assert replay.status_code == 200
                assert replay.json()["duplicate"] is True

                import time

                node = "split-node-{}".format(uuid4().hex)
                sample = {
                    "schema_version": 1,
                    "type": "agent_stats",
                    "node": node,
                    "instance_id": "split-instance",
                    "sequence": 1,
                    "observed_at": int(time.time()),
                    "window_seconds": 30,
                    "status": "ok",
                    "reasons": [],
                }
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=agent_app), base_url="http://agent"
            ) as agent:
                accepted = await agent.post("/api/agent/stats", json=sample)
                duplicate = await agent.post("/api/agent/stats", json=sample)
                history = await agent.get("/api/agent/stats/{}/history".format(node))
                deleted = await agent.delete(
                    "/api/agent/stats/{}/split-instance".format(node)
                )
                assert accepted.json()["accepted"] is True
                assert duplicate.json()["accepted"] is False
                assert history.json()["count"] == 1
                assert deleted.status_code == 200
                assert deleted.json()["deleted"] is True
        finally:
            ingest_writer.shutdown()
            await storage_owner_client.shutdown()

    asyncio.run(exercise())
