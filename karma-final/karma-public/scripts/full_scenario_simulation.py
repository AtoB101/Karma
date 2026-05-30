#!/usr/bin/env python3
"""
Karma Trust Protocol — Full Scenario Simulation
================================================
Simulates realistic agent work patterns through the Karma Trusted Agent Runtime.

Scenarios:
  1. data_labeling     — AI data labeling (image/text annotation)
  2. ocr              — OCR correction (document digitization)
  3. api_call         — API call service (external data fetching)
  4. translation      — Translation task (multi-language)
  5. data_cleaning    — Data cleaning (dedup, normalization)
  6. a2a_microservice — Agent-to-agent microservice call

Each scenario flows through:
  task → agent execution → tool calls → execution receipts
  → receipt chain → evidence bundle → structural verification
  → settlement plan → trace_id → stress summary

Usage:
  python scripts/full_scenario_simulation.py \\
      --scenarios data_labeling,ocr,api_call,translation,data_cleaning,a2a_microservice \\
      --agents 100 --malicious-rate 0.5 --seed 42 \\
      --output-dir results/full-scenario-test

  python scripts/full_scenario_simulation.py --agents 500 --seed 42 \\
      --output-dir results/full-scenario-test-500
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_SCENARIOS = [
    "data_labeling",
    "ocr",
    "api_call",
    "translation",
    "data_cleaning",
    "a2a_microservice",
]

ATTACK_TYPES = [
    "duplicate_receipt",
    "replayed_receipt",
    "forged_hash",
    "timeout",
    "malformed_receipt",
    "partial_receipt_chain",
    "fake_execution",
    "repeated_output",
    "cross_task_receipt_reuse",
]

# Scenario-specific tool definitions
SCENARIO_TOOLS = {
    "data_labeling": [
        ("label.classify", 3),
        ("label.bbox", 2),
        ("label.validate", 1),
    ],
    "ocr": [
        ("ocr.extract", 2),
        ("ocr.correct", 2),
        ("ocr.format", 1),
    ],
    "api_call": [
        ("api.authenticate", 1),
        ("api.fetch", 2),
        ("api.parse", 1),
        ("api.validate", 1),
    ],
    "translation": [
        ("translate.detect_lang", 1),
        ("translate.translate", 2),
        ("translate.quality_check", 1),
    ],
    "data_cleaning": [
        ("clean.dedup", 2),
        ("clean.normalize", 2),
        ("clean.validate", 1),
    ],
    "a2a_microservice": [
        ("a2a.discover", 1),
        ("a2a.negotiate", 1),
        ("a2a.execute", 2),
        ("a2a.verify_response", 1),
    ],
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def sha256(data: Any) -> str:
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode()
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def make_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Data Models (simulation-local, using existing schema structure)
# ---------------------------------------------------------------------------

@dataclass
class SimAgent:
    agent_id: str
    name: str
    role: str  # "worker" or "client"
    is_malicious: bool
    attack_type: Optional[str] = None


@dataclass
class SimReceipt:
    receipt_id: str
    task_id: str
    agent_id: str
    step_index: int
    tool_name: str
    input_hash: str
    output_hash: str
    started_at: str
    ended_at: str
    duration_ms: int
    status: str  # "success" | "failure" | "timeout"
    error_message: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "receipt_id": self.receipt_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "step_index": self.step_index,
            "tool_name": self.tool_name,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "status": self.status,
        }
        if self.error_message:
            d["error_message"] = self.error_message
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class SimEvidenceBundle:
    bundle_id: str
    task_id: str
    task_contract_hash: str
    receipt_ids: list[str]
    receipt_hashes: list[str]
    final_result_hash: str
    total_steps: int
    successful_steps: int
    failed_steps: int
    total_duration_ms: int
    settlement_status: str = "submitted"

    def to_dict(self) -> dict:
        return {
            "bundle_id": self.bundle_id,
            "task_id": self.task_id,
            "task_contract_hash": self.task_contract_hash,
            "receipt_ids": self.receipt_ids,
            "receipt_hashes": self.receipt_hashes,
            "final_result_hash": self.final_result_hash,
            "total_steps": self.total_steps,
            "successful_steps": self.successful_steps,
            "failed_steps": self.failed_steps,
            "total_duration_ms": self.total_duration_ms,
            "settlement_status": self.settlement_status,
        }


@dataclass
class VerificationCheck:
    name: str
    passed: bool
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"name": self.name, "passed": self.passed}
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class VerificationResult:
    verification_id: str
    task_id: str
    bundle_id: str
    decision: str  # "release" | "hold" | "refund" | "dispute"
    confidence: float
    checks: list[VerificationCheck]
    detected_attacks: list[str] = field(default_factory=list)
    verification_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "verification_id": self.verification_id,
            "task_id": self.task_id,
            "bundle_id": self.bundle_id,
            "decision": self.decision,
            "confidence": self.confidence,
            "checks": [c.to_dict() for c in self.checks],
            "detected_attacks": self.detected_attacks,
            "verification_ms": round(self.verification_ms, 2),
        }


@dataclass
class SettlementPlan:
    task_id: str
    trace_id: str
    decision: str
    escrow_amount: float
    release_to_worker: float
    refund_to_client: float
    reason: str
    detected_attacks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "decision": self.decision,
            "escrow_amount": self.escrow_amount,
            "release_to_worker": self.release_to_worker,
            "refund_to_client": self.refund_to_client,
            "reason": self.reason,
            "detected_attacks": self.detected_attacks,
        }


# ---------------------------------------------------------------------------
# Honest Agent Execution
# ---------------------------------------------------------------------------

def execute_honest_task(
    rng: random.Random,
    agent: SimAgent,
    task_id: str,
    scenario: str,
    task_contract_hash: str,
) -> tuple[list[SimReceipt], SimEvidenceBundle]:
    """Execute a task honestly — proper receipts, valid hashes, complete chain."""
    tools = SCENARIO_TOOLS[scenario]
    receipts: list[SimReceipt] = []
    step = 0
    total_duration = 0
    base_time = now_utc()

    for tool_name, count in tools:
        for _ in range(count):
            step += 1
            duration = rng.randint(20, 800)
            total_duration += duration
            started = base_time + timedelta(milliseconds=total_duration - duration)
            ended = base_time + timedelta(milliseconds=total_duration)

            input_data = {"task_id": task_id, "step": step, "tool": tool_name, "nonce": rng.randint(0, 999999)}
            output_data = {"result": f"output_{step}_{rng.randint(0, 9999)}", "quality": rng.uniform(0.8, 1.0)}

            receipt = SimReceipt(
                receipt_id=make_uuid(rng),
                task_id=task_id,
                agent_id=agent.agent_id,
                step_index=step,
                tool_name=tool_name,
                input_hash=sha256(input_data),
                output_hash=sha256(output_data),
                started_at=started.isoformat(),
                ended_at=ended.isoformat(),
                duration_ms=duration,
                status="success",
                metadata={"scenario": scenario},
            )
            receipts.append(receipt)

    # Build evidence bundle
    receipt_hashes = [sha256(r.to_dict()) for r in receipts]
    final_result = {"task_id": task_id, "total_steps": step, "scenario": scenario}

    bundle = SimEvidenceBundle(
        bundle_id=make_uuid(rng),
        task_id=task_id,
        task_contract_hash=task_contract_hash,
        receipt_ids=[r.receipt_id for r in receipts],
        receipt_hashes=receipt_hashes,
        final_result_hash=sha256(final_result),
        total_steps=step,
        successful_steps=step,
        failed_steps=0,
        total_duration_ms=total_duration,
    )

    return receipts, bundle


# ---------------------------------------------------------------------------
# Malicious Agent Execution
# ---------------------------------------------------------------------------

def execute_malicious_task(
    rng: random.Random,
    agent: SimAgent,
    task_id: str,
    scenario: str,
    task_contract_hash: str,
    all_previous_receipts: list[SimReceipt],
) -> tuple[list[SimReceipt], SimEvidenceBundle, str]:
    """Execute a task maliciously — introduce specific attack patterns."""
    attack = agent.attack_type or rng.choice(ATTACK_TYPES)

    # Start with honest execution, then corrupt
    receipts, bundle = execute_honest_task(rng, agent, task_id, scenario, task_contract_hash)

    if attack == "duplicate_receipt":
        # Duplicate one receipt with same step_index
        if receipts:
            dup = SimReceipt(**{**receipts[0].__dict__})
            dup.receipt_id = make_uuid(rng)
            receipts.append(dup)

    elif attack == "replayed_receipt":
        # Copy a receipt from a different task execution
        if all_previous_receipts:
            stolen = rng.choice(all_previous_receipts)
            replay = SimReceipt(**{**stolen.__dict__})
            replay.receipt_id = make_uuid(rng)
            replay.task_id = task_id  # Change task_id to current
            if receipts:
                replay.step_index = receipts[-1].step_index + 1
            receipts.append(replay)

    elif attack == "forged_hash":
        # Forge: bundle declares original hashes but receipt was tampered
        # Compute bundle hashes FIRST (honest), then corrupt a receipt
        receipt_hashes_honest = [sha256(r.to_dict()) for r in receipts]
        if receipts:
            target = rng.choice(receipts)
            target.output_hash = sha256(f"forged_{rng.randint(0, 99999)}")
        # Bundle still has the old (honest) hashes — mismatch!
        bundle = SimEvidenceBundle(
            bundle_id=make_uuid(rng),
            task_id=task_id,
            task_contract_hash=task_contract_hash,
            receipt_ids=[r.receipt_id for r in receipts],
            receipt_hashes=receipt_hashes_honest,
            final_result_hash=bundle.final_result_hash,
            total_steps=len(receipts),
            successful_steps=sum(1 for r in receipts if r.status == "success"),
            failed_steps=sum(1 for r in receipts if r.status != "success"),
            total_duration_ms=sum(r.duration_ms for r in receipts),
        )
        return receipts, bundle, attack

    elif attack == "timeout":
        # Exceed timeout on one step
        if receipts:
            target = rng.choice(receipts)
            target.status = "timeout"
            target.duration_ms = 999999
            target.error_message = "Exceeded 60s timeout"

    elif attack == "malformed_receipt":
        # Leave critical fields empty/invalid
        if receipts:
            target = rng.choice(receipts)
            target.input_hash = ""
            target.output_hash = "not-a-valid-hash"

    elif attack == "partial_receipt_chain":
        # Remove receipts from the middle, breaking the chain
        if len(receipts) > 2:
            remove_idx = rng.randint(1, len(receipts) - 2)
            receipts.pop(remove_idx)

    elif attack == "fake_execution":
        # All receipts have 0ms duration (impossible for real execution)
        for r in receipts:
            r.duration_ms = 0
            r.started_at = r.ended_at

    elif attack == "repeated_output":
        # All receipts produce identical output hash (copy-paste attack)
        if receipts:
            single_hash = receipts[0].output_hash
            for r in receipts:
                r.output_hash = single_hash

    elif attack == "cross_task_receipt_reuse":
        # Use receipt_ids from another task
        if all_previous_receipts:
            for i, r in enumerate(receipts):
                if i < len(all_previous_receipts):
                    r.receipt_id = all_previous_receipts[i].receipt_id

    # Rebuild bundle with corrupted receipts
    receipt_hashes = [sha256(r.to_dict()) for r in receipts]
    bundle = SimEvidenceBundle(
        bundle_id=make_uuid(rng),
        task_id=task_id,
        task_contract_hash=task_contract_hash,
        receipt_ids=[r.receipt_id for r in receipts],
        receipt_hashes=receipt_hashes,
        final_result_hash=bundle.final_result_hash,
        total_steps=len(receipts),
        successful_steps=sum(1 for r in receipts if r.status == "success"),
        failed_steps=sum(1 for r in receipts if r.status != "success"),
        total_duration_ms=sum(r.duration_ms for r in receipts),
    )

    return receipts, bundle, attack


# ---------------------------------------------------------------------------
# Structural Verification Engine
# ---------------------------------------------------------------------------

def verify_bundle(
    receipts: list[SimReceipt],
    bundle: SimEvidenceBundle,
    task_id: str,
    expected_tools: list[tuple[str, int]],
    all_known_receipt_ids: set[str],
    rng: random.Random,
) -> VerificationResult:
    """
    Structural verification — no private risk logic exposed.
    Checks structural integrity of the receipt chain and evidence bundle.
    """
    t0 = time.perf_counter_ns()
    checks: list[VerificationCheck] = []
    detected_attacks: list[str] = []

    # Check 1: Receipt chain completeness
    expected_steps = sum(count for _, count in expected_tools)
    chain_complete = len(receipts) == expected_steps
    if not chain_complete:
        if len(receipts) < expected_steps:
            detected_attacks.append("partial_receipt_chain")
        else:
            detected_attacks.append("duplicate_receipt")
    checks.append(VerificationCheck(
        name="receipt_chain_completeness",
        passed=chain_complete,
        detail=f"expected={expected_steps}, actual={len(receipts)}",
    ))

    # Check 2: Step index continuity (no gaps, no duplicates)
    step_indices = [r.step_index for r in receipts]
    expected_indices = list(range(1, len(receipts) + 1))
    indices_valid = sorted(step_indices) == expected_indices
    if not indices_valid:
        if len(set(step_indices)) < len(step_indices):
            detected_attacks.append("duplicate_receipt")
        else:
            detected_attacks.append("partial_receipt_chain")
    checks.append(VerificationCheck(
        name="step_index_continuity",
        passed=indices_valid,
        detail=f"indices={sorted(step_indices)}",
    ))

    # Check 3: All receipts belong to same task
    all_same_task = all(r.task_id == task_id for r in receipts)
    if not all_same_task:
        detected_attacks.append("cross_task_receipt_reuse")
    checks.append(VerificationCheck(
        name="task_id_consistency",
        passed=all_same_task,
    ))

    # Check 4: Hash format validity (64-char hex)
    hashes_valid = all(
        len(r.input_hash) == 64 and len(r.output_hash) == 64
        and all(c in "0123456789abcdef" for c in r.input_hash)
        and all(c in "0123456789abcdef" for c in r.output_hash)
        for r in receipts
    )
    if not hashes_valid:
        detected_attacks.append("malformed_receipt")
    checks.append(VerificationCheck(
        name="hash_format_validity",
        passed=hashes_valid,
    ))

    # Check 5: Receipt hash matches bundle declaration
    computed_hashes = [sha256(r.to_dict()) for r in receipts]
    hashes_match = computed_hashes == bundle.receipt_hashes
    if not hashes_match:
        detected_attacks.append("forged_hash")
    checks.append(VerificationCheck(
        name="receipt_hash_integrity",
        passed=hashes_match,
    ))

    # Check 6: No zero-duration executions (fake execution detection)
    all_have_duration = all(r.duration_ms > 0 for r in receipts)
    if not all_have_duration:
        detected_attacks.append("fake_execution")
    checks.append(VerificationCheck(
        name="execution_duration_positive",
        passed=all_have_duration,
    ))

    # Check 7: Output diversity (repeated output detection)
    output_hashes = [r.output_hash for r in receipts]
    unique_outputs = len(set(output_hashes))
    output_diverse = unique_outputs > 1 or len(receipts) <= 1
    if not output_diverse:
        detected_attacks.append("repeated_output")
    checks.append(VerificationCheck(
        name="output_diversity",
        passed=output_diverse,
        detail=f"unique={unique_outputs}/{len(receipts)}",
    ))

    # Check 8: No timeout in chain
    no_timeout = all(r.status != "timeout" for r in receipts)
    if not no_timeout:
        detected_attacks.append("timeout")
    checks.append(VerificationCheck(
        name="no_timeout_in_chain",
        passed=no_timeout,
    ))

    # Check 9: Receipt ID uniqueness (cross-task reuse)
    receipt_ids = [r.receipt_id for r in receipts]
    ids_unique_global = all(rid not in all_known_receipt_ids for rid in receipt_ids)
    if not ids_unique_global:
        detected_attacks.append("cross_task_receipt_reuse")
    checks.append(VerificationCheck(
        name="receipt_id_global_uniqueness",
        passed=ids_unique_global,
    ))

    # Check 10: Temporal ordering (started_at < ended_at, monotonic)
    temporal_valid = True
    for r in receipts:
        if r.started_at >= r.ended_at and r.duration_ms > 0:
            temporal_valid = False
            break
    checks.append(VerificationCheck(
        name="temporal_ordering",
        passed=temporal_valid,
    ))

    # Decision
    all_passed = all(c.passed for c in checks)
    critical_passed = all(c.passed for c in checks if c.name in {
        "receipt_chain_completeness", "task_id_consistency",
        "hash_format_validity", "receipt_hash_integrity",
    })

    if all_passed:
        decision = "release"
        confidence = 0.95 + rng.uniform(0, 0.05)
    elif critical_passed:
        decision = "hold"
        confidence = 0.5 + rng.uniform(0, 0.3)
    else:
        decision = "refund"
        confidence = 0.8 + rng.uniform(0, 0.15)

    elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000

    # Deduplicate attacks
    detected_attacks = list(dict.fromkeys(detected_attacks))

    return VerificationResult(
        verification_id=make_uuid(rng),
        task_id=task_id,
        bundle_id=bundle.bundle_id,
        decision=decision,
        confidence=round(min(confidence, 1.0), 4),
        checks=checks,
        detected_attacks=detected_attacks,
        verification_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Settlement Plan Generator
# ---------------------------------------------------------------------------

def generate_settlement_plan(
    rng: random.Random,
    task_id: str,
    verification: VerificationResult,
    escrow_amount: float,
) -> SettlementPlan:
    """Generate settlement plan based on verification result. No real funds."""
    trace_id = f"trace_{sha256(task_id)[:16]}"

    if verification.decision == "release":
        return SettlementPlan(
            task_id=task_id,
            trace_id=trace_id,
            decision="release",
            escrow_amount=escrow_amount,
            release_to_worker=escrow_amount,
            refund_to_client=0.0,
            reason="All verification checks passed",
            detected_attacks=[],
        )
    elif verification.decision == "hold":
        return SettlementPlan(
            task_id=task_id,
            trace_id=trace_id,
            decision="hold",
            escrow_amount=escrow_amount,
            release_to_worker=0.0,
            refund_to_client=0.0,
            reason=f"Held for review: {', '.join(verification.detected_attacks) or 'minor issues'}",
            detected_attacks=verification.detected_attacks,
        )
    else:  # refund
        return SettlementPlan(
            task_id=task_id,
            trace_id=trace_id,
            decision="refund",
            escrow_amount=escrow_amount,
            release_to_worker=0.0,
            refund_to_client=escrow_amount,
            reason=f"Structural violation: {', '.join(verification.detected_attacks)}",
            detected_attacks=verification.detected_attacks,
        )


# ---------------------------------------------------------------------------
# Scenario Runner
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    scenario: str
    total_tasks: int = 0
    honest_tasks: int = 0
    malicious_tasks: int = 0
    released: int = 0
    held: int = 0
    refunded: int = 0
    attacks_detected: dict = field(default_factory=dict)
    verification_times_ms: list[float] = field(default_factory=list)
    failed_cases: list[dict] = field(default_factory=list)
    receipt_chain_samples: list[list[dict]] = field(default_factory=list)
    evidence_bundle_samples: list[dict] = field(default_factory=list)
    verification_result_samples: list[dict] = field(default_factory=list)
    settlement_plan_samples: list[dict] = field(default_factory=list)


def run_scenario(
    scenario: str,
    agents: list[SimAgent],
    malicious_rate: float,
    rng: random.Random,
    all_known_receipt_ids: set[str],
    all_previous_receipts: list[SimReceipt],
) -> ScenarioResult:
    """Run a single scenario with the given agents."""
    result = ScenarioResult(scenario=scenario)
    tools = SCENARIO_TOOLS[scenario]

    workers = [a for a in agents if a.role == "worker"]
    clients = [a for a in agents if a.role == "client"]

    # Each worker gets one task per scenario
    for worker in workers:
        task_id = make_uuid(rng)
        client = rng.choice(clients)
        escrow = round(rng.uniform(5.0, 200.0), 2)
        task_contract = {
            "task_id": task_id,
            "client_agent_id": client.agent_id,
            "worker_agent_id": worker.agent_id,
            "scenario": scenario,
            "escrow_amount": escrow,
        }
        task_contract_hash = sha256(task_contract)

        result.total_tasks += 1

        if worker.is_malicious:
            result.malicious_tasks += 1
            receipts, bundle, attack_used = execute_malicious_task(
                rng, worker, task_id, scenario, task_contract_hash, all_previous_receipts
            )
        else:
            result.honest_tasks += 1
            receipts, bundle = execute_honest_task(
                rng, worker, task_id, scenario, task_contract_hash
            )
            attack_used = None

        # Verify
        verification = verify_bundle(
            receipts, bundle, task_id, tools, all_known_receipt_ids, rng
        )
        result.verification_times_ms.append(verification.verification_ms)

        # Settlement plan
        plan = generate_settlement_plan(rng, task_id, verification, escrow)

        # Track results
        if verification.decision == "release":
            result.released += 1
        elif verification.decision == "hold":
            result.held += 1
        else:
            result.refunded += 1

        # Track detected attacks
        for atk in verification.detected_attacks:
            result.attacks_detected[atk] = result.attacks_detected.get(atk, 0) + 1

        # Track failed cases (malicious that was detected, or honest that failed)
        if verification.decision != "release" and not worker.is_malicious:
            result.failed_cases.append({
                "task_id": task_id,
                "agent_id": worker.agent_id,
                "decision": verification.decision,
                "reason": "false_positive",
            })
        elif verification.decision == "release" and worker.is_malicious:
            result.failed_cases.append({
                "task_id": task_id,
                "agent_id": worker.agent_id,
                "decision": verification.decision,
                "attack_type": attack_used,
                "reason": "undetected_attack",
            })

        # Collect samples (first 3 of each)
        if len(result.receipt_chain_samples) < 3:
            result.receipt_chain_samples.append([r.to_dict() for r in receipts])
        if len(result.evidence_bundle_samples) < 3:
            result.evidence_bundle_samples.append(bundle.to_dict())
        if len(result.verification_result_samples) < 3:
            result.verification_result_samples.append(verification.to_dict())
        if len(result.settlement_plan_samples) < 3:
            result.settlement_plan_samples.append(plan.to_dict())

        # Update global state
        for r in receipts:
            all_known_receipt_ids.add(r.receipt_id)
            all_previous_receipts.append(r)

    return result


# ---------------------------------------------------------------------------
# Main Simulation
# ---------------------------------------------------------------------------

def run_simulation(
    scenarios: list[str],
    num_agents: int,
    malicious_rate: float,
    seed: int,
    output_dir: str,
) -> dict:
    """Run the full simulation and output results."""
    rng = random.Random(seed)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  KARMA TRUSTED AGENT RUNTIME — FULL SCENARIO SIMULATION")
    print(f"  Scenarios:       {', '.join(scenarios)}")
    print(f"  Agents:          {num_agents} (honest: {int(num_agents * (1 - malicious_rate))}, malicious: {int(num_agents * malicious_rate)})")
    print(f"  Malicious rate:  {malicious_rate:.0%}")
    print(f"  Seed:            {seed}")
    print(f"  Output:          {output_dir}")
    print("=" * 70)

    # Create agents
    num_workers = int(num_agents * 0.8)
    num_clients = num_agents - num_workers
    num_malicious_workers = int(num_workers * malicious_rate)
    num_honest_workers = num_workers - num_malicious_workers

    agents: list[SimAgent] = []

    # Honest workers
    for i in range(num_honest_workers):
        agents.append(SimAgent(
            agent_id=make_uuid(rng),
            name=f"honest-worker-{i:04d}",
            role="worker",
            is_malicious=False,
        ))

    # Malicious workers (each gets a specific attack type)
    for i in range(num_malicious_workers):
        attack = ATTACK_TYPES[i % len(ATTACK_TYPES)]
        agents.append(SimAgent(
            agent_id=make_uuid(rng),
            name=f"malicious-worker-{i:04d}",
            role="worker",
            is_malicious=True,
            attack_type=attack,
        ))

    # Clients (always honest)
    for i in range(num_clients):
        agents.append(SimAgent(
            agent_id=make_uuid(rng),
            name=f"client-{i:04d}",
            role="client",
            is_malicious=False,
        ))

    rng.shuffle(agents)

    # Global state
    all_known_receipt_ids: set[str] = set()
    all_previous_receipts: list[SimReceipt] = []

    # Run scenarios
    scenario_results: list[ScenarioResult] = []
    total_start = time.perf_counter()

    for idx, scenario in enumerate(scenarios, 1):
        print(f"\n[{idx}/{len(scenarios)}] Running: {scenario} ({num_workers} tasks)...")
        t0 = time.perf_counter()

        result = run_scenario(
            scenario, agents, malicious_rate, rng,
            all_known_receipt_ids, all_previous_receipts,
        )
        elapsed = time.perf_counter() - t0
        scenario_results.append(result)

        detection_rate = (result.refunded + result.held) / max(result.malicious_tasks, 1) * 100
        print(f"  ✓ {result.total_tasks} tasks | "
              f"released={result.released} held={result.held} refunded={result.refunded} | "
              f"detection={detection_rate:.0f}% | {elapsed:.2f}s")

    total_elapsed = time.perf_counter() - total_start

    # ---------------------------------------------------------------------------
    # Compute global statistics
    # ---------------------------------------------------------------------------

    all_verification_ms = []
    all_attacks_detected: dict[str, int] = {}
    all_failed_cases: list[dict] = []
    total_tasks = 0
    total_released = 0
    total_held = 0
    total_refunded = 0
    total_honest = 0
    total_malicious = 0

    for sr in scenario_results:
        all_verification_ms.extend(sr.verification_times_ms)
        for k, v in sr.attacks_detected.items():
            all_attacks_detected[k] = all_attacks_detected.get(k, 0) + v
        all_failed_cases.extend(sr.failed_cases)
        total_tasks += sr.total_tasks
        total_released += sr.released
        total_held += sr.held
        total_refunded += sr.refunded
        total_honest += sr.honest_tasks
        total_malicious += sr.malicious_tasks

    all_verification_ms.sort()
    avg_verification_ms = sum(all_verification_ms) / max(len(all_verification_ms), 1)
    p95_verification_ms = all_verification_ms[int(len(all_verification_ms) * 0.95)] if all_verification_ms else 0

    # Determinism check — rerun first scenario with same seed
    rng_check = random.Random(seed)
    # Recreate agents with same seed
    check_agents: list[SimAgent] = []
    for i in range(num_honest_workers):
        check_agents.append(SimAgent(
            agent_id=make_uuid(rng_check),
            name=f"honest-worker-{i:04d}",
            role="worker",
            is_malicious=False,
        ))
    for i in range(num_malicious_workers):
        attack = ATTACK_TYPES[i % len(ATTACK_TYPES)]
        check_agents.append(SimAgent(
            agent_id=make_uuid(rng_check),
            name=f"malicious-worker-{i:04d}",
            role="worker",
            is_malicious=True,
            attack_type=attack,
        ))
    for i in range(num_clients):
        check_agents.append(SimAgent(
            agent_id=make_uuid(rng_check),
            name=f"client-{i:04d}",
            role="client",
            is_malicious=False,
        ))
    rng_check.shuffle(check_agents)

    check_ids: set[str] = set()
    check_prev: list[SimReceipt] = []
    check_result = run_scenario(
        scenarios[0], check_agents, malicious_rate, rng_check,
        check_ids, check_prev,
    )
    determinism_match = (
        check_result.released == scenario_results[0].released
        and check_result.refunded == scenario_results[0].refunded
        and check_result.held == scenario_results[0].held
    )

    # ---------------------------------------------------------------------------
    # Output files
    # ---------------------------------------------------------------------------

    # full_scenario_summary.json
    full_summary = {
        "simulation_name": "karma_full_scenario_simulation",
        "timestamp": now_utc().isoformat(),
        "config": {
            "scenarios": scenarios,
            "num_agents": num_agents,
            "num_workers": num_workers,
            "num_clients": num_clients,
            "malicious_rate": malicious_rate,
            "seed": seed,
        },
        "results": {
            "total_tasks": total_tasks,
            "total_honest_tasks": total_honest,
            "total_malicious_tasks": total_malicious,
            "released": total_released,
            "held": total_held,
            "refunded": total_refunded,
            "honest_release_rate": round(total_released / max(total_honest, 1), 4),
            "malicious_detection_rate": round((total_held + total_refunded - (total_honest - total_released)) / max(total_malicious, 1), 4),
            "false_positive_count": sum(1 for f in all_failed_cases if f.get("reason") == "false_positive"),
            "undetected_attack_count": sum(1 for f in all_failed_cases if f.get("reason") == "undetected_attack"),
        },
        "performance": {
            "total_duration_s": round(total_elapsed, 2),
            "average_verification_ms": round(avg_verification_ms, 3),
            "p95_verification_ms": round(p95_verification_ms, 3),
            "tasks_per_second": round(total_tasks / max(total_elapsed, 0.001), 1),
        },
        "detected_attack_types": all_attacks_detected,
        "failed_cases": all_failed_cases[:50],
        "determinism_rerun_match": determinism_match,
        "verdict": "PASS" if determinism_match and total_released >= total_honest * 0.95 else "NEEDS_REVIEW",
    }

    with open(output_path / "full_scenario_summary.json", "w") as f:
        json.dump(full_summary, f, indent=2, ensure_ascii=False)

    # per_scenario_summary.json
    per_scenario = []
    for sr in scenario_results:
        sr_ms = sorted(sr.verification_times_ms)
        per_scenario.append({
            "scenario": sr.scenario,
            "total_tasks": sr.total_tasks,
            "honest_tasks": sr.honest_tasks,
            "malicious_tasks": sr.malicious_tasks,
            "released": sr.released,
            "held": sr.held,
            "refunded": sr.refunded,
            "detection_rate": round((sr.held + sr.refunded) / max(sr.malicious_tasks, 1), 4) if sr.malicious_tasks > 0 else None,
            "attacks_detected": sr.attacks_detected,
            "average_verification_ms": round(sum(sr_ms) / max(len(sr_ms), 1), 3),
            "p95_verification_ms": round(sr_ms[int(len(sr_ms) * 0.95)], 3) if sr_ms else 0,
            "failed_cases": sr.failed_cases[:10],
        })

    with open(output_path / "per_scenario_summary.json", "w") as f:
        json.dump(per_scenario, f, indent=2, ensure_ascii=False)

    # Samples
    samples = {
        "receipt_chain_samples": [],
        "evidence_bundle_samples": [],
        "verification_result_samples": [],
        "settlement_plan_samples": [],
    }
    for sr in scenario_results:
        samples["receipt_chain_samples"].extend(sr.receipt_chain_samples[:1])
        samples["evidence_bundle_samples"].extend(sr.evidence_bundle_samples[:1])
        samples["verification_result_samples"].extend(sr.verification_result_samples[:1])
        samples["settlement_plan_samples"].extend(sr.settlement_plan_samples[:1])

    with open(output_path / "samples.json", "w") as f:
        json.dump(samples, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 70)
    print("  SIMULATION COMPLETE")
    print("=" * 70)
    print(f"\n  Total tasks:            {total_tasks}")
    print(f"  Honest tasks:           {total_honest} (released: {total_released})")
    print(f"  Malicious tasks:        {total_malicious} (detected: {total_held + total_refunded - (total_honest - total_released)})")
    print(f"  Detection rate:         {full_summary['results']['malicious_detection_rate']:.1%}")
    print(f"  False positives:        {full_summary['results']['false_positive_count']}")
    print(f"  Undetected attacks:     {full_summary['results']['undetected_attack_count']}")
    print(f"  Avg verification:       {avg_verification_ms:.3f}ms")
    print(f"  P95 verification:       {p95_verification_ms:.3f}ms")
    print(f"  Determinism rerun:      {'✅ MATCH' if determinism_match else '❌ MISMATCH'}")
    print(f"  Duration:               {total_elapsed:.2f}s")
    print(f"\n  Detected attack types:")
    for atk, count in sorted(all_attacks_detected.items(), key=lambda x: -x[1]):
        print(f"    {atk:<30} {count}")
    print(f"\n  Output:                 {output_dir}/")
    print(f"  Verdict:                {full_summary['verdict']}")
    print("=" * 70)

    return full_summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Karma Trusted Agent Runtime — Full Scenario Simulation"
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default=",".join(ALL_SCENARIOS),
        help="Comma-separated scenario names",
    )
    parser.add_argument(
        "--agents",
        type=int,
        default=100,
        help="Number of agents (default: 100)",
    )
    parser.add_argument(
        "--malicious-rate",
        type=float,
        default=0.5,
        help="Fraction of workers that are malicious (default: 0.5)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for determinism (default: 42)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results/full-scenario-test",
        help="Output directory (default: results/full-scenario-test)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenarios = [s.strip() for s in args.scenarios.split(",")]

    for s in scenarios:
        if s not in ALL_SCENARIOS:
            print(f"ERROR: Unknown scenario '{s}'. Available: {ALL_SCENARIOS}")
            sys.exit(1)

    result = run_simulation(
        scenarios=scenarios,
        num_agents=args.agents,
        malicious_rate=args.malicious_rate,
        seed=args.seed,
        output_dir=args.output_dir,
    )

    sys.exit(0 if result["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
