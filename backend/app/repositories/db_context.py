"""ClickHouse connection context and a narrow SQLite-compatibility adapter.

One canonical ClickHouse schema avoids split-brain reads between ingestion and
analytics. The adapter preserves established repository SQL contracts during
cutover, confining dialect translation to this boundary rather than scattering
storage-specific branches throughout API and detector code.
"""
from __future__ import annotations

import datetime
import logging
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence

import clickhouse_connect
from clickhouse_connect.driver.binding import bind_query, format_query_value
from backend.config import settings

log = logging.getLogger("tracescope-hub")

_client_local = threading.local()


class ClickHouseRow:
    """Row adapter that supports both dictionary-style and tuple-style access."""
    __slots__ = ("_keys", "_values", "_mapping")

    def __init__(self, column_names: Sequence[str], values: Sequence[Any]):
        clean_keys = [c.split(".")[-1] if "." in c else c for c in column_names]
        self._keys = clean_keys
        self._values = tuple(values)
        self._mapping = dict(zip(clean_keys, values))
        for orig, val in zip(column_names, values):
            self._mapping[orig] = val

    def __getitem__(self, item: str | int | slice) -> Any:
        if isinstance(item, (int, slice)):
            return self._values[item]
        return self._mapping[item]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._keys)

    def get(self, key: str, default: Any = None) -> Any:
        return self._mapping.get(key, default)

    def keys(self) -> list[str]:
        return list(self._keys)

    def values(self) -> list[Any]:
        return list(self._values)

    def items(self):
        return self._mapping.items()

    def __contains__(self, key: str) -> bool:
        return key in self._mapping

    def __repr__(self) -> str:
        return f"ClickHouseRow({self._mapping!r})"


class ClickHouseCursor:
    """Cursor-like wrapper over ClickHouse query results."""
    def __init__(self, result_rows: list[Sequence[Any]], column_names: list[str], rowcount: int = 0, lastrowid: int = 0):
        self._rows = [ClickHouseRow(column_names, r) for r in result_rows]
        self._column_names = column_names
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self._idx = 0

    def fetchone(self) -> Optional[ClickHouseRow]:
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None

    def fetchall(self) -> list[ClickHouseRow]:
        remaining = self._rows[self._idx:]
        self._idx = len(self._rows)
        return remaining

    def __iter__(self) -> Iterator[ClickHouseRow]:
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


def _convert_placeholders_and_bind(sql: str, params: Sequence[Any] | dict[str, Any] | None) -> str:
    """Safely convert legacy placeholders at the storage boundary, never by string interpolation upstream."""
    if not params:
        return sql
    if isinstance(params, dict):
        bound_sql, _ = bind_query(sql, params)
        return bound_sql

    param_list = list(params)
    param_idx = 0
    tokens: list[str] = []
    in_quote: Optional[str] = None
    escaped = False
    for ch in sql:
        if escaped:
            tokens.append(ch)
            escaped = False
        elif ch == '\\':
            tokens.append(ch)
            escaped = True
        elif ch in ("'", '"'):
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
            tokens.append(ch)
        elif ch == '?' and in_quote is None:
            if param_idx < len(param_list):
                tokens.append(str(format_query_value(param_list[param_idx], datetime.timezone.utc)))
                param_idx += 1
            else:
                tokens.append('?')
        else:
            tokens.append(ch)

    return "".join(tokens)


_RE_INSERT = re.compile(
    r"^\s*INSERT(?:\s+OR\s+IGNORE)?\s+INTO\s+([a-zA-Z0-9_]+)\s*\((.*?)\)\s*VALUES",
    re.IGNORECASE | re.DOTALL,
)
_RE_PRAGMA_TABLE_INFO = re.compile(r"^\s*PRAGMA\s+table_info\s*\(\s*([a-zA-Z0-9_]+)\s*\)\s*;?$", re.IGNORECASE)
_RE_PRAGMA_GENERIC = re.compile(r"^\s*PRAGMA\s+.*$", re.IGNORECASE)


