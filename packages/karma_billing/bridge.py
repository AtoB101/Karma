"""
AnchoringBridge — Connect ReceiptSyncService to IncrementalMerkleAnchor
=========================================================================

Bridges the Karma billing/receipt pipeline with Solana Merkle tree anchoring.
Controls when receipts are anchored based on configurable policies.

Usage
-----
    from karma_solana import IncrementalMerkleAnchor, AnchorResult
    from karma_billing.bridge import AnchoringBridge, AnchoringPolicy

    policy = AnchoringPolicy(
        anchor_every_n_receipts=3,
        anchor_every_n_seconds=30,
    )
    bridge = AnchoringBridge(
        sync_service=receipt_sync,
        merkle_anchor=merkle_anchor,
        policy=policy,
    )

    result = await bridge.check_and_anchor("task-001")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ── Data Classes ───────────────────────────────────────────────────

@dataclass
class AnchoringPolicy:
    """
    Policy controlling when receipts are anchored to Solana.

    Parameters
    ----------
    anchor_every_n_receipts : int
        Anchor after accumulating N new receipts. 0 = disabled.
    anchor_every_n_seconds : int
        Anchor after N seconds since last anchor. 0 = disabled.
    anchor_on_state_change : bool
        Anchor immediately when the billing state changes.
    anchor_on_milestone : bool
        Anchor on key milestones (funded, delivered, verified, etc.).
    force_anchor_states : list[str]
        Billing states that trigger an immediate force anchor.
    max_batch_size : int
        Maximum number of receipts per anchor transaction.
    min_batch_size : int
        Minimum receipts to batch before anchoring (unless forced).
    """

    anchor_every_n_receipts: int = 3
    anchor_every_n_seconds: int = 30
    anchor_on_state_change: bool = True
    anchor_on_milestone: bool = True
    force_anchor_states: list[str] = field(default_factory=lambda: [
        "funded",
        "delivered",
        "verified",
        "settled",
        "disputed",
        "frozen",
    ])
    max_batch_size: int = 10
    min_batch_size: int = 1


@dataclass
class _AnchoringState:
    """Internal tracking state for anchoring decisions."""
    task_id: str
    unanchored_count: int = 0
    last_anchor_time: float = 0.0
    last_state: str = ""
    total_anchored: int = 0
    last_result: Optional[Any] = None  # AnchorResult


@dataclass
class _ReceiptBatch:
    """A batch of receipts waiting to be anchored."""
    receipts: list = field(default_factory=list)
    state: str = ""
    created_at: float = 0.0


# ── Abstract Interfaces ────────────────────────────────────────────

class ReceiptSyncService:
    """
    Abstract interface for receipt synchronization.

    Implement this to connect Karma's billing/receipt pipeline.
    The bridge calls these methods to check receipt state.
    """

    async def get_unanchored_receipts(self, task_id: str, limit: int = 100) -> list:
        """Get receipts that haven't been anchored yet."""
        raise NotImplementedError

    async def get_task_state(self, task_id: str) -> str:
        """Get the current billing state for a task."""
        raise NotImplementedError

    async def mark_anchored(self, task_id: str, receipt_ids: list[str], anchor_result: Any) -> None:
        """Mark receipts as anchored after successful submission."""
        raise NotImplementedError


class SimpleMemReceiptSync(ReceiptSyncService):
    """
    In-memory receipt sync service for testing and development.

    Stores receipts in memory and tracks anchoring status.
    """

    def __init__(self) -> None:
        self._receipts: dict[str, list[dict]] = {}
        self._states: dict[str, str] = {}
        self._anchored: dict[str, set] = {}

    def add_receipt(self, task_id: str, receipt: dict) -> None:
        """Add a receipt for a task."""
        if task_id not in self._receipts:
            self._receipts[task_id] = []
        self._receipts[task_id].append(receipt)

    def set_state(self, task_id: str, state: str) -> None:
        """Set the billing state for a task."""
        self._states[task_id] = state

    async def get_unanchored_receipts(self, task_id: str, limit: int = 100) -> list:
        """Return receipts that haven't been anchored yet."""
        all_receipts = self._receipts.get(task_id, [])
        anchored = self._anchored.get(task_id, set())
        unanchored = [r for i, r in enumerate(all_receipts) if r.get("id", f"rec-{i}") not in anchored]
        return unanchored[:limit]

    async def get_task_state(self, task_id: str) -> str:
        """Get the current billing state."""
        return self._states.get(task_id, "unknown")

    async def mark_anchored(self, task_id: str, receipt_ids: list[str], anchor_result: Any) -> None:
        """Mark receipts as anchored."""
        if task_id not in self._anchored:
            self._anchored[task_id] = set()
        self._anchored[task_id].update(receipt_ids)


