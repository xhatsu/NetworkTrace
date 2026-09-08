import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Iterator
from backend.config import settings

def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path else settings.db_path
    conn = sqlite3.connect(target, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def db_transaction(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