class ClickHouseConnection:
    """Adapter mimicking sqlite3.Connection on top of ClickHouse client."""
    def __init__(self, client: clickhouse_connect.driver.Client, database: str):
        self.client = client
        self.database = database
        self.total_changes = 0

    def cursor(self) -> ClickHouseConnection:
        return self

    def _translate_and_format(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> tuple[str, str]:
        """
        Returns (command_type, translated_sql).
        command_type is one of ('SELECT', 'COMMAND', 'MUTATION', 'PRAGMA_TABLE_INFO', 'NOOP').
        """
        stripped = sql.strip()

        # Legacy callers use PRAGMA for schema discovery; map only the supported shape.
        m_pragma = _RE_PRAGMA_TABLE_INFO.match(stripped)
        if m_pragma:
            table_name = m_pragma.group(1)
            return "PRAGMA_TABLE_INFO", table_name

        if _RE_PRAGMA_GENERIC.match(stripped):
            return "NOOP", ""

        # Never imply cross-statement transactional semantics that ClickHouse does not provide.
        upper = stripped.upper()
        if upper.startswith(("BEGIN", "COMMIT", "ROLLBACK")):
            raise NotImplementedError("Explicit SQL transactions are not supported by ClickHouse")

        # ReplacingMergeTree models mutable entities; retain legacy insert syntax at callers.
        if upper.startswith("INSERT"):
            if re.match(r"^\s*INSERT\s+OR\s+IGNORE\b", stripped, re.IGNORECASE):
                raise NotImplementedError("INSERT OR IGNORE must be implemented with an explicit ClickHouse key strategy")

        # Preserve expression intent where SQLite's scalar spelling differs from ClickHouse.
        stripped = re.sub(r"\bMAX\s*\(([^,()]+),\s*([^()]+)\)", r"greatest(\1, \2)", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\bMIN\s*\(([^,()]+),\s*([^()]+)\)", r"least(\1, \2)", stripped, flags=re.IGNORECASE)

        # Wait for mutations so lifecycle APIs retain their historical synchronous visibility guarantee.
        if upper.startswith("UPDATE"):
            m_up = re.match(r"^\s*UPDATE\s+([a-zA-Z0-9_]+)\s+SET\s+(.*?)\s+WHERE\s+(.*)$", stripped, re.IGNORECASE | re.DOTALL)
            if m_up:
                table, set_clause, where_clause = m_up.groups()
                mut_sql = f"ALTER TABLE {table} UPDATE {set_clause} WHERE {where_clause} SETTINGS mutations_sync = 1"
                bound = _convert_placeholders_and_bind(mut_sql, params)
                return "MUTATION", bound

        # The same synchronous mutation rule makes delete responses deterministic for operators.
        if upper.startswith("DELETE"):
            m_del = re.match(r"^\s*DELETE\s+FROM\s+([a-zA-Z0-9_]+)(?:\s+WHERE\s+(.*))?$", stripped, re.IGNORECASE | re.DOTALL)
            if m_del:
                table = m_del.group(1)
                where_clause = m_del.group(2)
                where_clause = where_clause.strip() if where_clause else "1=1"
                mut_sql = f"ALTER TABLE {table} DELETE WHERE {where_clause} SETTINGS mutations_sync = 1"
                bound = _convert_placeholders_and_bind(mut_sql, params)
                return "MUTATION", bound

        # Translate SQLite strftime and GROUP_CONCAT to ClickHouse equivalents
        stripped = re.sub(
            r"strftime\s*\(\s*('[^']+')\s*,\s*([a-zA-Z0-9_]+)\s*/\s*1000(?:\s*,\s*'unixepoch')?\s*\)",
            r"formatDateTime(toDateTime(intDiv(\2, 1000)), \1)",
            stripped,
            flags=re.IGNORECASE,
        )
        stripped = re.sub(
            r"strftime\s*\(\s*('[^']+')\s*,\s*([a-zA-Z0-9_]+)(?:\s*,\s*'unixepoch')?\s*\)",
            r"formatDateTime(toDateTime(\2), \1)",
            stripped,
            flags=re.IGNORECASE,
        )
        stripped = re.sub(
            r"GROUP_CONCAT\s*\(\s*([a-zA-Z0-9_]+)\s*\)",
            r"arrayStringConcat(groupArray(toString(\1)), ',')",
            stripped,
            flags=re.IGNORECASE,
        )

        if "SQLITE_MASTER" in upper:
            stripped = re.sub(r"SELECT\s+sql\s+FROM\s+sqlite_master", "SELECT create_table_query AS sql FROM system.tables WHERE database = currentDatabase()", stripped, flags=re.IGNORECASE)
            stripped = re.sub(r"FROM\s+sqlite_master\b", "FROM system.tables WHERE database = currentDatabase()", stripped, flags=re.IGNORECASE)

        bound = _convert_placeholders_and_bind(stripped, params)
        if bound.strip().upper().startswith(("SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "WITH")):
            return "SELECT", bound
        return "COMMAND", bound

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> ClickHouseCursor:
        cmd_type, processed = self._translate_and_format(sql, params)

        if cmd_type == "NOOP":
            return ClickHouseCursor([], [], 0)

        if cmd_type == "PRAGMA_TABLE_INFO":
            table_name = processed
            res = self.client.query(f"DESCRIBE TABLE {table_name}")
            # SQLite table_info returns: cid, name, type, notnull, dflt_value, pk
            pragma_rows = []
            for idx, r in enumerate(res.result_rows):
                col_name = r[0]
                col_type = r[1]
                is_notnull = 0 if "Nullable" in col_type else 1
                pragma_rows.append((idx, col_name, col_type, is_notnull, None, 0))
            return ClickHouseCursor(pragma_rows, ["cid", "name", "type", "notnull", "dflt_value", "pk"], len(pragma_rows))

        if cmd_type == "SELECT":
            res = self.client.query(processed)
            return ClickHouseCursor(res.result_rows, res.column_names, len(res.result_rows))

        if cmd_type in ("COMMAND", "MUTATION"):
            self.client.command(processed)
            self.total_changes += 1
            last_id = 0
            if sql.strip().upper().startswith("INSERT"):
                m_t = re.match(r"^\s*INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+([a-zA-Z0-9_]+)", sql, re.IGNORECASE)
                if m_t:
                    tname = m_t.group(1).lower()
                    try:
                        r = self.client.query(f"SELECT max(id) FROM {tname}").result_rows
                        if r and r[0][0] is not None:
                            last_id = int(r[0][0])
                    except Exception:
                        pass
            return ClickHouseCursor([], [], 1, lastrowid=last_id)

        return ClickHouseCursor([], [], 0)

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any] | dict[str, Any]]) -> ClickHouseCursor:
        if not seq_of_params:
            return ClickHouseCursor([], [], 0)

        stripped = sql.strip()
        m_insert = _RE_INSERT.match(stripped)

        # Prefer block inserts: small row-by-row parts would undermine ClickHouse ingest throughput.
        if m_insert and m_insert.group(2):
            table = m_insert.group(1)
            raw_cols = m_insert.group(2)
            cols = [c.strip() for c in raw_cols.split(",") if c.strip()]
            first_p = seq_of_params[0]
            if isinstance(first_p, dict) or len(first_p) == len(cols):
                rows_data = []
                for p in seq_of_params:
                    if isinstance(p, dict):
                        rows_data.append([p.get(c) for c in cols])
                    else:
                        rows_data.append(list(p))
                self.client.insert(table, rows_data, column_names=cols)
                self.total_changes += len(rows_data)
                return ClickHouseCursor([], [], len(rows_data))

        # Fallback to iterated execute
        count = 0
        for params in seq_of_params:
            self.execute(sql, params)
            count += 1
        return ClickHouseCursor([], [], count)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> ClickHouseConnection:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


import hashlib
from backend.app.repositories.clickhouse_migrator import ensure_database, run_clickhouse_migrations

_initialized_dbs: set[str] = set()
_init_lock = threading.Lock()


def resolve_target_db(db_path: Optional[str] = None) -> str:
    """Derive target ClickHouse database name, supporting isolated test databases."""
    if not db_path:
        return settings.clickhouse_database
    str_path = str(db_path)
    if re.match(r"^[a-zA-Z0-9_]+$", str_path) and not str_path.endswith(".db"):
        return str_path
    h = hashlib.md5(str_path.encode()).hexdigest()[:12]
    return f"test_{h}"


def ensure_db_ready(target_db: str) -> None:
    """Initialize a database once per process, avoiding repeated migration checks on hot paths."""
    if target_db not in _initialized_dbs:
        with _init_lock:
            if target_db not in _initialized_dbs:
                ensure_database(target_db)
                run_clickhouse_migrations(target_db)
                _initialized_dbs.add(target_db)


def get_connection(db_path: Optional[str] = None) -> ClickHouseConnection:
    """Return a thread-local client so concurrent requests do not share mutable driver state."""
    target_db = resolve_target_db(db_path)
    ensure_db_ready(target_db)

    clients = getattr(_client_local, "clients", None)
    if clients is None:
        clients = {}
        _client_local.clients = clients

    client = clients.get(target_db)
    if client is None:
        client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            database=target_db,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            secure=settings.clickhouse_secure,
            connect_timeout=settings.clickhouse_connect_timeout,
            send_receive_timeout=settings.clickhouse_send_receive_timeout,
        )
        clients[target_db] = client

    return ClickHouseConnection(client, target_db)


@contextmanager
def db_transaction(db_path: Optional[str] = None) -> Iterator[ClickHouseConnection]:
    """Keep the repository call shape stable while ClickHouse owns per-statement durability."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
