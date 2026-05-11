"""Task + idempotency helpers."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from apps.karma_bff.app import state_machine


def _now() -> float:
    return time.time()


def idempotency_get(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT response_body FROM idempotency WHERE idem_key = ?", (key,)).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def idempotency_put(conn: sqlite3.Connection, key: str, route: str, response: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO idempotency (idem_key, route, response_body, created_at) VALUES (?,?,?,?)",
        (key, route, json.dumps(response, sort_keys=True), _now()),
    )
    conn.commit()


def task_get(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tasks WHERE trace_id = ?", (trace_id,)).fetchone()
    if row is None:
        return None
    return dict(row)


def task_set_state(conn: sqlite3.Connection, trace_id: str, new_state: str) -> None:
    row = task_get(conn, trace_id)
    if row is None:
        raise KeyError("task not found")
    old = row["state"]
    if old == new_state:
        return
    if not state_machine.can_transition(old, new_state):
        raise ValueError(f"invalid transition {old} -> {new_state}")
    conn.execute(
        "UPDATE tasks SET state = ?, updated_at = ? WHERE trace_id = ?",
        (new_state, _now(), trace_id),
    )
    conn.commit()


def task_create(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    task_id: str,
    task_contract: dict[str, Any],
) -> dict[str, Any]:
    conn.execute(
        """
        INSERT INTO tasks (trace_id, task_id, state, task_contract_json, snapshot_json, bill_id, lock_tx, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            trace_id,
            task_id,
            "PLANNED",
            json.dumps(task_contract, sort_keys=True),
            None,
            None,
            None,
            _now(),
            _now(),
        ),
    )
    conn.commit()
    return task_get(conn, trace_id)  # type: ignore[return-value]


def task_update_snapshot(conn: sqlite3.Connection, trace_id: str, snapshot: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE tasks SET snapshot_json = ?, updated_at = ? WHERE trace_id = ?",
        (json.dumps(snapshot, sort_keys=True), _now(), trace_id),
    )
    conn.commit()


def task_set_bill(conn: sqlite3.Connection, trace_id: str, bill_id: int | None, lock_tx: str | None) -> None:
    conn.execute(
        "UPDATE tasks SET bill_id = ?, lock_tx = ?, updated_at = ? WHERE trace_id = ?",
        (bill_id, lock_tx, _now(), trace_id),
    )
    conn.commit()


def receipts_list(conn: sqlite3.Connection, trace_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT receipt_json FROM receipts WHERE trace_id = ? ORDER BY id ASC",
        (trace_id,),
    ).fetchall()
    return [json.loads(r[0]) for r in rows]


def receipt_append(conn: sqlite3.Connection, trace_id: str, receipt: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO receipts (trace_id, receipt_json, created_at) VALUES (?,?,?)",
        (trace_id, json.dumps(receipt, sort_keys=True), _now()),
    )
    conn.commit()
