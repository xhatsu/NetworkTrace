"""Bounded, append-only persistence for investigation state transitions."""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID

from backend.app.models.investigation import (
    MAX_EVIDENCE_BYTES,
    MAX_METADATA_BYTES,
    MAX_RESULT_BYTES,
    MAX_SNAPSHOT_BYTES,
    FindingRef,
    finding_key,
)
from backend.app.repositories.db_context import get_connection


TABLE_COLUMNS = (
    "id", "dedup_key", "retry_index", "retry_of", "finding_kind", "finding_id",
    "source_version", "snapshot_schema_version", "prompt_version", "result_schema_version",
    "policy_version", "provider", "configured_model", "reported_model", "state",
    "state_version", "cancel_requested", "created_at_ms", "updated_at_ms", "started_at_ms",
    "finished_at_ms", "deadline_ms", "expires_at", "snapshot_json", "evidence_json",
    "evidence_digest", "deterministic_summary_json", "result_json", "failure_code", "metadata_json",
)
NONTERMINAL = ("queued", "assembling", "generating", "validating")
TERMINAL = ("succeeded", "failed", "timed_out", "canceled", "source_changed", "source_closed", "source_superseded", "source_stale")
QUERY_SETTINGS = {
    "max_execution_time": 2,
    "max_rows_to_read": 100000,
    "max_result_rows": 1000,
    "max_memory_usage": 67108864,
    "read_overflow_mode": "throw",
    "result_overflow_mode": "throw",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _json_bytes(value: str | None, maximum: int, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
        raise ValueError("{} exceeds the investigation byte limit".format(name))
    # Ensure persisted payloads are canonical JSON and contain no NaN/Infinity.
    json.loads(value, object_pairs_hook=_reject_duplicate_keys,
               parse_constant=lambda token: (_ for _ in ()).throw(ValueError("non-finite JSON")))
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _row_to_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(row, dict):
        result = dict(row)
    elif hasattr(row, "items"):
        result = dict(row.items())
    else:
        result = dict(zip(columns, row))
    if isinstance(result.get("id"), UUID):
        result["id"] = str(result["id"])
    if isinstance(result.get("retry_of"), UUID):
        result["retry_of"] = str(result["retry_of"])
    if isinstance(result.get("expires_at"), datetime):
        result["expires_at"] = result["expires_at"].isoformat()
    for column in ("dedup_key", "source_version", "evidence_digest"):
        value = result.get(column)
        if isinstance(value, bytes):
            result[column] = value.rstrip(b"\x00").decode("utf-8")
    return result


class InvestigationRepository:
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

    def table_exists(self) -> bool:
        try:
            with self._client() as client:
                result = self._query(client, "SELECT name FROM system.tables WHERE database = currentDatabase() AND name = 'llm_investigations' LIMIT 1")
                return bool(result.result_rows)
        except Exception:
            return False

    def get(self, run_id: UUID | str, include_expired: bool = False) -> dict[str, Any] | None:
        expiry = "1=1" if include_expired else "expires_at > now()"
        sql = "SELECT * FROM llm_investigations FINAL WHERE id = {run_id:UUID} AND " + expiry + " LIMIT 1"
        with self._client() as client:
            result = self._query(client, sql, {"run_id": str(run_id)})
            if not result.result_rows:
                return None
            return _row_to_dict(result.result_rows[0], list(result.column_names))

    def get_by_dedup_key(self, dedup_key: str, include_expired: bool = False) -> dict[str, Any] | None:
        if len(dedup_key) != 64:
            raise ValueError("invalid dedup key")
        expiry = "1=1" if include_expired else "expires_at > now()"
        sql = "SELECT * FROM llm_investigations FINAL WHERE dedup_key = {dedup_key:String} AND " + expiry + " ORDER BY state_version DESC LIMIT 1"
        with self._client() as client:
            result = self._query(client, sql, {"dedup_key": dedup_key})
            if not result.result_rows:
                return None
            return _row_to_dict(result.result_rows[0], list(result.column_names))

    def list_for_finding(self, ref: FindingRef, limit: int = 5) -> list[dict[str, Any]]:
        if not 1 <= limit <= 10:
            raise ValueError("history limit must be between 1 and 10")
        kind, identifier = finding_key(ref)
        sql = """SELECT * FROM llm_investigations FINAL
                 WHERE finding_kind = {kind:String} AND finding_id = {finding_id:String}
                   AND expires_at > now()
                 ORDER BY created_at_ms DESC LIMIT {limit:UInt8}"""
        with self._client() as client:
            result = self._query(client, sql, {"kind": kind, "finding_id": identifier, "limit": limit})
            return [_row_to_dict(row, list(result.column_names)) for row in result.result_rows]

    def list_nonterminal(self, limit: int = 100, cursor: int = 0) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("recovery page limit out of range")
        sql = """SELECT * FROM llm_investigations FINAL
                 WHERE state IN ('queued','assembling','generating','validating')
                   AND expires_at > now() AND created_at_ms > {cursor:UInt64}
                 ORDER BY created_at_ms ASC LIMIT {limit:UInt8}"""
        with self._client() as client:
            result = self._query(client, sql, {"cursor": max(0, cursor), "limit": limit})
            return [_row_to_dict(row, list(result.column_names)) for row in result.result_rows]

    def admission_counts(self, now_ms: int) -> dict[str, int]:
        day = now_ms - 86_400_000
        minute = now_ms - 60_000
        sql = """SELECT
                   countIf(created_at_ms >= {minute:UInt64}) AS minute_count,
                   countIf(created_at_ms >= {day:UInt64}) AS day_count,
                   countIf(state IN ('queued','assembling','generating','validating')) AS active_count
                 FROM llm_investigations FINAL WHERE expires_at > now()"""
        with self._client() as client:
            result = self._query(client, sql, {"minute": max(0, minute), "day": max(0, day)})
            row = result.result_rows[0] if result.result_rows else (0, 0, 0)
            return {"minute": int(row[0]), "day": int(row[1]), "active": int(row[2])}

    def append_state(self, row: dict[str, Any]) -> None:
        required = set(TABLE_COLUMNS)
        if set(row) != required:
            missing = sorted(required - set(row))
            extra = sorted(set(row) - required)
            raise ValueError("invalid investigation state columns: missing={} extra={}".format(missing, extra))
        _json_bytes(row["snapshot_json"], MAX_SNAPSHOT_BYTES, "snapshot")
        _json_bytes(row["evidence_json"], MAX_EVIDENCE_BYTES, "evidence")
        _json_bytes(row["deterministic_summary_json"], MAX_RESULT_BYTES, "summary")
        _json_bytes(row["result_json"], MAX_RESULT_BYTES, "result")
        _json_bytes(row["metadata_json"], MAX_METADATA_BYTES, "metadata")
        try:
            UUID(str(row["id"]))
        except Exception as exc:
            raise ValueError("id must be a UUID") from exc
        if not isinstance(row["dedup_key"], str) or not HEX64.fullmatch(row["dedup_key"]):
            raise ValueError("dedup_key must be lowercase sha256 hex")
        if not isinstance(row["source_version"], str) or not HEX64.fullmatch(row["source_version"]):
            raise ValueError("source_version must be lowercase sha256 hex")
        if row["finding_kind"] not in {"anomaly_event", "principal_change_event", "incident"}:
            raise ValueError("invalid finding kind")
        if row["state"] not in NONTERMINAL + TERMINAL:
            raise ValueError("invalid investigation state")
        if not isinstance(row["retry_index"], int) or isinstance(row["retry_index"], bool) or not 0 <= row["retry_index"] <= 2:
            raise ValueError("retry_index must be between 0 and 2")
        if not isinstance(row["state_version"], int) or isinstance(row["state_version"], bool) or row["state_version"] < 1:
            raise ValueError("state_version must be positive")
        if not isinstance(row["cancel_requested"], int) or row["cancel_requested"] not in (0, 1):
            raise ValueError("cancel_requested must be 0 or 1")
        expires = row["expires_at"]
        if isinstance(expires, (int, float)):
            expires = datetime.fromtimestamp(float(expires) / 1000.0, tz=timezone.utc)
        elif isinstance(expires, str):
            try:
                expires = datetime.fromisoformat(expires)
            except ValueError as exc:
                raise ValueError("expires_at must be a datetime") from exc
        if not isinstance(expires, datetime):
            raise ValueError("expires_at must be a datetime")
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        values = [row[column] if column != "expires_at" else expires for column in TABLE_COLUMNS]
        with self._client() as client:
            current_result = self._query(client,
                "SELECT * FROM llm_investigations FINAL WHERE id = {run_id:UUID} LIMIT 1",
                {"run_id": str(row["id"])})
            current_rows = getattr(current_result, "result_rows", ())
            if current_rows:
                current = _row_to_dict(current_rows[0], list(getattr(current_result, "column_names", TABLE_COLUMNS)))
                current_version = int(current.get("state_version", 0))
                if current_version == row["state_version"]:
                    if current.get("dedup_key") != row["dedup_key"] or current.get("state") != row["state"]:
                        raise ValueError("state version already contains different content")
                    return
                if current_version + 1 != row["state_version"]:
                    raise ValueError("state_version must increase monotonically")
            try:
                client.insert("llm_investigations", [values], column_names=list(TABLE_COLUMNS))
            except Exception:
                # ClickHouse can acknowledge an INSERT only after the client
                # loses the response.  Query the deterministic ID before
                # deciding that admission/persistence failed.
                try:
                    confirmed = self._query(client,
                        "SELECT * FROM llm_investigations FINAL WHERE id = {run_id:UUID} LIMIT 1",
                        {"run_id": str(row["id"])})
                    confirmed_rows = getattr(confirmed, "result_rows", ())
                    if confirmed_rows:
                        confirmed_row = _row_to_dict(confirmed_rows[0], list(getattr(confirmed, "column_names", TABLE_COLUMNS)))
                        if int(confirmed_row.get("state_version", 0)) == row["state_version"] and confirmed_row.get("dedup_key") == row["dedup_key"]:
                            return
                except Exception:
                    pass
                raise
