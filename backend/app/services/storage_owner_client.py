"""Async client for the optional authenticated storage-owner boundary.

ClickHouse is the canonical store, but this client preserves an isolation mode
for deployments that centralize durable operations. Edge receivers can validate
and normalize without inheriting storage credentials or internal-only routes.
"""
from __future__ import annotations

from typing import Any

import httpx

from backend.config import settings
from backend.app.models.trace import NormalizedTrace


class StorageOwnerError(RuntimeError):
    def __init__(self, status_code: int, detail: str, retry_after: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


class StorageOwnerClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.storage_owner_url)

    async def start(self) -> None:
        if self.enabled and self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.storage_owner_url,
                timeout=settings.internal_request_timeout_seconds,
            )

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        await self.start()
        if self._client is None:
            raise StorageOwnerError(503, "Storage owner is not configured", "1")
        headers = dict(kwargs.pop("headers", {}))
        # The token distinguishes trusted role-to-role calls from the public API surface.
        headers["X-TraceScope-Internal-Token"] = settings.internal_api_token
        try:
            response = await self._client.request(method, path, headers=headers, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise StorageOwnerError(503, "Storage owner is unavailable", "1") from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = str(payload.get("detail") or payload.get("error") or response.text)
            except ValueError:
                detail = response.text or "Storage owner request failed"
            raise StorageOwnerError(
                response.status_code,
                detail,
                response.headers.get("retry-after"),
            )
        try:
            return response.json()
        except ValueError as exc:
            raise StorageOwnerError(502, "Storage owner returned invalid JSON", "1") from exc

    async def ready(self) -> bool:
        try:
            result = await self._request("GET", "/internal/v1/readyz")
            return result.get("status") == "ready"
        except StorageOwnerError:
            return False

    async def commit_traces(
        self, traces: list[NormalizedTrace], batch_id: str, node: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/internal/v1/traces/commit",
            json={
                "traces": [trace.model_dump(mode="json") for trace in traces],
                "batch_id": batch_id,
                "node": node,
            },
        )

    async def ingestion_status(self) -> dict[str, Any]:
        return await self._request("GET", "/internal/v1/ingestion/status")

    async def store_agent_sample(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/internal/v1/agent-stats/samples", json=body)

    async def agent_latest(
        self, node: str | None = None, instance_id: str | None = None
    ) -> list[dict[str, Any]]:
        params = {key: value for key, value in {"node": node, "instance_id": instance_id}.items() if value}
        return (await self._request("GET", "/internal/v1/agent-stats/latest", params=params))["items"]

    async def agent_history(
        self, node: str, limit: int, instance_id: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"node": node, "limit": limit}
        if instance_id:
            params["instance_id"] = instance_id
        return (await self._request("GET", "/internal/v1/agent-stats/history", params=params))["items"]

    async def delete_agent(
        self, node: str, instance_id: str | None = None
    ) -> dict[str, Any]:
        params = {"node": node}
        if instance_id:
            params["instance_id"] = instance_id
        return await self._request("DELETE", "/internal/v1/agent-stats", params=params)


storage_owner_client = StorageOwnerClient()
