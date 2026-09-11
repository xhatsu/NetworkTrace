"""Ingestion batch repository — provides deduplication tracking for agent batches.

Protects against duplicate event injection when shippers retry requests after
network timeouts or lost HTTP 200 responses.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any, Dict, Optional

from backend.app.repositories.db_context import get_connection

log = logging.getLogger("tracescope-hub")

_DEFAULT_RETENTION_MS = 7 * 24 * 3600 * 1000  # 7 days
_MAX_CACHE_ENTRIES = 50_000


class IngestBatchRepository:
    _lock = threading.Lock()
    _cache: collections.OrderedDict[str, bool] = collections.OrderedDict()
    _max_cache_size: int = _MAX_CACHE_ENTRIES
    _last_pruned_at: float = 0.0

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def is_batch_processed(self, batch_id: str) -> bool:
        """Check whether batch_id has already been processed and committed."""
        if not batch_id:
            return False

        with self._lock:
            if batch_id in self._cache:
                self._cache.move_to_end(batch_id)
                return True

        try:
            with get_connection(self.db_path) as db:
                row = db.execute(
                    "SELECT 1 FROM ingest_batches WHERE batch_id = ?",
                    (batch_id,)
                ).fetchone()
                if row is not None:
                    with self._lock:
                        self._cache[batch_id] = True
                        if len(self._cache) > self._max_cache_size:
                            self._cache.popitem(last=False)
                    return True
        except Exception as exc:
            log.warning("Failed to query ingest_batches for %s: %s", batch_id, exc)

        return False

    def record_batch(
        self,
        batch_id: str,
        node: Optional[str] = None,
        record_count: int = 0,
        status: str = "accepted"
    ) -> bool:
        """Record batch_id as successfully processed in database and cache."""
        if not batch_id:
            return False

        now_ms = int(time.time() * 1000)
        try:
            with get_connection(self.db_path) as db:
                db.execute(
                    """
                    INSERT OR IGNORE INTO ingest_batches (batch_id, node, record_count, received_at_ms, status)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (batch_id, node, record_count, now_ms, status)
                )

            with self._lock:
                self._cache[batch_id] = True
                if len(self._cache) > self._max_cache_size:
                    self._cache.popitem(last=False)

            self._maybe_prune()
            return True
        except Exception as exc:
            log.warning("Failed to record batch_id %s: %s", batch_id, exc)
            return False

    def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve batch metadata by batch_id."""
        if not batch_id:
            return None
        try:
            with get_connection(self.db_path) as db:
                row = db.execute(
                    "SELECT batch_id, node, record_count, received_at_ms, status FROM ingest_batches WHERE batch_id = ?",
                    (batch_id,)
                ).fetchone()
                if row:
                    return dict(row)
        except Exception as exc:
            log.warning("Failed to get batch %s: %s", batch_id, exc)
        return None

    def prune_batches(self, older_than_ms: Optional[int] = None) -> int:
        """Prune batches older than the given timestamp (default 7 days)."""
        if older_than_ms is None:
            older_than_ms = int(time.time() * 1000) - _DEFAULT_RETENTION_MS
        try:
            with get_connection(self.db_path) as db:
                cursor = db.execute(
                    "DELETE FROM ingest_batches WHERE received_at_ms < ?",
                    (older_than_ms,)
                )
                return cursor.rowcount
        except Exception as exc:
            log.warning("Failed to prune ingest_batches: %s", exc)
            return 0

    def _maybe_prune(self) -> None:
        """Opportunistically prune old records at most once per hour."""
        now = time.time()
        if now - IngestBatchRepository._last_pruned_at > 3600.0:
            IngestBatchRepository._last_pruned_at = now
            try:
                self.prune_batches()
            except Exception:
                pass

    @classmethod
    def clear_cache(cls) -> None:
        """Clear in-memory cache (primarily for tests)."""
        with cls._lock:
            cls._cache.clear()

    @classmethod
    def cache_batch(cls, batch_id: str) -> None:
        """Remember a batch already committed by the coalescing ingest writer."""
        if not batch_id:
            return
        with cls._lock:
            cls._cache[batch_id] = True
            cls._cache.move_to_end(batch_id)
            if len(cls._cache) > cls._max_cache_size:
                cls._cache.popitem(last=False)
