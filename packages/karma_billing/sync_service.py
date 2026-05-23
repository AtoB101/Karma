"""Receipt Sync Service — three-route fanout for every UniversalReceipt.

Every receipt flows through three routes simultaneously:

1.  **Route 1: PostgreSQL INSERT** — async persistent storage (deferred to DB layer)
2.  **Route 2: Redis Pub/Sub** — real-time event notification (InMemoryPubSub by default)
3.  **Route 3: IncrementalMerkleAccumulator** — cryptographic anchoring via leaf hashes

After fanout, the service checks anchoring policy to decide whether an on-chain
anchor should be triggered.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from packages.karma_billing.schema import UniversalReceipt, BillingState

logger = logging.getLogger("karma.billing.sync_service")


# ── Sync Result ───────────────────────────────────────────────────────────────


class SyncRouteStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class SyncResult:
    """Result of a single receipt sync operation."""

    receipt_id: str
    pg_status: SyncRouteStatus = SyncRouteStatus.SUCCESS
    pubsub_status: SyncRouteStatus = SyncRouteStatus.SUCCESS
    merkle_status: SyncRouteStatus = SyncRouteStatus.SUCCESS
    anchoring_triggered: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(
            s in (SyncRouteStatus.SUCCESS, SyncRouteStatus.SKIPPED)
            for s in [self.pg_status, self.pubsub_status, self.merkle_status]
        )


# ── InMemory Pub/Sub ──────────────────────────────────────────────────────────


class InMemoryPubSub:
    """Simple in-memory pub/sub implementation.

    Replaceable with Redis Pub/Sub in production.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[dict[str, Any]], None]]] = {}

    def subscribe(self, channel: str, callback: Callable[[dict[str, Any]], None]) -> None:
        """Subscribe to a channel with a callback."""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)
        logger.debug("Subscribed to channel: %s (total: %d)", channel, len(self._subscribers[channel]))

    def unsubscribe(self, channel: str, callback: Callable[[dict[str, Any]], None]) -> None:
        """Unsubscribe from a channel."""
        if channel in self._subscribers:
            self._subscribers[channel] = [
                cb for cb in self._subscribers[channel] if cb is not callback
            ]
            if not self._subscribers[channel]:
                del self._subscribers[channel]

    def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Publish a message to all subscribers on a channel."""
        if channel in self._subscribers:
            for callback in self._subscribers[channel]:
                try:
                    callback(message)
                except Exception:
                    logger.exception(
                        "Error in subscriber callback for channel=%s", channel
                    )

    def publish_async(self, channel: str, message: dict[str, Any]) -> None:
        """Alias for publish — sync in-memory version."""
        self.publish(channel, message)

    @property
    def subscriber_count(self) -> Dict[str, int]:
        return {ch: len(cbs) for ch, cbs in self._subscribers.items()}


# ── Incremental Merkle Accumulator ────────────────────────────────────────────


class IncrementalMerkleAccumulator:
    """Append-only Merkle tree accumulator for cryptographic anchoring.

    Leaf hashes are appended in insertion order.  The accumulator periodically
    produces a Merkle root that can be anchored on-chain.

    This is a simplified implementation — production should use a more
    efficient structure (e.g., sparse Merkle tree or append-only log).
    """

    def __init__(self) -> None:
        self._leaves: List[bytes] = []
        self._anchor_count: int = 0

    def append(self, leaf_hash: bytes) -> int:
        """Append a leaf hash and return its index."""
        index = len(self._leaves)
        self._leaves.append(leaf_hash)
        logger.debug("Merkle leaf %d appended: %s", index, leaf_hash.hex()[:16])
        return index

    def compute_root(self) -> Optional[str]:
        """Compute the current Merkle root.

        Uses simple pairing: hash consecutive pairs until one hash remains.
        Empty tree returns None.
        """
        if not self._leaves:
            return None

        current_level = list(self._leaves)

        while len(current_level) > 1:
            next_level: List[bytes] = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                right = current_level[i + 1] if i + 1 < len(current_level) else left
                combined = left + right
                next_level.append(hashlib.sha256(combined).digest())
            current_level = next_level

        return current_level[0].hex() if current_level else None

    @property
    def leaf_count(self) -> int:
        return len(self._leaves)

    @property
    def anchor_count(self) -> int:
        return self._anchor_count

    def mark_anchored(self) -> str:
        """Mark current state as anchored, increment counter, return root."""
        root = self.compute_root() or ""
        self._anchor_count += 1
        return root


# ── ReceiptSyncService ────────────────────────────────────────────────────────


class ReceiptSyncService:
    """Orchestrates the three-route sync pipeline for every UniversalReceipt.

    Usage::

        svc = ReceiptSyncService()
        result = await svc.sync(receipt)

    The service is intentionally database-agnostic at the Python layer.
    Route 1 (PostgreSQL) emits a hook that integrators wire to their DB layer.
    Route 2 (Pub/Sub) uses InMemoryPubSub by default (swap for Redis in prod).
    Route 3 (Merkle) always appends the leaf hash.
    """

    def __init__(
        self,
        pubsub: Optional[InMemoryPubSub] = None,
        merkle: Optional[IncrementalMerkleAccumulator] = None,
        anchoring_threshold: int = 10,
    ) -> None:
        self._pubsub = pubsub or InMemoryPubSub()
        self._merkle = merkle or IncrementalMerkleAccumulator()
        self._anchoring_threshold = anchoring_threshold

        # Hook for Route 1 — integrators set this to their async DB insert func
        self._pg_insert_hook: Optional[
            Callable[[UniversalReceipt], Any]
        ] = None

        # Track receipts per task for anchoring policy
        self._task_receipt_count: Dict[str, int] = {}

    def set_pg_insert_hook(self, hook: Callable[[UniversalReceipt], Any]) -> None:
        """Set the PostgreSQL insert hook for Route 1."""
        self._pg_insert_hook = hook

    async def sync(self, receipt: UniversalReceipt) -> SyncResult:
        """Fan-out a UniversalReceipt through all three routes simultaneously.

        Each route is processed independently — one route's failure does not
        block the others.
        """
        result = SyncResult(receipt_id=receipt.receipt_id)

        # ── Route 1: PostgreSQL INSERT ──
        if self._pg_insert_hook:
            try:
                await self._pg_insert_hook(receipt)  # type: ignore[misc]
                result.pg_status = SyncRouteStatus.SUCCESS
            except Exception as e:
                result.pg_status = SyncRouteStatus.FAILED
                result.errors.append(f"PG: {e}")
                logger.error(
                    "Route 1 (PG) failed for receipt=%s: %s",
                    receipt.receipt_id,
                    e,
                )
        else:
            result.pg_status = SyncRouteStatus.SKIPPED
            logger.debug("Route 1 (PG) skipped — no insert hook configured")

        # ── Route 2: Pub/Sub ──
        try:
            channel = f"karma:billing:receipts:{receipt.task_id}"
            message = receipt.model_dump(mode="json")
            self._pubsub.publish(channel, message)
            result.pubsub_status = SyncRouteStatus.SUCCESS
        except Exception as e:
            result.pubsub_status = SyncRouteStatus.FAILED
            result.errors.append(f"PubSub: {e}")
            logger.error(
                "Route 2 (PubSub) failed for receipt=%s: %s",
                receipt.receipt_id,
                e,
            )

        # ── Route 3: Merkle Accumulator ──
        try:
            leaf = receipt.compute_leaf()
            index = self._merkle.append(leaf)
            result.merkle_status = SyncRouteStatus.SUCCESS
            logger.debug(
                "Route 3 (Merkle) leaf=%d for receipt=%s",
                index,
                receipt.receipt_id,
            )
        except Exception as e:
            result.merkle_status = SyncRouteStatus.FAILED
            result.errors.append(f"Merkle: {e}")
            logger.error(
                "Route 3 (Merkle) failed for receipt=%s: %s",
                receipt.receipt_id,
                e,
            )

        # ── Check Anchoring Policy ──
        task_id = receipt.task_id
        count = self._task_receipt_count.get(task_id, 0) + 1
        self._task_receipt_count[task_id] = count

        if count % self._anchoring_threshold == 0:
            root = self._merkle.compute_root()
            result.anchoring_triggered = True
            logger.info(
                "Anchoring triggered for task=%s at receipt_count=%d, root=%s",
                task_id,
                count,
                root,
            )

        return result

    def get_merkle_root(self) -> Optional[str]:
        """Get the current Merkle root."""
        return self._merkle.compute_root()

    @property
    def pubsub(self) -> InMemoryPubSub:
        return self._pubsub

    @property
    def merkle(self) -> IncrementalMerkleAccumulator:
        return self._merkle
