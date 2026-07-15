# src/db/connection.py
from __future__ import annotations

import sqlite3
from pathlib import Path


SQLITE_BUSY_TIMEOUT_MS = 15_000


def connect(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    # The Python timeout and SQLite busy handler cover both the initial lock
    # acquisition and later writes. This matters on Windows in particular,
    # where antivirus/indexing and a just-finished backup can briefly retain a
    # file handle even though no MAHIRA transaction is still active.
    conn = sqlite3.connect(str(p), timeout=SQLITE_BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
