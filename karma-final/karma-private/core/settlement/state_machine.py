"""
PRIVATE — Karma Runtime Settlement State Machine
=================================================
Full implementation. Contains:
- Release / refund / dispute decision rules
- Partial settlement split calculation
- Buyer / seller win conditions
- Escrow release authorization logic

DO NOT commit to public repository.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import structlog

from config.settings import settings  # private settings with production values
from core.schemas import (
    SettlementState,
    TaskStatus,
    VerificationDecision,
    VerificationResult,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Transition table (same as public — only decision handlers are private)
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[TaskStatus, list[TaskStatus]] = {
    TaskStatus.CREATED:     [TaskStatus.LOCKED],
    TaskStatus.LOCKED:      [TaskStatus.RUNNING, TaskStatus.REFUNDED],
    TaskStatus.RUNNING:     [TaskStatus.SUBMITTED, TaskStatus.FAILED],
    TaskStatus.SUBMITTED:   [TaskStatus.VERIFYING, TaskStatus.DISPUTED],
    TaskStatus.VERIFYING:   [TaskStatus.VERIFIED, TaskStatus.DISPUTED, TaskStatus.REFUNDED],
    TaskStatus.VERIFIED:    [TaskStatus.RELEASED],
    TaskStatus.DISPUTED:    [TaskStatus.ARBITRATION],
    TaskStatus.ARBITRATION: [TaskStatus.BUYER_WINS, TaskStatus.SELLER_WINS, TaskStatus.PARTIAL],
    TaskStatus.FAILED:      [TaskStatus.REFUNDED],
    TaskStatus.RELEASED:    [],
    TaskStatus.REFUNDED:    [],
    TaskStatus.BUYER_WINS:  [],
    TaskStatus.SELLER_WINS: [],
    TaskStatus.PARTIAL:     [],
}


# ---------------------------------------------------------------------------
# PRIVATE: Partial settlement split rules
# ---------------------------------------------------------------------------

def _calculate_partial_split(
    escrow_amount: float,
    verification_confidence: float,
    successful_steps: int,
    total_steps: int,
) -> tuple[float, float]:
    """
    PRIVATE: Calculate worker payout and client refund for partial settlement.

    Formula:
        step_completion_ratio × confidence_weight × escrow_amount

    confidence_weight: scales payout based on verification confidence.
    The remainder goes back to client.
    """
    if total_steps == 0:
        return 0.0, escrow_amount

    step_ratio = successful_steps / total_steps
    confidence_weight = max(0.0, min(1.0, verification_confidence))

    # Worker gets: step_ratio * confidence_weighted portion
    # Confidence weight dampens payout when verification is uncertain
    worker_fraction = step_ratio * (0.5 + 0.5 * confidence_weight)
    worker_amount = round(escrow_amount * worker_fraction, 2)
    client_amount = round(escrow_amount - worker_amount, 2)

    return worker_amount, client_amount


# ---------------------------------------------------------------------------
# PRIVATE: Arbitration win conditions
# ---------------------------------------------------------------------------

def _evaluate_arbitration_evidence(
    dispute_reason: str,
    verification_confidence: float,
    successful_steps: int,
    total_steps: int,
    escrow_amount: float,
) -> tuple[TaskStatus, float | None, float | None, str]:
    """
    PRIVATE: Determine arbitration outcome from evidence signals.

    Returns: (decision, released_amount, refunded_amount, notes)

    Win condition rules:
    - High confidence + high completion  → SELLER_WINS (full release)
    - Low confidence + low completion    → BUYER_WINS  (full refund)
    - Mixed signals                      → PARTIAL     (split)
    """
    step_ratio = successful_steps / total_steps if total_steps > 0 else 0.0

    # Seller wins: strong evidence of good work
    if verification_confidence >= 0.75 and step_ratio >= 0.80:
        return (
            TaskStatus.SELLER_WINS,
            escrow_amount,
            None,
            f"Strong execution evidence: {step_ratio:.0%} steps, confidence {verification_confidence:.0%}",
        )

    # Buyer wins: clear failure
    if verification_confidence < 0.40 or step_ratio < 0.30:
        return (
            TaskStatus.BUYER_WINS,
            None,
            escrow_amount,
            f"Insufficient execution evidence: {step_ratio:.0%} steps, confidence {verification_confidence:.0%}",
        )

    # Partial: ambiguous — split proportionally
    worker_amount, client_amount = _calculate_partial_split(
        escrow_amount, verification_confidence, successful_steps, total_steps
    )
    return (
        TaskStatus.PARTIAL,
        worker_amount,
        client_amount,
        f"Partial settlement: worker ${worker_amount}, client ${client_amount}",
    )


# ---------------------------------------------------------------------------
# Settlement State Machine
# ---------------------------------------------------------------------------

class PrivateSettlementStateMachine:
    """
    Full settlement state machine with private decision logic.
    """

    def __init__(self, store: "SettlementStore"):
        self.store = store

    async def create(
        self,
        task_id: str,
        client_agent_id: str,
        escrow_amount: float,
        currency: str = "USD",
    ) -> SettlementState:
        if escrow_amount < settings.escrow_min_amount:
            raise ValueError(f"Escrow amount below minimum ({settings.escrow_min_amount})")
        if escrow_amount > settings.escrow_max_amount:
            raise ValueError(f"Escrow amount above maximum ({settings.escrow_max_amount})")

        state = SettlementState(
            task_id=task_id,
            escrow_amount=escrow_amount,
            currency=currency,
            client_agent_id=client_agent_id,
            status=TaskStatus.CREATED,
        )
        await self.store.save(state)
        logger.info("settlement_created", task_id=task_id, amount=escrow_amount)
        return state

    async def _transition(
        self, task_id: str, to: TaskStatus, **kwargs
    ) -> SettlementState:
        state = await self.store.get(task_id)
        if not state:
            raise ValueError(f"No settlement for task {task_id}")
        allowed = VALID_TRANSITIONS.get(state.status, [])
        if to not in allowed:
            raise ValueError(
                f"Invalid transition {state.status} → {to}. Allowed: {[s.value for s in allowed]}"
            )
        state.status = to
        state.updated_at = datetime.utcnow()
        for k, v in kwargs.items():
            if hasattr(state, k):
                setattr(state, k, v)
        await self.store.save(state)
        logger.info("settlement_transition", task_id=task_id, to=to)
        return state

    async def lock(self, task_id: str, worker_agent_id: str) -> SettlementState:
        return await self._transition(task_id, TaskStatus.LOCKED, worker_agent_id=worker_agent_id)

    async def start(self, task_id: str) -> SettlementState:
        return await self._transition(task_id, TaskStatus.RUNNING)

    async def submit(self, task_id: str) -> SettlementState:
        return await self._transition(task_id, TaskStatus.SUBMITTED)

    async def apply_verification(
        self,
        task_id: str,
        result: VerificationResult,
    ) -> SettlementState:
        await self._transition(task_id, TaskStatus.VERIFYING)

        # --- PRIVATE DECISION LOGIC ---
        if result.decision == VerificationDecision.RELEASE:
            return await self._release(task_id, result)

        elif result.decision == VerificationDecision.HOLD:
            # Stay in VERIFYING; flagged for ops review
            logger.warning("settlement_on_hold", task_id=task_id, notes=result.notes)
            return await self.store.get(task_id)

        elif result.decision == VerificationDecision.REFUND:
            return await self._refund(task_id, result)

        elif result.decision == VerificationDecision.DISPUTE:
            return await self._dispute_and_arbitrate(task_id, result)

        raise ValueError(f"Unknown verification decision: {result.decision}")

    async def _release(self, task_id: str, result: VerificationResult) -> SettlementState:
        state = await self.store.get(task_id)
        state = await self._transition(task_id, TaskStatus.VERIFIED)
        return await self._transition(
            task_id,
            TaskStatus.RELEASED,
            released_amount=state.escrow_amount,
            released_at=datetime.utcnow(),
        )

    async def _refund(self, task_id: str, result: VerificationResult) -> SettlementState:
        state = await self.store.get(task_id)
        return await self._transition(
            task_id,
            TaskStatus.REFUNDED,
            refunded_amount=state.escrow_amount,
            dispute_reason=result.notes,
        )

    async def _dispute_and_arbitrate(
        self, task_id: str, result: VerificationResult
    ) -> SettlementState:
        state = await self.store.get(task_id)
        await self._transition(task_id, TaskStatus.DISPUTED, dispute_reason=result.notes)
        await self._transition(task_id, TaskStatus.ARBITRATION)

        # --- AUTO-ARBITRATION using private win conditions ---
        bundle = result  # confidence and checks available in result
        successful = sum(1 for c in result.checks if c.name == "success_rate" and c.passed)
        total = result.confidence  # proxy for step completion in auto-arb

        decision, released, refunded, notes = _evaluate_arbitration_evidence(
            dispute_reason=result.notes or "",
            verification_confidence=result.confidence,
            successful_steps=int(result.confidence * 10),   # normalized proxy
            total_steps=10,
            escrow_amount=state.escrow_amount,
        )

        return await self._transition(
            task_id,
            decision,
            released_amount=released,
            refunded_amount=refunded,
            arbitration_notes=notes,
            released_at=datetime.utcnow() if released else None,
        )

    async def fail(self, task_id: str) -> SettlementState:
        state = await self.store.get(task_id)
        await self._transition(task_id, TaskStatus.FAILED)
        return await self._transition(
            task_id, TaskStatus.REFUNDED, refunded_amount=state.escrow_amount
        )

    async def get(self, task_id: str) -> Optional[SettlementState]:
        return await self.store.get(task_id)


# ---------------------------------------------------------------------------
# Store interface (private — includes admin methods)
# ---------------------------------------------------------------------------

class SettlementStore:
    async def save(self, state: SettlementState) -> None:
        raise NotImplementedError

    async def get(self, task_id: str) -> Optional[SettlementState]:
        raise NotImplementedError

    async def list_by_status(self, status: TaskStatus) -> list[SettlementState]:
        raise NotImplementedError

    async def admin_override(self, task_id: str, to: TaskStatus, reason: str) -> SettlementState:
        """PRIVATE: Admin override for ops escalations. Never exposed via public API."""
        raise NotImplementedError
