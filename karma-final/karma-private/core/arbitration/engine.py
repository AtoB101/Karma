"""
PRIVATE — Karma Arbitration Engine
=====================================
Evaluates disputed tasks and determines outcomes.
Combines verification confidence, fraud signals, and behavior
scores to produce a final binding decision.

DO NOT commit to public repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

from core.schemas import (
    EvidenceBundle,
    ReputationSnapshot,
    SettlementState,
    TaskContract,
    TaskStatus,
    VerificationResult,
)
from core.fraud.detector import FraudReport
from core.behavior.analyzer import BehaviorProfile

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# PRIVATE: Arbitration decision weights
# ---------------------------------------------------------------------------

ARBITRATION_WEIGHTS = {
    "verification_confidence": 0.35,
    "fraud_report_clean":      0.30,
    "behavior_score":          0.15,
    "worker_reputation":       0.10,
    "buyer_reputation":        0.10,
}

ARBITRATION_THRESHOLDS = {
    "seller_wins_score":  0.72,   # weighted score above this → seller wins
    "buyer_wins_score":   0.35,   # weighted score below this → buyer wins
    # between these two → partial
}

# Partial split rules (PRIVATE)
PARTIAL_WORKER_FRACTION = {
    "score_0.35_to_0.50": 0.25,   # worker gets 25%
    "score_0.50_to_0.60": 0.40,
    "score_0.60_to_0.72": 0.60,
}


@dataclass
class ArbitrationDecision:
    task_id: str
    outcome: TaskStatus              # BUYER_WINS | SELLER_WINS | PARTIAL
    released_amount: Optional[float]
    refunded_amount: Optional[float]
    composite_score: float
    reasoning: str
    signal_breakdown: dict


class ArbitrationEngine:
    """
    Makes binding arbitration decisions for disputed tasks.
    Uses a weighted composite of all available evidence signals.
    """

    def adjudicate(
        self,
        bundle: EvidenceBundle,
        contract: TaskContract,
        settlement: SettlementState,
        verification: VerificationResult,
        fraud_report: FraudReport,
        behavior: BehaviorProfile,
        worker_rep: Optional[ReputationSnapshot] = None,
        buyer_rep: Optional[ReputationSnapshot] = None,
    ) -> ArbitrationDecision:

        # --- Build signal scores (0.0–1.0) ---
        v_score = verification.confidence
        f_score = 1.0 if not fraud_report.is_fraudulent else (1.0 - fraud_report.confidence)
        b_score = behavior.behavior_score
        w_score = self._normalize_reputation(worker_rep)
        c_score = self._normalize_reputation(buyer_rep)

        breakdown = {
            "verification_confidence": round(v_score, 3),
            "fraud_clean_score":       round(f_score, 3),
            "behavior_score":          round(b_score, 3),
            "worker_reputation":       round(w_score, 3),
            "buyer_reputation":        round(c_score, 3),
        }

        composite = (
            v_score * ARBITRATION_WEIGHTS["verification_confidence"] +
            f_score * ARBITRATION_WEIGHTS["fraud_report_clean"] +
            b_score * ARBITRATION_WEIGHTS["behavior_score"] +
            w_score * ARBITRATION_WEIGHTS["worker_reputation"] +
            c_score * ARBITRATION_WEIGHTS["buyer_reputation"]
        )
        composite = round(composite, 3)

        escrow = settlement.escrow_amount

        # --- Decision matrix (PRIVATE) ---
        if fraud_report.is_fraudulent and fraud_report.confidence > 0.90:
            # Hard block: clear fraud → full refund
            outcome = TaskStatus.BUYER_WINS
            released, refunded = None, escrow
            reasoning = f"Fraud detected with {fraud_report.confidence:.0%} confidence: {fraud_report.signals[0].signal_type if fraud_report.signals else 'unknown'}"

        elif composite >= ARBITRATION_THRESHOLDS["seller_wins_score"]:
            outcome = TaskStatus.SELLER_WINS
            released, refunded = escrow, None
            reasoning = f"Strong evidence of legitimate execution (composite={composite:.2f})"

        elif composite < ARBITRATION_THRESHOLDS["buyer_wins_score"]:
            outcome = TaskStatus.BUYER_WINS
            released, refunded = None, escrow
            reasoning = f"Insufficient evidence of quality execution (composite={composite:.2f})"

        else:
            # Partial: interpolate worker fraction
            worker_fraction = self._partial_fraction(composite)
            released = round(escrow * worker_fraction, 2)
            refunded = round(escrow - released, 2)
            outcome = TaskStatus.PARTIAL
            reasoning = (
                f"Mixed evidence (composite={composite:.2f}) — "
                f"worker {worker_fraction:.0%}, client {1-worker_fraction:.0%}"
            )

        logger.info(
            "arbitration_decision",
            task_id=bundle.task_id,
            outcome=outcome,
            composite=composite,
        )

        return ArbitrationDecision(
            task_id=bundle.task_id,
            outcome=outcome,
            released_amount=released,
            refunded_amount=refunded,
            composite_score=composite,
            reasoning=reasoning,
            signal_breakdown=breakdown,
        )

    # -------------------------------------------------------------------------
    # Helpers (PRIVATE)
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_reputation(rep: Optional[ReputationSnapshot]) -> float:
        """Normalize reputation score to 0.0–1.0."""
        if rep is None:
            return 0.5   # unknown — neutral
        return min(1.0, rep.score / 1000.0)

    @staticmethod
    def _partial_fraction(composite: float) -> float:
        """PRIVATE: Determine worker payout fraction for partial outcomes."""
        if composite < 0.50:
            return PARTIAL_WORKER_FRACTION["score_0.35_to_0.50"]
        elif composite < 0.60:
            return PARTIAL_WORKER_FRACTION["score_0.50_to_0.60"]
        else:
            return PARTIAL_WORKER_FRACTION["score_0.60_to_0.72"]
