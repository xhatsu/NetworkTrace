from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def epoch_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


class QueryFilters(BaseModel):
    start: datetime
    end: datetime
    timezone: str = Field(default="UTC", max_length=64)
    environment: str | None = Field(default=None, max_length=100)
    group: str | None = Field(default=None, max_length=150)
    module: str | None = Field(default=None, max_length=150)
    service: str | None = Field(default=None, max_length=200)
    operation: str | None = Field(default=None, max_length=500)
    account: str | None = Field(default=None, max_length=300)
    comparison: Literal["previous", "week", "none"] = "previous"

    @model_validator(mode="after")
    def valid_range(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if (self.end - self.start).total_seconds() > 31 * 86400:
            raise ValueError("interactive range cannot exceed 31 days")
        return self

    @property
    def start_ms(self) -> int:
        return epoch_ms(self.start)

    @property
    def end_ms(self) -> int:
        return epoch_ms(self.end)


class AnomalyPatch(BaseModel):
    status: Literal["open", "acknowledged", "resolved", "suppressed"]
    suppressed_until: datetime | None = None

    @model_validator(mode="after")
    def suppression_expiry(self):
        if self.status == "suppressed" and self.suppressed_until is None:
            raise ValueError("suppressed_until is required")
        return self


class Page(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=1_000_000)

