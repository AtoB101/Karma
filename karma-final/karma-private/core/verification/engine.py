"""
PRIVATE — Karma Runtime Verification Engine
============================================
Full implementation. Contains:
- Check weights and thresholds
- Fraud detection rules
- Human-like execution scoring
- Anti-cheat logic
- AI-generated spam detection
- Decision matrix

DO NOT commit to public repository.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

from core.schemas import (
    EvidenceBundle,
    ExecutionReceipt,
    TaskContract,
    ToolStatus,
    VerificationCheck,
    VerificationDecision,
    VerificationResult,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Check weights (PRIVATE)
# ---------------------------------------------------------------------------

CHECK_WEIGHTS: dict[str, float] = {
    # Critical — failure triggers immediate REFUND
    "receipt_completeness":         1.0,
    "hash_integrity":               1.0,
    "task_id_consistency":          1.0,
    "chronological_order":          1.0,
    "contract_hash_match":          1.0,
    "agent_signature_valid":        1.0,

    # High — failure triggers DISPUTE
    "success_rate":                 0.9,
    "duplicate_step_detection":     0.9,
    "missing_step_detection":       0.85,
    "anti_cheat_execution_time":    0.9,
    "human_timing_variance":        0.8,

    # Medium — failure triggers HOLD
    "output_count_validation":      0.7,
    "empty_output_detection":       0.7,
    "output_diversity":             0.65,
    "ai_spam_detection":            0.7,

    # Low — advisory only
    "wash_trade_detection":         0.5,
    "self_dealing_detection":       0.5,
    "behavior_consistency":         0.4,
}

# Thresholds (PRIVATE)
THRESHOLDS = {
    "min_success_rate":             0.80,
    "min_step_completion_ratio":    0.75,
    "suspicious_speed_ms":          50,       # < 50ms per step = suspicious
    "max_identical_outputs":        0.30,     # > 30% identical = spam
    "timing_variance_min_cv":       0.05,     # too uniform = bot
    "min_unique_output_ratio":      0.70,
    "wash_trade_same_agent_ratio":  1.0,      # same client+worker = wash
}

# Decision thresholds (PRIVATE)
DECISION_THRESHOLDS = {
    "refund_critical_failures":     1,        # any critical failure → refund
    "dispute_weighted_score_below": 0.65,
    "hold_weighted_score_below":    0.80,
    "release_minimum_score":        0.80,
}


# ---------------------------------------------------------------------------
# Check result with weight
# ---------------------------------------------------------------------------

@dataclass
class WeightedCheck:
    name: str
    passed: bool
    weight: float
    detail: str | None = None
    is_critical: bool = False

    def to_public(self) -> VerificationCheck:
        return VerificationCheck(name=self.name, passed=self.passed, detail=self.detail)


# ---------------------------------------------------------------------------
# Private Verification Engine
# ---------------------------------------------------------------------------

class PrivateVerificationEngine:
    """
    Full verification engine. Contains all private scoring logic.
    Called by the FastAPI verification endpoint — never exposed via SDK.
    """

    CRITICAL = {
        "receipt_completeness",
        "hash_integrity",
        "task_id_consistency",
        "chronological_order",
        "contract_hash_match",
        "agent_signature_valid",
    }

    def __init__(self, signing_service, receipt_store):
        self.signer = signing_service
        self.receipt_store = receipt_store

    async def verify(
        self,
        bundle: EvidenceBundle,
        contract: TaskContract,
    ) -> VerificationResult:
        log = logger.bind(task_id=bundle.task_id, bundle_id=bundle.bundle_id)
        log.info("private_verification_start")

        receipts = await self.receipt_store.list_by_task(bundle.task_id)
        receipts.sort(key=lambda r: r.step_index)

        checks: list[WeightedCheck] = [
            # --- Critical ---
            self._check_receipt_completeness(bundle, receipts, contract),
            self._check_hash_integrity(bundle, receipts),
            self._check_task_id_consistency(bundle, receipts),
            self._check_chronological_order(receipts),
            self._check_contract_hash(bundle, contract),
            self._check_agent_signature(bundle),

            # --- High ---
            self._check_success_rate(bundle),
            self._check_duplicate_steps(receipts),
            self._check_missing_steps(receipts),
            self._check_anti_cheat_execution_time(receipts),
            self._check_human_timing_variance(receipts),

            # --- Medium ---
            self._check_output_count(bundle, contract),
            self._check_empty_outputs(receipts),
            self._check_output_diversity(receipts),
            self._check_ai_spam(receipts),

            # --- Low ---
            self._check_wash_trade(bundle, contract),
            self._check_self_dealing(bundle, contract),
            self._check_behavior_consistency(receipts),
        ]

        # Tag critical checks
        for c in checks:
            c.is_critical = c.name in self.CRITICAL

        critical_failures = [c for c in checks if c.is_critical and not c.passed]

        # Weighted score across non-critical checks
        non_critical = [c for c in checks if not c.is_critical]
        if non_critical:
            total_weight = sum(c.weight for c in non_critical)
            weighted_score = sum(
                c.weight for c in non_critical if c.passed
            ) / total_weight
        else:
            weighted_score = 1.0

        # --- Decision matrix (PRIVATE) ---
        if len(critical_failures) >= DECISION_THRESHOLDS["refund_critical_failures"]:
            decision = VerificationDecision.REFUND
            confidence = 0.95
            notes = f"Critical failures: {[c.name for c in critical_failures]}"

        elif weighted_score < DECISION_THRESHOLDS["dispute_weighted_score_below"]:
            decision = VerificationDecision.DISPUTE
            confidence = round(1.0 - weighted_score, 3)
            notes = f"Weighted score {weighted_score:.2%} below dispute threshold"

        elif weighted_score < DECISION_THRESHOLDS["hold_weighted_score_below"]:
            decision = VerificationDecision.HOLD
            confidence = round(weighted_score, 3)
            notes = f"Weighted score {weighted_score:.2%} — flagged for review"

        else:
            decision = VerificationDecision.RELEASE
            confidence = round(weighted_score, 3)
            notes = "All checks passed."

        result = VerificationResult(
            task_id=bundle.task_id,
            bundle_id=bundle.bundle_id,
            decision=decision,
            confidence=confidence,
            checks=[c.to_public() for c in checks],
            notes=notes,
        )

        log.info(
            "private_verification_complete",
            decision=decision,
            weighted_score=f"{weighted_score:.2%}",
            critical_failures=len(critical_failures),
        )
        return result

    # =========================================================================
    # CRITICAL CHECKS
    # =========================================================================

    def _check_receipt_completeness(
        self, bundle: EvidenceBundle, receipts: list[ExecutionReceipt], contract: TaskContract
    ) -> WeightedCheck:
        name = "receipt_completeness"
        expected = contract.expected_step_count
        actual = len(receipts)
        lower = max(1, int(expected * THRESHOLDS["min_step_completion_ratio"]))
        passed = actual >= lower
        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail=f"Expected ≥{lower} steps, got {actual}" if not passed else None,
        )

    def _check_hash_integrity(
        self, bundle: EvidenceBundle, receipts: list[ExecutionReceipt]
    ) -> WeightedCheck:
        name = "hash_integrity"
        mismatches = []
        for i, (receipt, stored_hash) in enumerate(zip(receipts, bundle.receipt_hashes)):
            computed = self._hash_receipt(receipt)
            if computed != stored_hash:
                mismatches.append(i + 1)
        return WeightedCheck(
            name=name,
            passed=len(mismatches) == 0,
            weight=CHECK_WEIGHTS[name],
            detail=f"Hash mismatch at steps {mismatches}" if mismatches else None,
        )

    def _check_task_id_consistency(
        self, bundle: EvidenceBundle, receipts: list[ExecutionReceipt]
    ) -> WeightedCheck:
        name = "task_id_consistency"
        bad = [r.receipt_id for r in receipts if r.task_id != bundle.task_id]
        return WeightedCheck(
            name=name,
            passed=len(bad) == 0,
            weight=CHECK_WEIGHTS[name],
            detail=f"{len(bad)} receipts with mismatched task_id" if bad else None,
        )

    def _check_chronological_order(
        self, receipts: list[ExecutionReceipt]
    ) -> WeightedCheck:
        name = "chronological_order"
        overlaps = []
        for i in range(1, len(receipts)):
            if receipts[i].started_at < receipts[i - 1].ended_at:
                overlaps.append(receipts[i].step_index)
        return WeightedCheck(
            name=name,
            passed=len(overlaps) == 0,
            weight=CHECK_WEIGHTS[name],
            detail=f"Temporal overlaps at steps {overlaps}" if overlaps else None,
        )

    def _check_contract_hash(
        self, bundle: EvidenceBundle, contract: TaskContract
    ) -> WeightedCheck:
        name = "contract_hash_match"
        expected = contract.contract_hash or self._hash_dict(contract.model_dump())
        passed = bundle.task_contract_hash == expected
        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail="Contract hash mismatch — possible tampering" if not passed else None,
        )

    def _check_agent_signature(self, bundle: EvidenceBundle) -> WeightedCheck:
        name = "agent_signature_valid"
        if not bundle.agent_signature:
            return WeightedCheck(name=name, passed=False, weight=CHECK_WEIGHTS[name],
                                 detail="No agent signature present")
        payload = {
            "task_id": bundle.task_id,
            "contract_hash": bundle.task_contract_hash,
            "receipt_hashes": bundle.receipt_hashes,
            "final_result_hash": bundle.final_result_hash,
            "total_steps": bundle.total_steps,
            "successful_steps": bundle.successful_steps,
            "created_at": bundle.created_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        valid = self.signer.verify(canonical, bundle.agent_signature)
        return WeightedCheck(
            name=name,
            passed=valid,
            weight=CHECK_WEIGHTS[name],
            detail="Invalid Ed25519 signature" if not valid else None,
        )

    # =========================================================================
    # HIGH SEVERITY CHECKS
    # =========================================================================

    def _check_success_rate(self, bundle: EvidenceBundle) -> WeightedCheck:
        name = "success_rate"
        if bundle.total_steps == 0:
            return WeightedCheck(name=name, passed=False, weight=CHECK_WEIGHTS[name], detail="Zero steps")
        rate = bundle.successful_steps / bundle.total_steps
        passed = rate >= THRESHOLDS["min_success_rate"]
        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail=f"Success rate {rate:.1%} < threshold {THRESHOLDS['min_success_rate']:.1%}" if not passed else None,
        )

    def _check_duplicate_steps(self, receipts: list[ExecutionReceipt]) -> WeightedCheck:
        name = "duplicate_step_detection"
        indices = [r.step_index for r in receipts]
        dupes = [i for i in set(indices) if indices.count(i) > 1]
        return WeightedCheck(
            name=name,
            passed=len(dupes) == 0,
            weight=CHECK_WEIGHTS[name],
            detail=f"Duplicate step indices detected: {dupes}" if dupes else None,
        )

    def _check_missing_steps(self, receipts: list[ExecutionReceipt]) -> WeightedCheck:
        name = "missing_step_detection"
        if not receipts:
            return WeightedCheck(name=name, passed=False, weight=CHECK_WEIGHTS[name], detail="No receipts")
        indices = sorted(r.step_index for r in receipts)
        expected = list(range(1, indices[-1] + 1))
        missing = [i for i in expected if i not in indices]
        return WeightedCheck(
            name=name,
            passed=len(missing) == 0,
            weight=CHECK_WEIGHTS[name],
            detail=f"Missing step indices: {missing}" if missing else None,
        )

    def _check_anti_cheat_execution_time(
        self, receipts: list[ExecutionReceipt]
    ) -> WeightedCheck:
        """
        ANTI-CHEAT: Detect fake/pre-computed executions.
        Real tool calls take measurable time. Sub-threshold executions
        indicate pre-computed or fabricated receipts.
        """
        name = "anti_cheat_execution_time"
        threshold_ms = THRESHOLDS["suspicious_speed_ms"]
        suspicious = [
            r.receipt_id for r in receipts
            if r.status == ToolStatus.SUCCESS and r.duration_ms < threshold_ms
        ]
        passed = len(suspicious) == 0
        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail=f"{len(suspicious)} steps completed suspiciously fast (<{threshold_ms}ms)" if not passed else None,
        )

    def _check_human_timing_variance(
        self, receipts: list[ExecutionReceipt]
    ) -> WeightedCheck:
        """
        ANTI-CHEAT: Detect robotic/scripted execution patterns.
        Real agent work shows natural variance in step durations.
        Perfectly uniform timing is a bot signal.
        """
        name = "human_timing_variance"
        durations = [r.duration_ms for r in receipts if r.status == ToolStatus.SUCCESS]
        if len(durations) < 3:
            return WeightedCheck(name=name, passed=True, weight=CHECK_WEIGHTS[name],
                                 detail="Insufficient samples")
        mean = statistics.mean(durations)
        stdev = statistics.stdev(durations)
        cv = stdev / mean if mean > 0 else 0
        min_cv = THRESHOLDS["timing_variance_min_cv"]
        passed = cv >= min_cv
        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail=f"Timing CV={cv:.3f} below minimum {min_cv} — suspiciously uniform" if not passed else None,
        )

    # =========================================================================
    # MEDIUM SEVERITY CHECKS
    # =========================================================================

    def _check_output_count(
        self, bundle: EvidenceBundle, contract: TaskContract
    ) -> WeightedCheck:
        name = "output_count_validation"
        passed = bundle.successful_steps > 0
        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail="Zero successful outputs" if not passed else None,
        )

    def _check_empty_outputs(self, receipts: list[ExecutionReceipt]) -> WeightedCheck:
        name = "empty_output_detection"
        empty_hash = hashlib.sha256(b"").hexdigest()
        empty = [
            r.receipt_id for r in receipts
            if r.output_hash == empty_hash and r.status == ToolStatus.SUCCESS
        ]
        return WeightedCheck(
            name=name,
            passed=len(empty) == 0,
            weight=CHECK_WEIGHTS[name],
            detail=f"{len(empty)} successful steps with empty output" if empty else None,
        )

    def _check_output_diversity(self, receipts: list[ExecutionReceipt]) -> WeightedCheck:
        """
        SPAM DETECTION: Detect copy-paste / repeated outputs.
        Low diversity = agent submitted same output repeatedly.
        """
        name = "output_diversity"
        hashes = [r.output_hash for r in receipts if r.status == ToolStatus.SUCCESS]
        if len(hashes) < 2:
            return WeightedCheck(name=name, passed=True, weight=CHECK_WEIGHTS[name])
        unique_ratio = len(set(hashes)) / len(hashes)
        min_ratio = THRESHOLDS["min_unique_output_ratio"]
        passed = unique_ratio >= min_ratio
        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail=f"Output uniqueness {unique_ratio:.1%} < threshold {min_ratio:.1%} — possible spam" if not passed else None,
        )

    def _check_ai_spam(self, receipts: list[ExecutionReceipt]) -> WeightedCheck:
        """
        AI SPAM DETECTION: Detect low-effort AI-generated bulk output.
        Checks for suspiciously identical output hashes across tool calls
        of the same type (indicating copy-pasted AI completions).
        """
        name = "ai_spam_detection"
        by_tool: dict[str, list[str]] = {}
        for r in receipts:
            if r.status == ToolStatus.SUCCESS:
                by_tool.setdefault(r.tool_name, []).append(r.output_hash)

        spam_tools = []
        for tool, hashes in by_tool.items():
            if len(hashes) < 2:
                continue
            duplicate_ratio = 1 - (len(set(hashes)) / len(hashes))
            if duplicate_ratio > THRESHOLDS["max_identical_outputs"]:
                spam_tools.append(f"{tool}({duplicate_ratio:.0%} duplicate)")

        return WeightedCheck(
            name=name,
            passed=len(spam_tools) == 0,
            weight=CHECK_WEIGHTS[name],
            detail=f"AI spam detected in tools: {spam_tools}" if spam_tools else None,
        )

    # =========================================================================
    # LOW SEVERITY / FRAUD SIGNALS
    # =========================================================================

    def _check_wash_trade(
        self, bundle: EvidenceBundle, contract: TaskContract
    ) -> WeightedCheck:
        """
        WASH TRADE DETECTION: Same entity as both client and worker.
        """
        name = "wash_trade_detection"
        same_agent = (
            contract.client_agent_id == bundle.task_id or   # placeholder pattern
            contract.client_agent_id == contract.worker_agent_id
        )
        return WeightedCheck(
            name=name,
            passed=not same_agent,
            weight=CHECK_WEIGHTS[name],
            detail="Client and worker agent IDs are identical — wash trade signal" if same_agent else None,
        )

    def _check_self_dealing(
        self, bundle: EvidenceBundle, contract: TaskContract
    ) -> WeightedCheck:
        """
        SELF-DEALING DETECTION: Worker agent controlling both sides of settlement.
        Extend with behavior graph analysis in production.
        """
        name = "self_dealing_detection"
        # Base check: worker_agent_id must differ from client
        passed = (
            contract.worker_agent_id is None or
            contract.worker_agent_id != contract.client_agent_id
        )
        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail="Self-dealing pattern detected" if not passed else None,
        )

    def _check_behavior_consistency(
        self, receipts: list[ExecutionReceipt]
    ) -> WeightedCheck:
        """
        BEHAVIOR ANALYSIS: Check for inconsistent tool sequences.
        In production, this feeds into the behavior graph model.
        Here we check that tool names don't repeat in unexpected patterns.
        """
        name = "behavior_consistency"
        if len(receipts) < 2:
            return WeightedCheck(name=name, passed=True, weight=CHECK_WEIGHTS[name])

        tool_sequence = [r.tool_name for r in receipts]
        consecutive_repeats = sum(
            1 for i in range(1, len(tool_sequence))
            if tool_sequence[i] == tool_sequence[i - 1]
        )
        repeat_ratio = consecutive_repeats / len(tool_sequence)
        passed = repeat_ratio < 0.5

        return WeightedCheck(
            name=name,
            passed=passed,
            weight=CHECK_WEIGHTS[name],
            detail=f"Suspicious tool repetition pattern ({repeat_ratio:.0%} consecutive repeats)" if not passed else None,
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _hash_receipt(receipt: ExecutionReceipt) -> str:
        raw = json.dumps(receipt.model_dump(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _hash_dict(d: dict[str, Any]) -> str:
        raw = json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