# ── AnchoringBridge ────────────────────────────────────────────────

class AnchoringBridge:
    """
    Bridge that connects the receipt sync service to the Merkle anchor.

    Implements policy-based anchoring:
    - Accumulate N receipts → anchor batch
    - Time-based periodic anchoring
    - Force anchor on critical state changes

    Parameters
    ----------
    sync_service : ReceiptSyncService
        Service that provides unanchored receipts.
    merkle_anchor : IncrementalMerkleAnchor
        Solana Merkle tree anchor client.
    policy : AnchoringPolicy
        Policy controlling anchoring triggers.
    """

    def __init__(
        self,
        sync_service: ReceiptSyncService,
        merkle_anchor: Any,  # IncrementalMerkleAnchor (lazy import)
        policy: Optional[AnchoringPolicy] = None,
    ) -> None:
        self._sync = sync_service
        self._anchor = merkle_anchor
        self._policy = policy or AnchoringPolicy()
        self._states: dict[str, _AnchoringState] = {}
        self._batches: dict[str, _ReceiptBatch] = {}

    @property
    def policy(self) -> AnchoringPolicy:
        return self._policy

    async def check_and_anchor(self, task_id: str) -> Optional[Any]:
        """
        Check if anchoring should be triggered for a task based on policy.

        Returns
        -------
        AnchorResult | None
            The anchor result if anchoring was triggered, None otherwise.
        """
        # Get or create state
        if task_id not in self._states:
            self._states[task_id] = _AnchoringState(task_id=task_id)
        state = self._states[task_id]

        # Get current billing state
        current_state = await self._sync.get_task_state(task_id)
        state_changed = (current_state != state.last_state)

        # Check force-anchor states
        if state_changed and current_state in self._policy.force_anchor_states:
            logger.info(
                "Force anchoring task=%s: state %s → %s (force state)",
                task_id, state.last_state, current_state,
            )
            return await self.force_anchor(task_id)

        # Check milestone anchoring
        if (
            self._policy.anchor_on_milestone
            and state_changed
            and current_state in self._policy.force_anchor_states
        ):
            logger.info(
                "Milestone anchoring task=%s: state %s → %s",
                task_id, state.last_state, current_state,
            )
            return await self.force_anchor(task_id)

        # Get unanchored receipts
        receipts = await self._sync.get_unanchored_receipts(
            task_id,
            limit=self._policy.max_batch_size,
        )
        state.unanchored_count = len(receipts)
        state.last_state = current_state

        # Check count-based trigger
        if (
            self._policy.anchor_every_n_receipts > 0
            and state.unanchored_count >= self._policy.anchor_every_n_receipts
        ):
            logger.info(
                "Count-based anchoring task=%s: %d receipts accumulated",
                task_id, state.unanchored_count,
            )
            return await self._do_anchor(task_id, receipts)

        # Check time-based trigger
        now = time.time()
        if (
            self._policy.anchor_every_n_seconds > 0
            and state.last_anchor_time > 0
            and (now - state.last_anchor_time) >= self._policy.anchor_every_n_seconds
            and state.unanchored_count >= self._policy.min_batch_size
        ):
            logger.info(
                "Time-based anchoring task=%s: %.0fs since last anchor, %d receipts",
                task_id, now - state.last_anchor_time, state.unanchored_count,
            )
            return await self._do_anchor(task_id, receipts)

        # Check state-change trigger
        if self._policy.anchor_on_state_change and state_changed:
            logger.info(
                "State-change anchoring task=%s: %s → %s",
                task_id, state.last_state, current_state,
            )
            return await self._do_anchor(task_id, receipts)

        return None

    async def force_anchor(self, task_id: str) -> Any:
        """
        Force immediate anchoring of all unanchored receipts for a task.

        Ignores count/time thresholds — used for critical state transitions.
        """
        receipts = await self._sync.get_unanchored_receipts(
            task_id,
            limit=self._policy.max_batch_size,
        )
        if not receipts:
            logger.warning("No unanchored receipts for task=%s", task_id)
            return None

        return await self._do_anchor(task_id, receipts)

    async def _do_anchor(self, task_id: str, receipts: list[dict]) -> Any:
        """
        Execute the anchoring: convert receipts to UniversalReceipt, append to tree.

        Parameters
        ----------
        task_id : str
            Task identifier.
        receipts : list[dict]
            Receipt dictionaries from sync service.

        Returns
        -------
        AnchorResult
        """
        if not receipts:
            return None

        # Convert dict receipts to UniversalReceipt objects
        from karma_solana.merkle_anchor import UniversalReceipt

        universal_receipts = []
        for receipt in receipts:
            task_id_bytes = _str_to_fixed_bytes(task_id, 16)
            receipt_data = _serialize_receipt(receipt)
            scenario = receipt.get("scenario", "default")
            billing_state = receipt.get("billing_state", "unknown")
            cost = receipt.get("cost_accrued_usdc", 0)

            universal_receipts.append(UniversalReceipt(
                task_id=task_id_bytes,
                receipt_data=receipt_data,
                scenario=scenario,
                billing_state=billing_state,
                cost_accrued_usdc=cost,
            ))

        # Append to Merkle tree
        result = await self._anchor.append_batch(universal_receipts)

        # Update state
        state = self._states.get(task_id, _AnchoringState(task_id=task_id))
        receipt_ids = [r.get("id", "") for r in receipts]
        await self._sync.mark_anchored(task_id, receipt_ids, result)

        state.last_anchor_time = time.time()
        state.total_anchored += len(receipts)
        state.unanchored_count = 0
        state.last_result = result
        self._states[task_id] = state

        logger.info(
            "Anchored %d receipts for task=%s: sig=%s, root=%s",
            len(receipts),
            task_id,
            getattr(result, "signature", "?"),
            getattr(result, "new_root", "?")[:16] + "...",
        )

        return result

    def get_state(self, task_id: str) -> Optional[_AnchoringState]:
        """Get the internal anchoring state for a task."""
        return self._states.get(task_id)

    async def start_periodic_check(self, task_id: str, interval: float = 5.0) -> None:
        """
        Start a background periodic check for anchoring triggers.

        Note: This is a simple coroutine-based periodic checker.
        For production, integrate with the task scheduler.

        Parameters
        ----------
        task_id : str
            Task to monitor.
        interval : float
            Check interval in seconds.
        """
        logger.info("Starting periodic anchor check for task=%s (every %.1fs)", task_id, interval)
        while True:
            try:
                await self.check_and_anchor(task_id)
            except Exception as e:
                logger.error("Periodic check failed for task=%s: %s", task_id, e)
            await asyncio.sleep(interval)


