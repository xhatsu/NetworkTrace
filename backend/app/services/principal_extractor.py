"""Offer a compatibility identity extractor that always returns scrubbed values."""
from __future__ import annotations

from typing import Any

from backend.app.services.normalization import extract_principal


def extract_principal_name(authorization_header: Any) -> tuple[str, str]:
    """Return a scrubbed principal and its initial neutral classification."""
    return extract_principal(authorization_header, fallback_user=None), "unknown"
