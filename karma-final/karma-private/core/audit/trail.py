"""
PRIVATE — Decision audit trail.
Stores append-only verification/settlement decision records.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class DecisionAuditEntry:
    event_type: str
    task_id: str
    request_hash: str
    policy_version: str
    decision: str
    confidence: float | None = None
    bundle_id: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": self.event_type,
            "task_id": self.task_id,
            "request_hash": self.request_hash,
            "policy_version": self.policy_version,
            "decision": self.decision,
            "confidence": self.confidence,
            "bundle_id": self.bundle_id,
            "notes": self.notes,
            "metadata": self.metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


class DecisionAuditTrail:
    """Simple JSONL-backed append-only audit trail."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, entry: DecisionAuditEntry) -> None:
        payload = json.dumps(entry.to_dict(), separators=(",", ":"), ensure_ascii=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(payload + "\n")

    def list_by_task(self, task_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        matches: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                if item.get("task_id") == task_id:
                    matches.append(item)
        return matches[-limit:]

