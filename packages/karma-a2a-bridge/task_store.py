"""Persistent A2A task store with append-only event sourcing.

State is rebuilt from the event log. Snapshots are materializations for fast reads.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = os.getenv(
    "A2A_TASK_STORE_PATH",
    str(Path(__file__).resolve().parent / "data" / "a2a_tasks.sqlite3"),
)


class TaskStore:
    """SQLite-backed event-sourced task repository."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_task_events_task_id_seq
                    ON task_events(task_id, seq);

                CREATE TABLE IF NOT EXISTS task_snapshots (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS used_nonces (
                    agent TEXT NOT NULL,
                    nonce INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    op_type TEXT NOT NULL,
                    used_at INTEGER NOT NULL,
                    PRIMARY KEY (agent, nonce)
                );
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def append_event(self, task_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append event and refresh snapshot. Returns latest state."""
        now = int(time.time())
        event_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO task_events(event_id, task_id, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (event_id, task_id, event_type, json.dumps(payload, separators=(",", ":")), now),
            )
            # Ordering is by AUTOINCREMENT seq (not UUID / same-second timestamps).
            state = self._rebuild(task_id)
            version = self._event_count(task_id)
            self._conn.execute(
                "INSERT INTO task_snapshots(task_id, status, state_json, version, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET "
                "status=excluded.status, state_json=excluded.state_json, "
                "version=excluded.version, updated_at=excluded.updated_at",
                (
                    task_id,
                    state.get("status", "unknown"),
                    json.dumps(state, separators=(",", ":")),
                    version,
                    now,
                ),
            )
            self._conn.commit()
            return state

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM task_snapshots WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row:
                return json.loads(row["state_json"])
            # Fallback: rebuild if events exist but snapshot missing
            if self._event_count(task_id) == 0:
                return None
            state = self._rebuild(task_id)
            return state or None

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, event_id, task_id, event_type, payload_json, created_at "
                "FROM task_events WHERE task_id = ? ORDER BY seq ASC",
                (task_id,),
            ).fetchall()
            return [
                {
                    "seq": r["seq"],
                    "event_id": r["event_id"],
                    "task_id": r["task_id"],
                    "event_type": r["event_type"],
                    "payload": json.loads(r["payload_json"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def consume_nonce(self, agent: str, nonce: int, task_id: str, op_type: str) -> None:
        """Replay protection for EIP-712 nonces. Raises ValueError if reused."""
        agent_key = agent.lower()
        now = int(time.time())
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO used_nonces(agent, nonce, task_id, op_type, used_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (agent_key, int(nonce), task_id, op_type, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"A2A EIP-712 nonce already used for agent {agent}") from exc

    def _event_count(self, task_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM task_events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row["c"])

    def _rebuild(self, task_id: str) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT event_type, payload_json, created_at FROM task_events "
            "WHERE task_id = ? ORDER BY seq ASC",
            (task_id,),
        ).fetchall()
        state: dict[str, Any] = {"task_id": task_id}
        for r in rows:
            payload = json.loads(r["payload_json"])
            et = r["event_type"]
            if et == "TaskCreated":
                # Do not blindly update() later fields over newer status — set explicitly
                state["task_id"] = payload.get("task_id", task_id)
                state["skill"] = payload.get("skill")
                state["params"] = payload.get("params", {})
                state["requester_id"] = payload.get("requester_id")
                state["status"] = payload.get("status", "negotiating")
                state["voucher_id"] = payload.get("voucher_id")
                state["result"] = payload.get("result")
                state["signer"] = payload.get("signer")
                state["created_at"] = r["created_at"]
            elif et == "TaskConfirmed":
                state["status"] = "accepted"
                if "voucher_id" in payload:
                    state["voucher_id"] = payload["voucher_id"]
                if "voucher" in payload:
                    state["voucher"] = payload["voucher"]
                if "seller_id" in payload:
                    state["seller_id"] = payload["seller_id"]
                if "amount" in payload:
                    state["amount"] = payload["amount"]
                if "signer" in payload:
                    state["signer"] = payload["signer"]
            elif et == "TaskSubmitted":
                state["status"] = "completed"
                state["result"] = payload.get("result")
                if "signer" in payload:
                    state["signer"] = payload["signer"]
            elif et == "TaskCancelled":
                state["status"] = "cancelled"
                state["reason"] = payload.get("reason", "")
                if "signer" in payload:
                    state["signer"] = payload["signer"]
            elif et == "HandoffGenerated":
                state["last_handoff"] = payload.get("handoff")
                if "signer" in payload:
                    state["signer"] = payload["signer"]
            state["updated_at"] = r["created_at"]
            state.setdefault("events_applied", 0)
            state["events_applied"] = int(state["events_applied"]) + 1
        return state


_STORE: TaskStore | None = None


def get_task_store() -> TaskStore:
    global _STORE
    if _STORE is None:
        _STORE = TaskStore()
    return _STORE


def reset_task_store_for_tests(db_path: str) -> TaskStore:
    global _STORE
    if _STORE is not None:
        _STORE.close()
    _STORE = TaskStore(db_path)
    return _STORE
