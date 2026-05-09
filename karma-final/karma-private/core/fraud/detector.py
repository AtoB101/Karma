"""
PRIVATE — Karma Fraud Detector
================================
Detects wash trading, self-dealing, and fabricated execution patterns.

DO NOT commit to public repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

from core.schemas import EvidenceBundle, ExecutionReceipt, TaskContract

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# PRIVATE: Fraud signal thresholds
# ---------------------------------------------------------------------------

FRAUD_THRESHOLDS = {
    # Timing-based fabrication detection
    "min_realistic_tool_ms":         10,       # tools taking < 10ms are likely fake
    "max_uniform_timing_cv":         0.03,     # coefficient of variation — too uniform = scripted
    "suspiciously_round_duration":   True,     # e.g. exactly 100ms, 200ms, 500ms = suspicious

    # Output fabrication
    "max_hash_collision_rate":       0.0,      # any two identical output hashes = flagged
    "min_entropy_per_output":        2.0,      # Shannon entropy below this = templated output

    # Self-dealing
    "self_dealing_agent_match":      True,     # client_id == worker_id

    # Wash trading
    "wash_trade_history_window":     10,       # look back N tasks
    "wash_trade_repeat_pair_limit":  3,        # same pair more than 3x = wash trade signal
}


@dataclass
class FraudSignal:
    signal_type: str
    severity: str          # "critical" | "high" | "medium"
    detail: str
    evidence: dict


@dataclass
class FraudReport:
    task_id: str
    is_fraudulent: bool
    signals: list[FraudSignal]
    confidence: float
    recommended_action: str   # "block" | "hold" | "flag" | "pass"


class FraudDetector:
    """
    Runs fraud detection checks against an evidence bundle.
    Called before settlement decisions are made.
    """

    def detect(
        self,
        bundle: EvidenceBundle,
        contract: TaskContract,
        receipts: list[ExecutionReceipt],
        task_history: Optional[list[dict]] = None,
    ) -> FraudReport:
        signals: list[FraudSignal] = []

        signals.extend(self._detect_fabricated_timing(receipts))
        signals.extend(self._detect_output_fabrication(receipts))
        signals.extend(self._detect_self_dealing(contract))
        signals.extend(self._detect_wash_trading(contract, task_history or []))
        signals.extend(self._detect_replay_attack(bundle, receipts))

        critical = [s for s in signals if s.severity == "critical"]
        high     = [s for s in signals if s.severity == "high"]

        if critical:
            confidence = 0.95
            action = "block"
            is_fraud = True
        elif len(high) >= 2:
            confidence = 0.80
            action = "hold"
            is_fraud = True
        elif high:
            confidence = 0.60
            action = "flag"
            is_fraud = False
        else:
            confidence = 1.0 - (len(signals) * 0.05)
            action = "pass"
            is_fraud = False

        report = FraudReport(
            task_id=bundle.task_id,
            is_fraudulent=is_fraud,
            signals=signals,
            confidence=round(max(0.0, confidence), 3),
            recommended_action=action,
        )

        if is_fraud:
            logger.warning(
                "fraud_detected",
                task_id=bundle.task_id,
                action=action,
                signal_count=len(signals),
            )
        return report

    # -------------------------------------------------------------------------
    # Fabricated timing detection (PRIVATE)
    # -------------------------------------------------------------------------

    def _detect_fabricated_timing(
        self, receipts: list[ExecutionReceipt]
    ) -> list[FraudSignal]:
        signals = []
        min_ms = FRAUD_THRESHOLDS["min_realistic_tool_ms"]

        instant = [r for r in receipts if r.duration_ms < min_ms]
        if instant:
            signals.append(FraudSignal(
                signal_type="instant_execution",
                severity="critical",
                detail=f"{len(instant)} steps completed in < {min_ms}ms — likely fabricated",
                evidence={"receipt_ids": [r.receipt_id for r in instant]},
            ))

        if FRAUD_THRESHOLDS["suspiciously_round_duration"]:
            round_numbers = {100, 200, 500, 1000, 2000, 5000}
            suspiciously_round = [
                r for r in receipts if r.duration_ms in round_numbers
            ]
            if len(suspiciously_round) > len(receipts) * 0.5:
                signals.append(FraudSignal(
                    signal_type="round_duration_pattern",
                    severity="medium",
                    detail="Majority of steps have suspiciously round durations",
                    evidence={"durations": [r.duration_ms for r in suspiciously_round]},
                ))

        return signals

    # -------------------------------------------------------------------------
    # Output fabrication detection (PRIVATE)
    # -------------------------------------------------------------------------

    def _detect_output_fabrication(
        self, receipts: list[ExecutionReceipt]
    ) -> list[FraudSignal]:
        signals = []
        from core.schemas import ToolStatus

        success_hashes = [r.output_hash for r in receipts if r.status == ToolStatus.SUCCESS]
        if len(success_hashes) != len(set(success_hashes)):
            from collections import Counter
            counts = Counter(success_hashes)
            duplicates = {h: c for h, c in counts.items() if c > 1}
            signals.append(FraudSignal(
                signal_type="duplicate_output_hash",
                severity="high",
                detail=f"Identical output hashes across {sum(duplicates.values())} steps",
                evidence={"duplicate_hashes": list(duplicates.keys())},
            ))
        return signals

    # -------------------------------------------------------------------------
    # Self-dealing detection (PRIVATE)
    # -------------------------------------------------------------------------

    def _detect_self_dealing(self, contract: TaskContract) -> list[FraudSignal]:
        if (
            contract.worker_agent_id
            and contract.client_agent_id == contract.worker_agent_id
        ):
            return [FraudSignal(
                signal_type="self_dealing",
                severity="critical",
                detail="Client and worker agent are identical — self-dealing detected",
                evidence={
                    "client_agent_id": contract.client_agent_id,
                    "worker_agent_id": contract.worker_agent_id,
                },
            )]
        return []

    # -------------------------------------------------------------------------
    # Wash trading detection (PRIVATE)
    # -------------------------------------------------------------------------

    def _detect_wash_trading(
        self, contract: TaskContract, task_history: list[dict]
    ) -> list[FraudSignal]:
        if not task_history or not contract.worker_agent_id:
            return []

        window = FRAUD_THRESHOLDS["wash_trade_history_window"]
        limit  = FRAUD_THRESHOLDS["wash_trade_repeat_pair_limit"]
        recent = task_history[-window:]

        pair = (contract.client_agent_id, contract.worker_agent_id)
        pair_count = sum(
            1 for t in recent
            if t.get("client_agent_id") == pair[0]
            and t.get("worker_agent_id") == pair[1]
        )

        if pair_count >= limit:
            return [FraudSignal(
                signal_type="wash_trading",
                severity="high",
                detail=f"Client-worker pair appeared {pair_count}x in last {window} tasks",
                evidence={"client": pair[0], "worker": pair[1], "count": pair_count},
            )]
        return []

    # -------------------------------------------------------------------------
    # Replay attack detection (PRIVATE)
    # -------------------------------------------------------------------------

    def _detect_replay_attack(
        self, bundle: EvidenceBundle, receipts: list[ExecutionReceipt]
    ) -> list[FraudSignal]:
        """Detect if receipt IDs or hashes are reused from another task."""
        # In production: cross-check against global receipt hash index in Redis
        # Here: check for internal receipt_id collisions
        ids = [r.receipt_id for r in receipts]
        if len(ids) != len(set(ids)):
            return [FraudSignal(
                signal_type="receipt_id_collision",
                severity="critical",
                detail="Duplicate receipt IDs detected — possible replay attack",
                evidence={"receipt_ids": ids},
            )]
        return []
