"""Bounded ClickHouse persistence for versioned semantic episode assessments."""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Any, Iterator

from backend.app.models.semantic_assessment import SemanticAssessmentV1
from backend.app.repositories.db_context import get_connection


HEX64 = re.compile(r"^[0-9a-f]{64}$")
TABLE_COLUMNS = (
    "episode_key", "episode_version", "assessment_version", "provider", "provider_model", "provider_request_id",
    "status", "abnormal_probability", "category", "category_confidence", "category_probabilities",
    "recommendation", "recommendation_confidence", "recommendation_probabilities", "input_signal_ids",
    "priority", "priority_confidence", "priority_probabilities", "summary",
    "supporting_signal_ids", "caveats", "input_digest", "response_digest",
    "input_tokens", "output_tokens", "cost_usd", "evaluated_at_ms", "created_at_ms", "updated_at_ms",
)
QUERY_SETTINGS = {
    "max_execution_time": 2,
    "max_rows_to_read": 100000,
    "max_result_rows": 10000,
    "max_memory_usage": 67108864,
    "read_overflow_mode": "throw",
    "result_overflow_mode": "throw",
}


def _row_to_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "items"):
        return dict(row.items())
    return dict(zip(columns, row))


def assessment_from_row(row: dict[str, Any]) -> SemanticAssessmentV1:
    evaluated = int(row.get("evaluated_at_ms") or 0)
    return SemanticAssessmentV1(
        status=row.get("status"),
        provider=row.get("provider") or None,
        provider_model=row.get("provider_model") or None,
        provider_request_id=row.get("provider_request_id") or None,
        assessment_version=row.get("assessment_version") or "semantic-v1",
        episode_version=bytes(row["episode_version"]).rstrip(b"\x00").decode() if isinstance(row.get("episode_version"), bytes) else str(row.get("episode_version") or "").rstrip("\x00") or None,
        abnormal_probability=float(row["abnormal_probability"]) if row.get("abnormal_probability") is not None else None,
        category=row.get("category") or None,
        category_confidence=float(row["category_confidence"]) if row.get("category_confidence") is not None else None,
        category_probabilities={str(key): float(value) for key, value in dict(row.get("category_probabilities") or {}).items()},
        priority=row.get("priority") or None,
        priority_confidence=float(row["priority_confidence"]) if row.get("priority_confidence") is not None else None,
        priority_probabilities={str(key): float(value) for key, value in dict(row.get("priority_probabilities") or {}).items()},
        recommendation=row.get("recommendation") or None,
        recommendation_confidence=row.get("recommendation_confidence"),
        recommendation_probabilities=dict(row.get("recommendation_probabilities") or {}),
        input_signal_ids=list(row.get("input_signal_ids") or []),
        summary=row.get("summary") or None,
        supporting_signal_ids=list(row.get("supporting_signal_ids") or []),
        caveats=list(row.get("caveats") or []),
        input_tokens=int(row["input_tokens"]) if row.get("input_tokens") is not None else None,
        output_tokens=int(row["output_tokens"]) if row.get("output_tokens") is not None else None,
        cost_usd=float(row["cost_usd"]) if row.get("cost_usd") is not None else None,
        evaluated_at=evaluated or None,
    )


