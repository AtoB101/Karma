"""
PRIVATE — Karma Behavior Analyzer
===================================
Analyzes agent execution behavior patterns to detect bots,
low-quality work, and anomalous sequences.

DO NOT commit to public repository.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional

from core.schemas import ExecutionReceipt, ToolStatus


# ---------------------------------------------------------------------------
# PRIVATE: Behavior scoring weights
# ---------------------------------------------------------------------------

BEHAVIOR_WEIGHTS = {
    "tool_sequence_entropy":     0.20,   # higher entropy = more natural
    "inter_step_pause_variance": 0.20,   # natural pauses vary
    "error_recovery_score":      0.15,   # handled errors gracefully?
    "tool_diversity":            0.15,   # used multiple tool types
    "output_length_variance":    0.15,   # outputs vary in length/complexity
    "execution_rhythm":          0.15,   # natural cadence vs robotic burst
}

BEHAVIOR_THRESHOLDS = {
    "min_behavior_score":         0.40,  # below this = bot signal
    "min_tool_entropy":           0.30,
    "min_pause_cv":               0.10,
    "min_tool_diversity_ratio":   0.20,
}


@dataclass
class BehaviorProfile:
    agent_id: str
    task_id: str
    behavior_score: float            # 0.0 = clearly bot, 1.0 = human-like
    is_suspicious: bool
    tool_sequence_entropy: float
    timing_variance_cv: float
    tool_diversity_ratio: float
    notes: list[str]


class BehaviorAnalyzer:
    """
    Scores agent behavior to detect scripted/bot execution.
    Human agents exhibit natural variance; bots are uniform.
    """

    def analyze(
        self,
        task_id: str,
        agent_id: str,
        receipts: list[ExecutionReceipt],
    ) -> BehaviorProfile:
        notes: list[str] = []
        scores: dict[str, float] = {}

        # 1. Tool sequence entropy
        entropy = self._tool_sequence_entropy(receipts)
        scores["tool_sequence_entropy"] = min(1.0, entropy / 2.0)
        if entropy < BEHAVIOR_THRESHOLDS["min_tool_entropy"]:
            notes.append(f"Low tool sequence entropy ({entropy:.3f}) — repetitive pattern")

        # 2. Inter-step pause variance
        pause_cv = self._inter_step_pause_cv(receipts)
        scores["inter_step_pause_variance"] = min(1.0, pause_cv / 0.5)
        if pause_cv < BEHAVIOR_THRESHOLDS["min_pause_cv"]:
            notes.append(f"Suspiciously uniform step timing (CV={pause_cv:.3f})")

        # 3. Error recovery score
        error_score = self._error_recovery_score(receipts)
        scores["error_recovery_score"] = error_score

        # 4. Tool diversity
        diversity = self._tool_diversity_ratio(receipts)
        scores["tool_diversity"] = diversity
        if diversity < BEHAVIOR_THRESHOLDS["min_tool_diversity_ratio"]:
            notes.append(f"Low tool diversity ({diversity:.0%}) — may be single-tool loop")

        # 5. Output length variance (proxy)
        output_variance = self._output_hash_diversity(receipts)
        scores["output_length_variance"] = output_variance

        # 6. Execution rhythm
        rhythm = self._execution_rhythm_score(receipts)
        scores["execution_rhythm"] = rhythm

        # Weighted composite
        composite = sum(
            scores[k] * BEHAVIOR_WEIGHTS[k] for k in BEHAVIOR_WEIGHTS
        )
        is_suspicious = composite < BEHAVIOR_THRESHOLDS["min_behavior_score"]

        return BehaviorProfile(
            agent_id=agent_id,
            task_id=task_id,
            behavior_score=round(composite, 3),
            is_suspicious=is_suspicious,
            tool_sequence_entropy=round(entropy, 3),
            timing_variance_cv=round(pause_cv, 3),
            tool_diversity_ratio=round(diversity, 3),
            notes=notes,
        )

    # -------------------------------------------------------------------------
    # Scoring methods (PRIVATE)
    # -------------------------------------------------------------------------

    def _tool_sequence_entropy(self, receipts: list[ExecutionReceipt]) -> float:
        """Shannon entropy of tool name sequence."""
        import math
        from collections import Counter
        if not receipts:
            return 0.0
        counts = Counter(r.tool_name for r in receipts)
        total = len(receipts)
        return -sum(
            (c / total) * math.log2(c / total)
            for c in counts.values()
        )

    def _inter_step_pause_cv(self, receipts: list[ExecutionReceipt]) -> float:
        """Coefficient of variation of pauses between steps."""
        if len(receipts) < 3:
            return 1.0
        pauses = []
        for i in range(1, len(receipts)):
            delta_ms = (
                receipts[i].started_at - receipts[i - 1].ended_at
            ).total_seconds() * 1000
            pauses.append(max(0.0, delta_ms))
        if not pauses:
            return 0.0
        mean = statistics.mean(pauses)
        if mean == 0:
            return 0.0
        return statistics.stdev(pauses) / mean if len(pauses) > 1 else 0.0

    def _error_recovery_score(self, receipts: list[ExecutionReceipt]) -> float:
        """
        Score based on how agent handled errors.
        Graceful recovery (failure followed by retry+success) scores well.
        All success with no errors is neutral.
        Cascading failures score poorly.
        """
        total = len(receipts)
        if total == 0:
            return 0.5
        failures = [r for r in receipts if r.status == ToolStatus.FAILURE]
        if not failures:
            return 0.8   # no errors — neutral-good

        # Check if failures were followed by successes (recovery)
        recoveries = 0
        for i, r in enumerate(receipts[:-1]):
            if r.status == ToolStatus.FAILURE:
                next_step = receipts[i + 1]
                if next_step.status == ToolStatus.SUCCESS:
                    recoveries += 1

        recovery_rate = recoveries / len(failures) if failures else 1.0
        return round(0.3 + 0.5 * recovery_rate, 3)

    def _tool_diversity_ratio(self, receipts: list[ExecutionReceipt]) -> float:
        """Unique tool types / total steps."""
        if not receipts:
            return 0.0
        unique_tools = len(set(r.tool_name for r in receipts))
        return unique_tools / len(receipts)

    def _output_hash_diversity(self, receipts: list[ExecutionReceipt]) -> float:
        """Unique output hashes / total steps — high = diverse outputs."""
        success = [r for r in receipts if r.status == ToolStatus.SUCCESS]
        if not success:
            return 0.5
        unique = len(set(r.output_hash for r in success))
        return unique / len(success)

    def _execution_rhythm_score(self, receipts: list[ExecutionReceipt]) -> float:
        """
        Score based on execution cadence.
        Natural agents: variable burst + pause patterns.
        Bots: steady metronomic execution.
        """
        durations = [r.duration_ms for r in receipts if r.status == ToolStatus.SUCCESS]
        if len(durations) < 3:
            return 0.5
        mean = statistics.mean(durations)
        if mean == 0:
            return 0.0
        cv = statistics.stdev(durations) / mean
        # Natural variance CV is typically 0.2–0.8
        # Very low CV (< 0.05) = robotic; very high (> 2.0) = erratic
        if cv < 0.05:
            return 0.1
        elif cv > 2.0:
            return 0.4
        else:
            return min(1.0, cv / 0.5)