# ── Helpers ─────────────────────────────────────────────────────────

def _str_to_fixed_bytes(s: str, length: int) -> bytes:
    """Convert a string to fixed-length bytes."""
    return s.encode("utf-8")[:length].ljust(length, b"\x00")


def _serialize_receipt(receipt: dict) -> bytes:
    """Serialize a receipt dict to deterministic bytes for hashing."""
    import json
    # Sort keys for deterministic output
    return json.dumps(receipt, sort_keys=True, default=str).encode("utf-8")


# ── Convenience Factory ────────────────────────────────────────────

def create_bridge(
    sync_service: ReceiptSyncService,
    solana_client: Any,
    program_id: str,
    tree_address: Any,
    payer_keypair: Any,
    policy: Optional[AnchoringPolicy] = None,
    simulate: bool = True,
) -> AnchoringBridge:
    """
    Convenience factory to create an AnchoringBridge with all dependencies wired.

    Parameters
    ----------
    sync_service : ReceiptSyncService
        Receipt sync service implementation.
    solana_client : AsyncClient
        Solana RPC client.
    program_id : str
        karma_anchor program ID.
    tree_address : Pubkey | str
        Merkle tree PDA address.
    payer_keypair : Keypair
        Transaction payer.
    policy : AnchoringPolicy | None
        Anchoring policy (uses defaults if None).
    simulate : bool
        If True, simulate transactions instead of submitting.

    Returns
    -------
    AnchoringBridge
    """
    from karma_solana.merkle_anchor import IncrementalMerkleAnchor

    anchor = IncrementalMerkleAnchor(
        solana_client=solana_client,
        program_id=program_id,
        tree_address=tree_address,
        payer_keypair=payer_keypair,
        simulate=simulate,
    )

    return AnchoringBridge(
        sync_service=sync_service,
        merkle_anchor=anchor,
        policy=policy,
    )


# ── Re-export ──────────────────────────────────────────────────────

__all__ = [
    "AnchoringBridge",
    "AnchoringPolicy",
    "ReceiptSyncService",
    "SimpleMemReceiptSync",
    "create_bridge",
    "_AnchoringState",
]
