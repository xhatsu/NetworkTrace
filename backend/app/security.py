from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from backend.config import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Require X-API-Key for mutations when OTEL_API_KEY is configured."""
    if settings.api_key and (
        x_api_key is None or not hmac.compare_digest(x_api_key, settings.api_key)
    ):
        raise HTTPException(status_code=401, detail="Valid X-API-Key required")
