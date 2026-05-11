"""
PRIVATE — Karma Runtime Reputation Scoring System
===================================================
Full implementation. Contains:
- Score delta weights per outcome
- Time-decay algorithm
- Behavior multipliers
- Anti-gaming rules
- Leaderboard calculation

DO NOT commit to public repository.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

import structlog

from core.schemas import AgentRole, ReputationSnapshot, TaskStatus

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# PRIVATE: Score delta table
# ---------------------------------------------------------------------------

SCORE_DELTAS: dict[str, float] = {
    "task_success":             +10.0,
    "task_failure":             -15.0,
    "task_disputed":             -5.0,
    "arbitration_win":          +20.0,
    "arbitration_loss":         -25.0,
    "partial_as_seller":         -3.0,
    "partial_as_buyer":          -1.0,
    "refunded_as_seller":       -12.0,
    "refunded_as_buyer":         +2.0,   # small signal: got money back

    # Bonus multipliers (applied on top of base deltas)
    "high_verification_confidence_bonus":   +5.0,   # confidence > 0.95
    "fast_execution_bonus":                 +2.0,   # < 5s total
    "perfect_receipt_bonus":                +3.0,   # all checks passed
    "consecutive_success_streak_bonus":     +1.0,   # per streak step (max +10)
}

# PRIVATE: Time-decay parameters
DECAY_CONFIG = {
    "base_factor":      0.95,       # applied per task (not per day)
    "half_life_tasks":  50,         # score halves every 50 tasks
    "floor":            0.0,
    "ceiling":         1000.0,
    "initial_score":   100.0,
}

# PRIVATE: Anti-gaming thresholds
ANTI_GAMING = {
    "max_streak_bonus":         10.0,
    "dispute_rate_penalty_at":  0.20,   # > 20% dispute rate → extra penalty
    "dispute_rate_penalty":     -5.0,   # per task above threshold
    "low_volume_cliff":          5,     # score is provisional below this
    "wash_trade_score_zero":    True,   # wash traders get score zeroed
}


# ---------------------------------------------------------------------------
# Internal record (includes fields not exposed publicly)
# ---------------------------------------------------------------------------

class _ReputationRecord:
    def __init__(self, agent_id: str, role: AgentRole):
        self.agent_id = agent_id
        self.role = role
        self.score: float = DECAY_CONFIG["initial_score"]
        self.total_tasks: int = 0
        self.successful_tasks: int = 0
        self.disputed_tasks: int = 0
        self.arbitration_wins: int = 0
        self.arbitration_losses: int = 0
        self.consecutive_successes: int = 0
        self.wash_trade_flags: int = 0
        self.last_updated: datetime = datetime.utcnow()

    @property
    def success_rate(self) -> float:
        return self.successful_tasks / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def dispute_rate(self) -> float:
        return self.disputed_tasks / self.total_tasks if self.total_tasks > 0 else 0.0

    def to_snapshot(self) -> ReputationSnapshot:
        return ReputationSnapshot(
            agent_id=self.agent_id,
            role=self.role,
            score=round(self.score, 2),
            total_tasks=self.total_tasks,
            successful_tasks=self.successful_tasks,
            disputed_tasks=self.disputed_tasks,
            success_rate=round(self.success_rate, 4),
            last_updated=self.last_updated,
        )


# ---------------------------------------------------------------------------
# Private Reputation System
# ---------------------------------------------------------------------------

class PrivateReputationSystem:
    """
    Computes and maintains agent reputation scores.
    All scoring logic is private.
    """

    def __init__(self, store: "ReputationStore"):
        self.store = store

    async def update(
        self,
        agent_id: str,
        role: AgentRole,
        final_status: TaskStatus,
        verification_confidence: Optional[float] = None,
        total_duration_ms: Optional[int] = None,
        all_checks_passed: bool = False,
        is_wash_trade: bool = False,
    ) -> ReputationSnapshot:
        record = await self._get_or_create(agent_id, role)

        # --- Anti-gaming: wash trade zeroing ---
        if is_wash_trade:
            record.wash_trade_flags += 1
            if ANTI_GAMING["wash_trade_score_zero"]:
                record.score = DECAY_CONFIG["floor"]
                record.total_tasks += 1
                await self.store.save(record)
                logger.warning("wash_trade_score_zeroed", agent_id=agent_id)
                return record.to_snapshot()

        # --- Time decay ---
        record.score = self._apply_decay(record.score)
        record.total_tasks += 1

        delta = self._compute_delta(
            record=record,
            role=role,
            final_status=final_status,
            verification_confidence=verification_confidence,
            total_duration_ms=total_duration_ms,
            all_checks_passed=all_checks_passed,
        )

        # --- Anti-gaming: dispute rate penalty ---
        if record.dispute_rate > ANTI_GAMING["dispute_rate_penalty_at"]:
            delta += ANTI_GAMING["dispute_rate_penalty"]

        # --- Apply ---
        record.score = self._clamp(record.score + delta)
        record.last_updated = datetime.utcnow()
        await self.store.save(record)

        logger.info(
            "reputation_updated",
            agent_id=agent_id,
            delta=round(delta, 2),
            new_score=round(record.score, 2),
            final_status=final_status,
        )
        return record.to_snapshot()

    def _compute_delta(
        self,
        record: _ReputationRecord,
        role: AgentRole,
        final_status: TaskStatus,
        verification_confidence: Optional[float],
        total_duration_ms: Optional[int],
        all_checks_passed: bool,
    ) -> float:
        delta = 0.0

        if final_status == TaskStatus.RELEASED:
            record.successful_tasks += 1
            record.consecutive_successes += 1
            delta += SCORE_DELTAS["task_success"]

            # Bonus: verification confidence
            if verification_confidence and verification_confidence > 0.95:
                delta += SCORE_DELTAS["high_verification_confidence_bonus"]

            # Bonus: fast execution
            if total_duration_ms and total_duration_ms < 5_000:
                delta += SCORE_DELTAS["fast_execution_bonus"]

            # Bonus: all checks passed
            if all_checks_passed:
                delta += SCORE_DELTAS["perfect_receipt_bonus"]

            # Bonus: streak (capped)
            streak_bonus = min(
                record.consecutive_successes * SCORE_DELTAS["consecutive_success_streak_bonus"],
                ANTI_GAMING["max_streak_bonus"],
            )
            delta += streak_bonus

        elif final_status in (TaskStatus.FAILED, TaskStatus.REFUNDED):
            record.consecutive_successes = 0
            delta += SCORE_DELTAS["task_failure"]
            if role == AgentRole.WORKER:
                delta += SCORE_DELTAS["refunded_as_seller"]
            else:
                delta += SCORE_DELTAS["refunded_as_buyer"]

        elif final_status == TaskStatus.DISPUTED:
            record.consecutive_successes = 0
            record.disputed_tasks += 1
            delta += SCORE_DELTAS["task_disputed"]

        elif final_status == TaskStatus.BUYER_WINS:
            record.consecutive_successes = 0
            if role == AgentRole.CLIENT:
                record.arbitration_wins += 1
                delta += SCORE_DELTAS["arbitration_win"]
            else:
                record.arbitration_losses += 1
                delta += SCORE_DELTAS["arbitration_loss"]

        elif final_status == TaskStatus.SELLER_WINS:
            if role == AgentRole.WORKER:
                record.consecutive_successes += 1
                record.arbitration_wins += 1
                delta += SCORE_DELTAS["arbitration_win"]
            else:
                record.consecutive_successes = 0
                record.arbitration_losses += 1
                delta += SCORE_DELTAS["arbitration_loss"]

        elif final_status == TaskStatus.PARTIAL:
            record.consecutive_successes = 0
            if role == AgentRole.WORKER:
                delta += SCORE_DELTAS["partial_as_seller"]
            else:
                delta += SCORE_DELTAS["partial_as_buyer"]

        return delta

    def _apply_decay(self, score: float) -> float:
        """Exponential decay based on task count, not time."""
        return self._clamp(score * DECAY_CONFIG["base_factor"])

    def _clamp(self, score: float) -> float:
        return max(DECAY_CONFIG["floor"], min(DECAY_CONFIG["ceiling"], score))

    async def _get_or_create(self, agent_id: str, role: AgentRole) -> _ReputationRecord:
        record = await self.store.get(agent_id)
        if not record:
            record = _ReputationRecord(agent_id=agent_id, role=role)
            await self.store.save(record)
        return record

    async def leaderboard(self, limit: int = 50) -> list[ReputationSnapshot]:
        records = await self.store.top_n(limit)
        return [r.to_snapshot() for r in records]


# ---------------------------------------------------------------------------
# Store interface
# ---------------------------------------------------------------------------

class ReputationStore:
    async def save(self, record: _ReputationRecord) -> None:
        raise NotImplementedError

    async def get(self, agent_id: str) -> Optional[_ReputationRecord]:
        raise NotImplementedError

    async def top_n(self, n: int) -> list[_ReputationRecord]:
        raise NotImplementedError
