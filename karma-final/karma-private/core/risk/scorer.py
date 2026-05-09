"""
PRIVATE — Karma Runtime Risk Scoring
======================================
Computes a composite risk score for a task before settlement decisions
are made. Feeds into the Verification Engine's weighted decision.

Contains:
- Risk factor weights
- Malicious buyer detection signals
- Malicious agent detection signals
- High-risk task pattern flags

DO NOT commit to public repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from core.schemas import EvidenceBundle, ReputationSnapshot, TaskContract

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# PRIVATE: Risk factor weights
# ---------------------------------------------------------------------------

RISK_WEIGHTS: dict[str, float] = {
    # Buyer-side risk signals
    "buyer_low_reputation":         0.20,
    "buyer_high_dispute_rate":      0.25,
    "buyer_new_account":            0.10,
    "buyer_abnormal_escrow_amount": 0.10,

    # Worker-side risk signals
    "worker_low_reputation":        0.20,
    "worker_high_dispute_rate":     0.25,
    "worker_new_account":           0.10,
    "worker_wash_trade_history":    0.40,

    # Task-level signals
    "unusually_high_escrow":        0.15,
    "very_short_deadline":          0.10,
    "excessive_step_count":         0.08,
    "low_expected_step_count":      0.05,
}

# PRIVATE: Thresholds
RISK_THRESHOLDS = {
    "low_reputation_score":         50.0,
    "high_dispute_rate":            0.15,
    "new_account_task_minimum":     3,
    "high_escrow_multiple":         10.0,   # > 10x median = suspicious
    "short_deadline_hours":         0.5,
    "excessive_steps":              500,
    "composite_risk_hold_at":       0.40,
    "composite_risk_block_at":      0.70,
}

MEDIAN_ESCROW_AMOUNT = 50.0  # Updated periodically from production data


# ---------------------------------------------------------------------------
# Risk signal
# ---------------------------------------------------------------------------

@dataclass
class RiskSignal:
    name: str
    triggered: bool
    weight: float
    detail: Optional[str] = None

    @property
    def contribution(self) -> float:
        return self.weight if self.triggered else 0.0


@dataclass
class RiskAssessment:
    task_id: str
    composite_score: float          # 0.0 (no risk) to 1.0 (max risk)
    signals: list[RiskSignal] = field(default_factory=list)
    should_hold: bool = False
    should_block: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# Risk Scorer
# ---------------------------------------------------------------------------

class RiskScorer:
    """
    Computes a composite risk score for a task.
    Called before verification to flag high-risk settlements.
    """

    def assess(
        self,
        contract: TaskContract,
        buyer_rep: Optional[ReputationSnapshot],
        worker_rep: Optional[ReputationSnapshot],
    ) -> RiskAssessment:
        signals: list[RiskSignal] = []

        # --- Buyer signals ---
        signals.append(self._signal_low_reputation(
            "buyer_low_reputation", buyer_rep, RISK_WEIGHTS["buyer_low_reputation"]
        ))
        signals.append(self._signal_high_dispute_rate(
            "buyer_high_dispute_rate", buyer_rep, RISK_WEIGHTS["buyer_high_dispute_rate"]
        ))
        signals.append(self._signal_new_account(
            "buyer_new_account", buyer_rep, RISK_WEIGHTS["buyer_new_account"]
        ))

        # --- Worker signals ---
        signals.append(self._signal_low_reputation(
            "worker_low_reputation", worker_rep, RISK_WEIGHTS["worker_low_reputation"]
        ))
        signals.append(self._signal_high_dispute_rate(
            "worker_high_dispute_rate", worker_rep, RISK_WEIGHTS["worker_high_dispute_rate"]
        ))
        signals.append(self._signal_new_account(
            "worker_new_account", worker_rep, RISK_WEIGHTS["worker_new_account"]
        ))

        # --- Task signals ---
        signals.append(self._signal_high_escrow(
            contract.escrow_amount, RISK_WEIGHTS["unusually_high_escrow"]
        ))
        signals.append(self._signal_short_deadline(
            contract, RISK_WEIGHTS["very_short_deadline"]
        ))
        signals.append(self._signal_excessive_steps(
            contract, RISK_WEIGHTS["excessive_step_count"]
        ))

        # Composite score: sum of triggered weights, capped at 1.0
        total_weight = sum(s.weight for s in signals)
        triggered_weight = sum(s.contribution for s in signals)
        composite = min(1.0, triggered_weight / total_weight if total_weight > 0 else 0.0)

        should_hold  = composite >= RISK_THRESHOLDS["composite_risk_hold_at"]
        should_block = composite >= RISK_THRESHOLDS["composite_risk_block_at"]

        triggered_names = [s.name for s in signals if s.triggered]
        notes = f"Risk {composite:.0%}" + (f" — signals: {triggered_names}" if triggered_names else "")

        assessment = RiskAssessment(
            task_id=contract.task_id,
            composite_score=round(composite, 3),
            signals=signals,
            should_hold=should_hold,
            should_block=should_block,
            notes=notes,
        )

        if should_block:
            logger.warning("risk_block", task_id=contract.task_id, score=composite)
        elif should_hold:
            logger.info("risk_hold", task_id=contract.task_id, score=composite)

        return assessment

    # -------------------------------------------------------------------------
    # Signal detectors (PRIVATE)
    # -------------------------------------------------------------------------

    def _signal_low_reputation(
        self, name: str, rep: Optional[ReputationSnapshot], weight: float
    ) -> RiskSignal:
        if rep is None:
            return RiskSignal(name=name, triggered=True, weight=weight, detail="No reputation record")
        triggered = rep.score < RISK_THRESHOLDS["low_reputation_score"]
        return RiskSignal(
            name=name,
            triggered=triggered,
            weight=weight,
            detail=f"Score {rep.score:.0f} < {RISK_THRESHOLDS['low_reputation_score']}" if triggered else None,
        )

    def _signal_high_dispute_rate(
        self, name: str, rep: Optional[ReputationSnapshot], weight: float
    ) -> RiskSignal:
        if rep is None or rep.total_tasks < RISK_THRESHOLDS["new_account_task_minimum"]:
            return RiskSignal(name=name, triggered=False, weight=weight)
        dispute_rate = rep.disputed_tasks / rep.total_tasks
        triggered = dispute_rate > RISK_THRESHOLDS["high_dispute_rate"]
        return RiskSignal(
            name=name,
            triggered=triggered,
            weight=weight,
            detail=f"Dispute rate {dispute_rate:.0%} > threshold {RISK_THRESHOLDS['high_dispute_rate']:.0%}" if triggered else None,
        )

    def _signal_new_account(
        self, name: str, rep: Optional[ReputationSnapshot], weight: float
    ) -> RiskSignal:
        triggered = rep is None or rep.total_tasks < RISK_THRESHOLDS["new_account_task_minimum"]
        return RiskSignal(
            name=name,
            triggered=triggered,
            weight=weight,
            detail="Account has fewer than minimum tasks" if triggered else None,
        )

    def _signal_high_escrow(self, amount: float, weight: float) -> RiskSignal:
        multiple = amount / MEDIAN_ESCROW_AMOUNT
        triggered = multiple > RISK_THRESHOLDS["high_escrow_multiple"]
        return RiskSignal(
            name="unusually_high_escrow",
            triggered=triggered,
            weight=weight,
            detail=f"Escrow {multiple:.1f}x median" if triggered else None,
        )

    def _signal_short_deadline(self, contract: TaskContract, weight: float) -> RiskSignal:
        from datetime import datetime
        hours_remaining = (contract.deadline_at - datetime.utcnow()).total_seconds() / 3600
        triggered = hours_remaining < RISK_THRESHOLDS["short_deadline_hours"]
        return RiskSignal(
            name="very_short_deadline",
            triggered=triggered,
            weight=weight,
            detail=f"Only {hours_remaining:.1f}h remaining" if triggered else None,
        )

    def _signal_excessive_steps(self, contract: TaskContract, weight: float) -> RiskSignal:
        triggered = contract.expected_step_count > RISK_THRESHOLDS["excessive_steps"]
        return RiskSignal(
            name="excessive_step_count",
            triggered=triggered,
            weight=weight,
            detail=f"{contract.expected_step_count} steps > max {RISK_THRESHOLDS['excessive_steps']}" if triggered else None,
        )
