"""WebSocket Hub — real-time billing event push to connected clients.

Provides a FastAPI WebSocket endpoint at::

    ws://host/v1/ws/tasks/{task_id}?role=buyer&token=...

Each connected client receives push messages for:
- New receipts
- Billing state changes
- Merkle root updates
- Anchoring confirmations

Message format::

    {
        "event": "receipt.created",
        "task_id": "...",
        "timestamp": "2024-01-01T00:00:00Z",
        "payload": {
            "receipt": {...},
            "billing_state": "STEP_IN_PROGRESS",
            "step_current": 3,
            "step_total": 10,
            "cost_accrued_usdc": 1.50,
            "latest_merkle_root": "abc123...",
            "anchored_count": 5
        }
    }
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from packages.karma_billing.schema import UniversalReceipt, BillingSnapshot

logger = logging.getLogger("karma.billing.ws_hub")


# ── WS Message Models ─────────────────────────────────────────────────────────


@dataclass
class WSPayload:
    """Payload carried in a WebSocket event message."""

    receipt: Optional[UniversalReceipt] = None
    billing_state: Optional[str] = None
    step_current: int = 0
    step_total: int = 0
    cost_accrued_usdc: float = 0.0
    latest_merkle_root: Optional[str] = None
    anchored_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt": self.receipt.model_dump(mode="json") if self.receipt else None,
            "billing_state": self.billing_state,
            "step_current": self.step_current,
            "step_total": self.step_total,
            "cost_accrued_usdc": self.cost_accrued_usdc,
            "latest_merkle_root": self.latest_merkle_root,
            "anchored_count": self.anchored_count,
        }


@dataclass
class WSMessage:
    """A WebSocket event message."""

    event: str
    task_id: str
    timestamp: str
    payload: WSPayload

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "payload": self.payload.to_dict(),
        }


# ── WS Connection ─────────────────────────────────────────────────────────────


@dataclass
class WSConnection:
    """Represents a single WebSocket connection."""

    task_id: str
    role: str  # "buyer" | "seller" | "observer"
    token: str
    queue: asyncio.Queue[WSMessage] = field(default_factory=asyncio.Queue)


# ── WebSocketHub ──────────────────────────────────────────────────────────────


class WebSocketHub:
    """Manages WebSocket connections and push events.

    Creates a FastAPI WebSocket endpoint.  Clients connect, subscribe to task
    events, and receive real-time push messages for every billing event.

    Usage with FastAPI::

        hub = WebSocketHub()

        @app.websocket("/v1/ws/tasks/{task_id}")
        async def ws_endpoint(websocket: WebSocket, task_id: str, role: str, token: str):
            await hub.handle_connection(websocket, task_id, role, token)

    For testing without a running ASGI server::

        hub.push_event(task_id, message)  # in-memory push
    """

    def __init__(self) -> None:
        # task_id → set of WSConnection
        self._subscriptions: Dict[str, Set[WSConnection]] = {}

    # ── Subscription Management ────────────────────────────────────────────

    def subscribe(self, conn: WSConnection) -> None:
        """Add a connection to the task's subscriber set."""
        if conn.task_id not in self._subscriptions:
            self._subscriptions[conn.task_id] = set()
        self._subscriptions[conn.task_id].add(conn)
        logger.info(
            "WS subscribe: task=%s role=%s (total=%d)",
            conn.task_id,
            conn.role,
            len(self._subscriptions[conn.task_id]),
        )

    def unsubscribe(self, conn: WSConnection) -> None:
        """Remove a connection from the task's subscriber set."""
        if conn.task_id in self._subscriptions:
            self._subscriptions[conn.task_id].discard(conn)
            if not self._subscriptions[conn.task_id]:
                del self._subscriptions[conn.task_id]
            logger.info(
                "WS unsubscribe: task=%s role=%s (remaining=%d)",
                conn.task_id,
                conn.role,
                len(self._subscriptions.get(conn.task_id, set())),
            )

    # ── Event Push ─────────────────────────────────────────────────────────

    async def push_event(self, task_id: str, message: WSMessage) -> None:
        """Push a WSMessage to all subscribers of a task.

        Each subscriber gets the message placed on its asyncio.Queue.
        Failed deliveries are logged and the connection is marked for cleanup.
        """
        subscribers = self._subscriptions.get(task_id, set())
        if not subscribers:
            logger.debug("WS push: no subscribers for task=%s", task_id)
            return

        dead: List[WSConnection] = []
        for conn in list(subscribers):
            try:
                conn.queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "WS queue full for task=%s role=%s — dropping connection",
                    task_id,
                    conn.role,
                )
                dead.append(conn)

        for conn in dead:
            self.unsubscribe(conn)

        logger.debug(
            "WS push: task=%s event=%s delivered_to=%d",
            task_id,
            message.event,
            len(subscribers) - len(dead),
        )

    async def push_receipt(
        self,
        receipt: UniversalReceipt,
        snapshot: Optional[BillingSnapshot] = None,
    ) -> None:
        """Convenience method: push a receipt.created event with snapshot."""
        from datetime import datetime, timezone

        payload = WSPayload(
            receipt=receipt,
            billing_state=snapshot.billing_state.value if snapshot else None,
            step_current=snapshot.current_step if snapshot else 0,
            step_total=snapshot.total_steps_estimated if snapshot else 0,
            cost_accrued_usdc=snapshot.cost_accrued_usdc if snapshot else 0.0,
            latest_merkle_root=snapshot.latest_merkle_root if snapshot else None,
            anchored_count=snapshot.anchored_receipts if snapshot else 0,
        )

        message = WSMessage(
            event="receipt.created",
            task_id=receipt.task_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )

        await self.push_event(receipt.task_id, message)

    async def push_state_change(
        self,
        task_id: str,
        previous_state: str,
        new_state: str,
        snapshot: Optional[BillingSnapshot] = None,
    ) -> None:
        """Push a state.changed event."""
        from datetime import datetime, timezone

        payload = WSPayload(
            billing_state=new_state,
            step_current=snapshot.current_step if snapshot else 0,
            step_total=snapshot.total_steps_estimated if snapshot else 0,
            cost_accrued_usdc=snapshot.cost_accrued_usdc if snapshot else 0.0,
            latest_merkle_root=snapshot.latest_merkle_root if snapshot else None,
            anchored_count=snapshot.anchored_receipts if snapshot else 0,
        )

        message = WSMessage(
            event="state.changed",
            task_id=task_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )

        await self.push_event(task_id, message)

    # ── Proof Request ──────────────────────────────────────────────────────

    async def request_proof(self, task_id: str, receipt_id: str) -> Optional[dict]:
        """Request a proof for a specific receipt.

        Returns the proof data if available, or None.
        In a full implementation, this would generate a Merkle inclusion proof.
        """
        from datetime import datetime, timezone

        response = WSMessage(
            event="proof.response",
            task_id=task_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=WSPayload(),
        )

        await self.push_event(task_id, response)
        return response.to_dict()

    # ── Queries ────────────────────────────────────────────────────────────

    def subscriber_count(self, task_id: Optional[str] = None) -> int:
        """Number of connected subscribers for a task (or total)."""
        if task_id:
            return len(self._subscriptions.get(task_id, set()))
        return sum(len(subs) for subs in self._subscriptions.values())

    def active_tasks(self) -> List[str]:
        """List of task IDs with active subscribers."""
        return list(self._subscriptions.keys())
