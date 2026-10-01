"""SQLite persistence for BFF (dev default)."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            trace_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            state TEXT NOT NULL,
            task_contract_json TEXT,
            snapshot_json TEXT,
            bill_id INTEGER,
            lock_tx TEXT,
            status_reason TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS idempotency (
            idem_key TEXT PRIMARY KEY,
            route TEXT NOT NULL,
            response_body TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_receipts_trace ON receipts(trace_id);
        """
    )
    # ``CREATE TABLE IF NOT EXISTS`` never adds a column to a database that
    # predates it, so a deployment created before ``status_reason`` existed
    # needs an explicit, idempotent ALTER. Without it every terminal write that
    # carries a reason fails with "no such column: status_reason".
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "status_reason" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN status_reason TEXT")
    conn.commit()


@contextmanager
def get_conn(db_path: str) -> Iterator[sqlite3.Connection]:
    c = connect(db_path)
    try:
        init_schema(c)
        yield c
    finally:
        c.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}