class SemanticAssessmentRepository:
    def __init__(self, db_path: str | None = None, connection_factory: Any = None):
        self.db_path = db_path
        self._connection_factory = connection_factory or get_connection

    @contextmanager
    def _client(self) -> Iterator[Any]:
        with self._connection_factory(self.db_path) as connection:
            yield connection.client

    @staticmethod
    def _query(client: Any, sql: str, parameters: dict[str, Any] | None = None) -> Any:
        return client.query(sql, parameters=parameters or {}, settings=QUERY_SETTINGS)

    def get_latest(self, episode_key: str, episode_version: str) -> dict[str, Any] | None:
        if not HEX64.fullmatch(episode_version):
            raise ValueError("episode_version must be lowercase SHA-256 hex")
        sql = """SELECT * FROM semantic_assessments FINAL
                 WHERE episode_key = {episode_key:String}
                   AND episode_version = {episode_version:FixedString(64)}
                   AND assessment_version = 'semantic-v1'
                 ORDER BY updated_at_ms DESC LIMIT 1"""
        with self._client() as client:
            result = self._query(client, sql, {"episode_key": episode_key, "episode_version": episode_version})
            if not result.result_rows:
                return None
            return _row_to_dict(result.result_rows[0], list(result.column_names))

    def get_latest_many(self, episode_keys: list[str]) -> list[dict[str, Any]]:
        keys = list(dict.fromkeys(key for key in episode_keys if key))
        if not keys:
            return []
        # The API returns at most 500 episodes; allow bounded version history while
        # keeping one ClickHouse round trip for the entire page.
        limit = min(10000, max(1000, len(keys) * 20))
        sql = """SELECT * FROM semantic_assessments FINAL
                 WHERE episode_key IN {episode_keys:Array(String)}
                   AND assessment_version = 'semantic-v1'
                 ORDER BY updated_at_ms DESC LIMIT {limit:UInt32}"""
        with self._client() as client:
            result = self._query(client, sql, {"episode_keys": keys, "limit": limit})
            return [_row_to_dict(row, list(result.column_names)) for row in result.result_rows]

    def save(self, episode_key: str, assessment: SemanticAssessmentV1, *, provider_model: str,
             input_digest: str, response_digest: str | None = None, created_at_ms: int | None = None) -> None:
        if assessment.status not in {"pending", "succeeded", "failed"}:
            raise ValueError("only pending, succeeded, and failed assessments can be persisted")
        if not assessment.episode_version or not HEX64.fullmatch(assessment.episode_version):
            raise ValueError("assessment must contain a lowercase SHA-256 episode_version")
        if not HEX64.fullmatch(input_digest) or (response_digest is not None and not HEX64.fullmatch(response_digest)):
            raise ValueError("assessment digests must be lowercase SHA-256 hex")
        now_ms = int(time.time() * 1000)
        # ReplacingMergeTree resolves updates by updated_at_ms. Keep that value
        # strictly increasing across pending -> result transitions, even when
        # the provider responds within the same wall-clock millisecond.
        current = self.get_latest(episode_key, assessment.episode_version)
        created = created_at_ms or int((current or {}).get("created_at_ms") or now_ms)
        updated = max(now_ms, int((current or {}).get("updated_at_ms") or 0) + 1)
        values = [
            episode_key, assessment.episode_version, assessment.assessment_version,
            assessment.provider or "jev", assessment.provider_model or provider_model,
            assessment.provider_request_id or "", assessment.status,
            assessment.abnormal_probability, assessment.category or "", assessment.category_confidence,
            assessment.category_probabilities,
            assessment.recommendation or "", assessment.recommendation_confidence,
            assessment.recommendation_probabilities, assessment.input_signal_ids,
            assessment.priority or "", assessment.priority_confidence,
            assessment.priority_probabilities, assessment.summary or "", assessment.supporting_signal_ids,
            assessment.caveats, input_digest, response_digest, assessment.input_tokens or 0,
            assessment.output_tokens or 0, assessment.cost_usd, assessment.evaluated_at or 0, created, updated,
        ]
        with self._client() as client:
            client.insert("semantic_assessments", [values], column_names=list(TABLE_COLUMNS))

    def mark_pending(self, episode_key: str, episode_version: str, *, input_digest: str,
                     provider_model: str = "") -> None:
        self.save(
            episode_key,
            SemanticAssessmentV1(status="pending", provider="jev", episode_version=episode_version),
            provider_model=provider_model,
            input_digest=input_digest,
        )

    def mark_failed(self, episode_key: str, episode_version: str, *, input_digest: str,
                    provider_model: str = "", evaluated_at_ms: int | None = None) -> None:
        self.save(
            episode_key,
            SemanticAssessmentV1(status="failed", provider="jev", episode_version=episode_version,
                                 evaluated_at=evaluated_at_ms or int(time.time() * 1000)),
            provider_model=provider_model,
            input_digest=input_digest,
        )
