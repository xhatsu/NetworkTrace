from datetime import datetime, timedelta, timezone

from backend.models import AnomalyPatch, QueryFilters
import pytest


def test_query_range_is_bounded():
    with pytest.raises(ValueError):
        QueryFilters(start=datetime.now(timezone.utc)-timedelta(days=32),end=datetime.now(timezone.utc))


def test_suppression_requires_expiry():
    with pytest.raises(ValueError): AnomalyPatch(status="suppressed")

