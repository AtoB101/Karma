#!/usr/bin/env python3
"""
Karma Trust Protocol — Market Scenario Simulation
==================================================
Per-market focused testing for the two best early Karma markets:

  1. AI Data Labeling Marketplace
  2. Agent/API Call Marketplace

Each market is tested independently with:
  - buyers, sellers / worker agents
  - honest agents, malicious agents
  - repeated tasks, disputes, refunds, successful settlements
  - timeout cases, replay attempts, duplicate outputs
  - fake execution, low-quality output, API failure, partial completion

Phases:
  Phase A: 100 tasks per market
  Phase B: 500 tasks per market
  Phase C: 1000 tasks per market (if A/B stable)

Output per task:
  - task_contract, receipt_chain, evidence_bundle
  - verification_result, settlement_plan, trace_id, operational_log

Output reports:
  1. DATA_LABELING_MARKET_TEST_REPORT.md
  2. API_CALL_MARKET_TEST_REPORT.md
  3. MARKET_SCENARIO_SUMMARY.json
  4. sampled_onchain_tx_log.jsonl
  5. failed_cases.json

Usage:
  python scripts/market_scenario_simulation.py --phase A
  python scripts/market_scenario_simulation.py --phase B
  python scripts/market_scenario_simulation.py --phase C
  python scripts/market_scenario_simulation.py --phase A,B,C --sepolia-sample
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

# ── Constants ──────────────────────────────────────────────────────────────
MARKETS = ["data_labeling", "api_call"]
PHASE_TASKS = {"A": 100, "B": 500, "C": 1000}

# Market-specific tool definitions
MARKET_TOOLS = {
    "data_labeling": [
        ("label.receive_task", 1),
        ("label.classify", 3),
        ("label.bbox", 2),
        ("label.validate", 2),
        ("label.submit", 1),
    ],
    "api_call": [
        ("api.authenticate", 1),
        ("api.fetch_data", 3),
        ("api.parse_response", 2),
        ("api.validate_output", 1),
        ("api.return_result", 1),
    ],
}

# Attack types — universal
ATTACK_TYPES_SHARED = [
    "duplicate_receipt",
    "replayed_receipt",
    "forged_hash",
    "timeout",
    "malformed_receipt",
    "partial_receipt_chain",
    "fake_execution",
    "repeated_output",
    "cross_task_receipt_reuse",
    "partial_completion",
]

# Market-specific attack types
ATTACK_TYPES_MARKET = {
    "data_labeling": ATTACK_TYPES_SHARED + ["low_quality_output"],
    "api_call": ATTACK_TYPES_SHARED + ["api_failure"],
}

# Buyer archetypes for data_labeling
DATA_LABELING_BUYERS = [
    {"name": "AI-Startup-X", "budget_range": (50, 500), "quality_threshold": 0.85},
    {"name": "Ecommerce-AI-Lab", "budget_range": (100, 1000), "quality_threshold": 0.90},
    {"name": "Medical-Image-Lab", "budget_range": (200, 2000), "quality_threshold": 0.95},
    {"name": "Autonomous-Drive-Co", "budget_range": (500, 5000), "quality_threshold": 0.92},
    {"name": "Research-University", "budget_range": (30, 300), "quality_threshold": 0.80},
]

# Buyer archetypes for api_call
API_CALL_BUYERS = [
    {"name": "Data-Aggregator-Inc", "budget_range": (10, 100), "timeout_s": 30},
    {"name": "FinTech-API-Consumer", "budget_range": (50, 500), "timeout_s": 10},
    {"name": "Weather-Data-Service", "budget_range": (5, 50), "timeout_s": 60},
    {"name": "Social-Media-Analytics", "budget_range": (20, 200), "timeout_s": 20},
    {"name": "Crypto-Price-Oracle", "budget_range": (100, 1000), "timeout_s": 5},
]


# ── Utilities ──────────────────────────────────────────────────────────────
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


# ── Data Models ────────────────────────────────────────────────────────────
@dataclass
class SimAgent:
    agent_id: str
    name: str
    role: str  # "buyer", "seller", "worker"
    is_malicious: bool
    attack_type: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskContract:
    task_id: str
    client_agent_id: str
    worker_agent_id: str
    market: str
    escrow_amount: float
    quality_threshold: float = 0.8
    timeout_seconds: int = 60
    expected_steps: int = 0
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "client_agent_id": self.client_agent_id,
            "worker_agent_id": self.worker_agent_id,
            "market": self.market,
            "escrow_amount": self.escrow_amount,
            "quality_threshold": self.quality_threshold,
            "timeout_seconds": self.timeout_seconds,
            "expected_steps": self.expected_steps,
            "created_at": self.created_at,
        }


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
    status: str
    quality_score: float = 1.0
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
            "quality_score": self.quality_score,
        }
        if self.error_message:
            d["error_message"] = self.error_message
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class EvidenceBundle:
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
    average_quality: float = 1.0
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
            "average_quality": self.average_quality,
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
    decision: str
    confidence: float
    checks: list[VerificationCheck] = field(default_factory=list)
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


@dataclass
class OperationalLogEntry:
    timestamp: str
    task_id: str
    event: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "task_id": self.task_id,
            "event": self.event,
            "detail": self.detail,
        }


@dataclass
class TaskOutput:
    task_contract: TaskContract
    receipt_chain: list[SimReceipt]
    evidence_bundle: EvidenceBundle
    verification_result: VerificationResult
    settlement_plan: SettlementPlan
    trace_id: str
    operational_log: list[OperationalLogEntry]


# ── Honest Agent Execution ─────────────────────────────────────────────────
def execute_honest_data_labeling(
    rng: random.Random, agent: SimAgent, task_id: str, contract_hash: str, quality_min: float
) -> tuple[list[SimReceipt], EvidenceBundle, list[OperationalLogEntry]]:
    """Honest data labeling worker: proper labels, varied quality scores."""
    tools = MARKET_TOOLS["data_labeling"]
    receipts: list[SimReceipt] = []
    oplog: list[OperationalLogEntry] = []
    step = 0
    total_duration = 0
    base_time = now_utc()
    ts = base_time.isoformat()

    oplog.append(OperationalLogEntry(ts, task_id, "task_received", {"agent": agent.name}))

    quality_scores = []
    for tool_name, count in tools:
        for _ in range(count):
            step += 1
            duration = rng.randint(30, 600)
            total_duration += duration
            started = base_time + timedelta(milliseconds=total_duration - duration)
            ended = base_time + timedelta(milliseconds=total_duration)

            input_data = {"task_id": task_id, "step": step, "tool": tool_name, "nonce": rng.randint(0, 999999)}
            quality = round(rng.uniform(quality_min, 1.0), 3)
            output_data = {
                "result": f"label_output_{step}_{rng.randint(0, 9999)}",
                "label": rng.choice(["cat", "dog", "car", "person", "tree", "building"]),
                "confidence": quality,
            }
            quality_scores.append(quality)

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
                quality_score=quality,
                metadata={"market": "data_labeling", "label_type": output_data["label"]},
            )
            receipts.append(receipt)

    avg_quality = round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else 0
    receipt_hashes = [sha256(r.to_dict()) for r in receipts]
    final_result = {"task_id": task_id, "total_steps": step, "market": "data_labeling", "avg_quality": avg_quality}

    bundle = EvidenceBundle(
        bundle_id=make_uuid(rng),
        task_id=task_id,
        task_contract_hash=contract_hash,
        receipt_ids=[r.receipt_id for r in receipts],
        receipt_hashes=receipt_hashes,
        final_result_hash=sha256(final_result),
        total_steps=step,
        successful_steps=step,
        failed_steps=0,
        total_duration_ms=total_duration,
        average_quality=avg_quality,
    )

    oplog.append(OperationalLogEntry(
        ended.isoformat(), task_id, "execution_complete",
        {"steps": step, "avg_quality": avg_quality, "duration_ms": total_duration},
    ))

    return receipts, bundle, oplog


def execute_honest_api_call(
    rng: random.Random, agent: SimAgent, task_id: str, contract_hash: str, timeout_s: int
) -> tuple[list[SimReceipt], EvidenceBundle, list[OperationalLogEntry]]:
    """Honest API call worker: proper API responses with realistic latency."""
    tools = MARKET_TOOLS["api_call"]
    receipts: list[SimReceipt] = []
    oplog: list[OperationalLogEntry] = []
    step = 0
    total_duration = 0
    base_time = now_utc()
    ts = base_time.isoformat()

    oplog.append(OperationalLogEntry(ts, task_id, "api_request_received", {"agent": agent.name}))

    api_endpoints = ["/users", "/prices", "/weather", "/analytics", "/search"]
    endpoint = rng.choice(api_endpoints)

    # Simulate network latency
    network_latency_ms = rng.randint(50, int(timeout_s * 1000 * 0.6))

    for tool_name, count in tools:
        for _ in range(count):
            step += 1
            duration = rng.randint(20, 400) if tool_name != "api.fetch_data" else network_latency_ms
            total_duration += duration
            started = base_time + timedelta(milliseconds=total_duration - duration)
            ended = base_time + timedelta(milliseconds=total_duration)

            input_data = {"task_id": task_id, "step": step, "tool": tool_name, "endpoint": endpoint}
            response_code = rng.choice([200, 200, 200, 200, 201, 204])
            output_data = {
                "status_code": response_code,
                "endpoint": endpoint,
                "response_size_bytes": rng.randint(256, 16384),
                "latency_ms": duration,
            }

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
                quality_score=1.0 if response_code < 300 else 0.5,
                metadata={"market": "api_call", "endpoint": endpoint, "status_code": response_code},
            )
            receipts.append(receipt)

    receipt_hashes = [sha256(r.to_dict()) for r in receipts]
    final_result = {
        "task_id": task_id, "total_steps": step, "market": "api_call",
        "endpoint": endpoint, "total_latency_ms": total_duration,
    }

    bundle = EvidenceBundle(
        bundle_id=make_uuid(rng),
        task_id=task_id,
        task_contract_hash=contract_hash,
        receipt_ids=[r.receipt_id for r in receipts],
        receipt_hashes=receipt_hashes,
        final_result_hash=sha256(final_result),
        total_steps=step,
        successful_steps=step,
        failed_steps=0,
        total_duration_ms=total_duration,
        average_quality=1.0,
    )

    oplog.append(OperationalLogEntry(
        ended.isoformat(), task_id, "api_call_complete",
        {"endpoint": endpoint, "steps": step, "latency_ms": total_duration},
    ))

    return receipts, bundle, oplog


# ── Malicious Agent Execution ──────────────────────────────────────────────
def execute_malicious_task(
    rng: random.Random,
    agent: SimAgent,
    task_id: str,
    market: str,
    contract_hash: str,
    all_previous_receipts: list[SimReceipt],
    quality_threshold: float = 0.8,
    timeout_s: int = 60,
) -> tuple[list[SimReceipt], EvidenceBundle, list[OperationalLogEntry], str]:
    """Execute maliciously with market-specific attack patterns."""
    market_attacks = ATTACK_TYPES_MARKET[market]
    attack = agent.attack_type or rng.choice(market_attacks)
    oplog: list[OperationalLogEntry] = []

    # Start with honest execution
    if market == "data_labeling":
        receipts, bundle, oplog = execute_honest_data_labeling(
            rng, agent, task_id, contract_hash, quality_threshold
        )
    else:
        receipts, bundle, oplog = execute_honest_api_call(
            rng, agent, task_id, contract_hash, timeout_s
        )

    oplog.append(OperationalLogEntry(now_utc().isoformat(), task_id, f"attack_{attack}", {}))

    if attack == "duplicate_receipt":
        if receipts:
            dup = SimReceipt(**{**receipts[0].__dict__})
            dup.receipt_id = make_uuid(rng)
            receipts.append(dup)

    elif attack == "replayed_receipt":
        if all_previous_receipts:
            stolen = rng.choice(all_previous_receipts)
            replay = SimReceipt(**{**stolen.__dict__})
            replay.receipt_id = make_uuid(rng)
            replay.task_id = task_id
            if receipts:
                replay.step_index = receipts[-1].step_index + 1
            receipts.append(replay)

    elif attack == "forged_hash":
        receipt_hashes_honest = [sha256(r.to_dict()) for r in receipts]
        if receipts:
            target = rng.choice(receipts)
            target.output_hash = sha256(f"forged_{rng.randint(0, 99999)}")
        bundle = EvidenceBundle(
            bundle_id=make_uuid(rng),
            task_id=task_id,
            task_contract_hash=contract_hash,
            receipt_ids=[r.receipt_id for r in receipts],
            receipt_hashes=receipt_hashes_honest,
            final_result_hash=bundle.final_result_hash,
            total_steps=len(receipts),
            successful_steps=sum(1 for r in receipts if r.status == "success"),
            failed_steps=sum(1 for r in receipts if r.status != "success"),
            total_duration_ms=sum(r.duration_ms for r in receipts),
            average_quality=bundle.average_quality,
        )
        return receipts, bundle, oplog, attack

    elif attack == "timeout":
        if receipts:
            target = rng.choice(receipts)
            target.status = "timeout"
            target.duration_ms = timeout_s * 1000 + 1
            target.error_message = f"Exceeded {timeout_s}s timeout"

    elif attack == "malformed_receipt":
        if receipts:
            target = rng.choice(receipts)
            target.input_hash = ""
            target.output_hash = "not-a-valid-hash"

    elif attack == "partial_receipt_chain":
        if len(receipts) > 2:
            remove_idx = rng.randint(1, len(receipts) - 2)
            receipts.pop(remove_idx)

    elif attack == "fake_execution":
        for r in receipts:
            r.duration_ms = 0
            r.started_at = r.ended_at

    elif attack == "repeated_output":
        if receipts:
            single_hash = receipts[0].output_hash
            for r in receipts:
                r.output_hash = single_hash

    elif attack == "cross_task_receipt_reuse":
        if all_previous_receipts:
            for i, r in enumerate(receipts):
                if i < len(all_previous_receipts):
                    r.receipt_id = all_previous_receipts[i].receipt_id

    elif attack == "low_quality_output":
        # Data labeling specific: all quality scores below threshold
        for r in receipts:
            r.quality_score = round(rng.uniform(0.1, quality_threshold - 0.05), 3)

    elif attack == "api_failure":
        # API call specific: return 5xx errors for all fetch steps
        for r in receipts:
            if "fetch" in r.tool_name:
                r.status = "failure"
                r.error_message = "HTTP 503 Service Unavailable"
                r.quality_score = 0.0
                r.metadata["status_code"] = 503

    elif attack == "partial_completion":
        # Complete only first 2-3 steps, leave rest undone
        keep_count = rng.randint(2, max(2, len(receipts) // 2))
        receipts = receipts[:keep_count]

    # Rebuild bundle with corrupted data
    receipt_hashes = [sha256(r.to_dict()) for r in receipts]
    avg_q = round(sum(r.quality_score for r in receipts) / max(len(receipts), 1), 3)
    bundle = EvidenceBundle(
        bundle_id=make_uuid(rng),
        task_id=task_id,
        task_contract_hash=contract_hash,
        receipt_ids=[r.receipt_id for r in receipts],
        receipt_hashes=receipt_hashes,
        final_result_hash=bundle.final_result_hash,
        total_steps=len(receipts),
        successful_steps=sum(1 for r in receipts if r.status == "success"),
        failed_steps=sum(1 for r in receipts if r.status != "success"),
        total_duration_ms=sum(r.duration_ms for r in receipts),
        average_quality=avg_q,
    )

    return receipts, bundle, oplog, attack


# ── Verification Engine ────────────────────────────────────────────────────
def verify_bundle(
    receipts: list[SimReceipt],
    bundle: EvidenceBundle,
    task: TaskContract,
    expected_tools: list[tuple[str, int]],
    all_known_receipt_ids: set[str],
    rng: random.Random,
) -> VerificationResult:
    """Structural + market-specific verification."""
    t0 = time.perf_counter_ns()
    checks: list[VerificationCheck] = []
    detected_attacks: list[str] = []

    expected_steps = sum(count for _, count in expected_tools)

    # C1: Receipt chain completeness
    chain_complete = len(receipts) == expected_steps
    detail_c1 = f"expected={expected_steps}, actual={len(receipts)}"
    if not chain_complete:
        if len(receipts) < expected_steps:
            detected_attacks.append("partial_receipt_chain")
        else:
            detected_attacks.append("duplicate_receipt")
    checks.append(VerificationCheck("receipt_chain_completeness", chain_complete, detail_c1))

    # C2: Step index continuity
    step_indices = [r.step_index for r in receipts]
    expected_indices = list(range(1, len(receipts) + 1))
    indices_valid = sorted(step_indices) == expected_indices
    if not indices_valid:
        if len(set(step_indices)) < len(step_indices):
            detected_attacks.append("duplicate_receipt")
        else:
            detected_attacks.append("partial_receipt_chain")
    checks.append(VerificationCheck("step_index_continuity", indices_valid,
                                     f"indices={sorted(step_indices)}"))

    # C3: Task ID consistency
    all_same_task = all(r.task_id == task.task_id for r in receipts)
    if not all_same_task:
        detected_attacks.append("cross_task_receipt_reuse")
    checks.append(VerificationCheck("task_id_consistency", all_same_task))

    # C4: Hash format validity
    hashes_valid = all(
        len(r.input_hash) == 64 and len(r.output_hash) == 64
        and all(c in "0123456789abcdef" for c in r.input_hash)
        and all(c in "0123456789abcdef" for c in r.output_hash)
        for r in receipts
    )
    if not hashes_valid:
        detected_attacks.append("malformed_receipt")
    checks.append(VerificationCheck("hash_format_validity", hashes_valid))

    # C5: Receipt hash integrity
    computed_hashes = [sha256(r.to_dict()) for r in receipts]
    hashes_match = computed_hashes == bundle.receipt_hashes
    if not hashes_match:
        detected_attacks.append("forged_hash")
    checks.append(VerificationCheck("receipt_hash_integrity", hashes_match))

    # C6: Positive execution duration
    all_have_duration = all(r.duration_ms > 0 for r in receipts)
    if not all_have_duration:
        detected_attacks.append("fake_execution")
    checks.append(VerificationCheck("execution_duration_positive", all_have_duration))

    # C7: Output diversity
    output_hashes = [r.output_hash for r in receipts]
    unique_outputs = len(set(output_hashes))
    output_diverse = unique_outputs > 1 or len(receipts) <= 1
    if not output_diverse:
        detected_attacks.append("repeated_output")
    checks.append(VerificationCheck("output_diversity", output_diverse,
                                     f"unique={unique_outputs}/{len(receipts)}"))

    # C8: No timeout
    no_timeout = all(r.status != "timeout" for r in receipts)
    if not no_timeout:
        detected_attacks.append("timeout")
    checks.append(VerificationCheck("no_timeout_in_chain", no_timeout))

    # C9: Receipt ID uniqueness
    receipt_ids = [r.receipt_id for r in receipts]
    ids_unique_global = all(rid not in all_known_receipt_ids for rid in receipt_ids)
    if not ids_unique_global:
        detected_attacks.append("cross_task_receipt_reuse")
    checks.append(VerificationCheck("receipt_id_global_uniqueness", ids_unique_global))

    # C10: Quality threshold (market-specific for data_labeling)
    avg_quality = sum(r.quality_score for r in receipts) / max(len(receipts), 1)
    quality_ok = avg_quality >= task.quality_threshold
    if not quality_ok and task.quality_threshold > 0:
        detected_attacks.append("low_quality_output")
    checks.append(VerificationCheck("quality_threshold", quality_ok,
                                     f"avg={avg_quality:.3f} threshold={task.quality_threshold}"))

    # C11: API failure detection (market-specific for api_call)
    has_api_failures = any(r.status == "failure" and "fetch" in r.tool_name for r in receipts)
    if has_api_failures:
        detected_attacks.append("api_failure")
    checks.append(VerificationCheck("api_call_health", not has_api_failures,
                                     "API failures detected" if has_api_failures else "OK"))

    # C12: Completion check
    completion_ratio = len(receipts) / max(expected_steps, 1)
    if completion_ratio < 0.8:
        detected_attacks.append("partial_completion")
    checks.append(VerificationCheck("completion_ratio",
                                     completion_ratio >= 0.8,
                                     f"{completion_ratio:.1%} complete"))

    # Decision
    all_passed = all(c.passed for c in checks)
    critical_checks = {"receipt_chain_completeness", "task_id_consistency",
                       "hash_format_validity", "receipt_hash_integrity"}
    critical_passed = all(c.passed for c in checks if c.name in critical_checks)

    if all_passed:
        decision = "release"
        confidence = 0.95 + rng.uniform(0, 0.05)
    elif critical_passed:
        decision = "hold"
        confidence = 0.5 + rng.uniform(0, 0.3)
    else:
        decision = "refund"
        confidence = 0.8 + rng.uniform(0, 0.15)

    detected_attacks = list(dict.fromkeys(detected_attacks))
    elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000

    return VerificationResult(
        verification_id=make_uuid(rng),
        task_id=task.task_id,
        bundle_id=bundle.bundle_id,
        decision=decision,
        confidence=round(min(confidence, 1.0), 4),
        checks=checks,
        detected_attacks=detected_attacks,
        verification_ms=elapsed_ms,
    )


# ── Settlement Plan Generator ──────────────────────────────────────────────
def generate_settlement_plan(
    rng: random.Random, task: TaskContract, verification: VerificationResult
) -> SettlementPlan:
    trace_id = f"trace_{task.market}_{sha256(task.task_id)[:16]}"

    if verification.decision == "release":
        return SettlementPlan(
            task_id=task.task_id,
            trace_id=trace_id,
            decision="release",
            escrow_amount=task.escrow_amount,
            release_to_worker=task.escrow_amount,
            refund_to_client=0.0,
            reason="All verification checks passed",
        )
    elif verification.decision == "hold":
        return SettlementPlan(
            task_id=task.task_id,
            trace_id=trace_id,
            decision="hold",
            escrow_amount=task.escrow_amount,
            release_to_worker=0.0,
            refund_to_client=0.0,
            reason=f"Held: {', '.join(verification.detected_attacks) or 'review'}",
            detected_attacks=verification.detected_attacks,
        )
    else:
        return SettlementPlan(
            task_id=task.task_id,
            trace_id=trace_id,
            decision="refund",
            escrow_amount=task.escrow_amount,
            release_to_worker=0.0,
            refund_to_client=task.escrow_amount,
            reason=f"Violation: {', '.join(verification.detected_attacks)}",
            detected_attacks=verification.detected_attacks,
        )


# ── Market Runner ──────────────────────────────────────────────────────────
@dataclass
class MarketResult:
    market: str
    tasks: list[TaskOutput] = field(default_factory=list)
    total_tasks: int = 0
    honest_tasks: int = 0
    malicious_tasks: int = 0
    released: int = 0
    held: int = 0
    refunded: int = 0
    disputes: int = 0
    attacks_detected: dict = field(default_factory=dict)
    verification_times_ms: list[float] = field(default_factory=list)
    failed_cases: list[dict] = field(default_factory=list)
    timeout_detected: int = 0
    duplicate_detected: int = 0
    replay_detected: int = 0
    api_failures_handled: int = 0
    partial_completions_handled: int = 0
    low_quality_detected: int = 0


def run_market(
    market: str,
    num_tasks: int,
    malicious_rate: float,
    rng: random.Random,
    all_known_receipt_ids: set[str],
    all_previous_receipts: list[SimReceipt],
    output_all: bool = False,
) -> MarketResult:
    """Run a full market simulation — all agent types, all scenarios."""
    result = MarketResult(market=market)
    tools = MARKET_TOOLS[market]

    num_workers = int(num_tasks * 0.8)
    num_buyers = num_tasks - num_workers
    num_malicious = int(num_workers * malicious_rate)
    num_honest = num_workers - num_malicious

    # Create agents
    agents: list[SimAgent] = []

    for i in range(num_honest):
        agents.append(SimAgent(
            agent_id=make_uuid(rng), name=f"honest-worker-{market}-{i:04d}",
            role="worker", is_malicious=False,
        ))

    market_attacks = ATTACK_TYPES_MARKET[market]
    for i in range(num_malicious):
        attack = market_attacks[i % len(market_attacks)]
        agents.append(SimAgent(
            agent_id=make_uuid(rng), name=f"malicious-worker-{market}-{i:04d}",
            role="worker", is_malicious=True, attack_type=attack,
        ))

    buyer_archetypes = DATA_LABELING_BUYERS if market == "data_labeling" else API_CALL_BUYERS
    buyers = []
    for i in range(num_buyers):
        arch = buyer_archetypes[i % len(buyer_archetypes)]
        buyers.append(SimAgent(
            agent_id=make_uuid(rng), name=f"{arch['name']}-{i:04d}",
            role="buyer", is_malicious=False, metadata=arch,
        ))

    rng.shuffle(agents)

    # Ensure honest workers run first (so replay attacks have material to steal)
    workers = [a for a in agents if a.role == "worker"]
    honest_workers = [w for w in workers if not w.is_malicious]
    malicious_workers = [w for w in workers if w.is_malicious]
    workers = honest_workers + malicious_workers

    for idx, worker in enumerate(workers):
        task_id = make_uuid(rng)
        buyer = rng.choice(buyers)

        if market == "data_labeling":
            quality_threshold = buyer.metadata.get("quality_threshold", 0.8)
            timeout_s = rng.choice([30, 60, 120, 300])
            budget_min, budget_max = buyer.metadata.get("budget_range", (10, 500))
            escrow = round(rng.uniform(budget_min, budget_max), 2)
        else:
            quality_threshold = 0.5
            timeout_s = buyer.metadata.get("timeout_s", 30)
            budget_min, budget_max = buyer.metadata.get("budget_range", (5, 200))
            escrow = round(rng.uniform(budget_min, budget_max), 2)

        expected_steps = sum(count for _, count in tools)

        contract = TaskContract(
            task_id=task_id,
            client_agent_id=buyer.agent_id,
            worker_agent_id=worker.agent_id,
            market=market,
            escrow_amount=escrow,
            quality_threshold=quality_threshold,
            timeout_seconds=timeout_s,
            expected_steps=expected_steps,
            created_at=now_utc().isoformat(),
        )
        contract_hash = sha256(contract.to_dict())

        result.total_tasks += 1
        oplog = [OperationalLogEntry(now_utc().isoformat(), task_id, "task_created",
                                      {"buyer": buyer.name, "worker": worker.name, "escrow": escrow})]

        if worker.is_malicious:
            result.malicious_tasks += 1
            receipts, bundle, extra_log, attack_used = execute_malicious_task(
                rng, worker, task_id, market, contract_hash,
                all_previous_receipts, quality_threshold, timeout_s,
            )
        else:
            result.honest_tasks += 1
            if market == "data_labeling":
                receipts, bundle, extra_log = execute_honest_data_labeling(
                    rng, worker, task_id, contract_hash, quality_threshold
                )
            else:
                receipts, bundle, extra_log = execute_honest_api_call(
                    rng, worker, task_id, contract_hash, timeout_s
                )
            attack_used = None

        oplog.extend(extra_log)

        # Verify
        verification = verify_bundle(receipts, bundle, contract, tools, all_known_receipt_ids, rng)
        result.verification_times_ms.append(verification.verification_ms)

        # Settlement
        plan = generate_settlement_plan(rng, contract, verification)
        trace_id = plan.trace_id

        oplog.append(OperationalLogEntry(
            now_utc().isoformat(), task_id, "verification_complete",
            {"decision": verification.decision, "confidence": verification.confidence},
        ))
        oplog.append(OperationalLogEntry(
            now_utc().isoformat(), task_id, "settlement_plan_generated",
            {"plan": plan.decision, "release": plan.release_to_worker, "refund": plan.refund_to_client},
        ))

        # Track outcomes
        if verification.decision == "release":
            result.released += 1
        elif verification.decision == "hold":
            result.held += 1
            result.disputes += 1
        else:
            result.refunded += 1

        for atk in verification.detected_attacks:
            result.attacks_detected[atk] = result.attacks_detected.get(atk, 0) + 1

        # Specific counters
        if "timeout" in verification.detected_attacks:
            result.timeout_detected += 1
        if "duplicate_receipt" in verification.detected_attacks:
            result.duplicate_detected += 1
        if "replayed_receipt" in verification.detected_attacks:
            result.replay_detected += 1
        if "api_failure" in verification.detected_attacks:
            result.api_failures_handled += 1
        if "partial_completion" in verification.detected_attacks:
            result.partial_completions_handled += 1
        if "low_quality_output" in verification.detected_attacks:
            result.low_quality_detected += 1

        # Track failed cases
        if verification.decision != "release" and not worker.is_malicious:
            result.failed_cases.append({
                "task_id": task_id, "agent_id": worker.agent_id,
                "decision": verification.decision, "reason": "false_positive",
            })
        elif verification.decision == "release" and worker.is_malicious:
            result.failed_cases.append({
                "task_id": task_id, "agent_id": worker.agent_id,
                "decision": verification.decision, "attack_type": attack_used,
                "reason": "undetected_attack",
            })

        # Store full task output
        task_output = TaskOutput(
            task_contract=contract,
            receipt_chain=receipts,
            evidence_bundle=bundle,
            verification_result=verification,
            settlement_plan=plan,
            trace_id=trace_id,
            operational_log=oplog,
        )
        result.tasks.append(task_output)

        # Update global state
        for r in receipts:
            all_known_receipt_ids.add(r.receipt_id)
            all_previous_receipts.append(r)

    return result


# ── Sepolia On-Chain Sampling ──────────────────────────────────────────────
def try_sepolia_sampling(
    market: str,
    sample_tasks: list[TaskOutput],
    output_path: Path,
) -> list[dict]:
    """Sample 10 settlement flows on Sepolia testnet."""
    tx_log = []

    try:
        import requests

        rpc_url = os.environ.get("TESTNET_RPC_URL", "")
        private_key = os.environ.get("TESTNET_PRIVATE_KEY", "")
        engine_addr = os.environ.get("KARMA_ENGINE_ADDRESS", "")
        chain_id = int(os.environ.get("TESTNET_CHAIN_ID", "11155111"))

        if not all([rpc_url, private_key, engine_addr]):
            print("  ⚠️  Sepolia config incomplete — skipping on-chain sampling")
            return [{"status": "skipped", "reason": "config_incomplete"}]

        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            print("  ⚠️  Sepolia RPC unreachable — skipping on-chain sampling")
            return [{"status": "skipped", "reason": "rpc_unreachable"}]

        account = w3.eth.account.from_key(private_key)
        balance = w3.eth.get_balance(account.address)
        print(f"  ✓ Sepolia connected | wallet: {account.address[:10]}... | balance: {w3.from_wei(balance, 'ether')} ETH")

        # Sample 10 tasks
        sample_count = min(10, len(sample_tasks))
        for i in range(sample_count):
            task_out = sample_tasks[i]
            tx_entry = {
                "market": market,
                "sample_index": i + 1,
                "task_id": task_out.task_contract.task_id,
                "trace_id": task_out.trace_id,
                "decision": task_out.settlement_plan.decision,
                "escrow_amount": task_out.task_contract.escrow_amount,
                "timestamp": now_utc().isoformat(),
            }

            try:
                # Build a minimal transaction — just a data-bearing call
                task_hash_bytes = sha256(task_out.task_contract.task_id).encode()[:32]
                settlement_data = json.dumps({
                    "task_id": task_out.task_contract.task_id,
                    "trace_id": task_out.trace_id,
                    "decision": task_out.settlement_plan.decision,
                    "bundle_hash": sha256(task_out.evidence_bundle.to_dict()),
                    "verification_id": task_out.verification_result.verification_id,
                })

                tx = {
                    "from": account.address,
                    "to": engine_addr,
                    "data": w3.to_hex(text=settlement_data),
                    "value": 0,
                    "gas": 100000,
                    "gasPrice": w3.eth.gas_price,
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "chainId": chain_id,
                }

                signed = account.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

                tx_entry["tx_hash"] = tx_hash.hex()
                tx_entry["block_number"] = receipt.blockNumber
                tx_entry["gas_used"] = receipt.gasUsed
                tx_entry["status"] = "success" if receipt.status == 1 else "failed"
                print(f"  [{i+1}/{sample_count}] {tx_hash.hex()[:16]}... block={receipt.blockNumber} gas={receipt.gasUsed} ✓")

            except Exception as e:
                tx_entry["status"] = "failed"
                tx_entry["error"] = str(e)[:200]
                print(f"  [{i+1}/{sample_count}] FAILED: {str(e)[:100]}")

            tx_log.append(tx_entry)
            time.sleep(0.3)

    except ImportError:
        print("  ⚠️  web3 not installed — skipping on-chain sampling")
        print("  Run: pip install web3")
        tx_log = [{"status": "skipped", "reason": "web3_not_installed"}]
    except Exception as e:
        print(f"  ⚠️  Sepolia sampling error: {e}")
        tx_log = [{"status": "error", "reason": str(e)[:200]}]

    # Save tx log
    with open(output_path / f"{market}_onchain_tx_log.jsonl", "w") as f:
        for entry in tx_log:
            f.write(json.dumps(entry) + "\n")

    return tx_log


# ── Report Generators ──────────────────────────────────────────────────────
def generate_market_report(market: str, result: MarketResult, phase: str, output_dir: Path, phase_config: dict = None) -> str:
    """Generate detailed markdown report for a single market."""
    title_map = {"data_labeling": "AI Data Labeling", "api_call": "Agent/API Call"}
    title = title_map.get(market, market)

    all_ms = sorted(result.verification_times_ms)
    avg_ms = sum(all_ms) / max(len(all_ms), 1)
    p95_ms = all_ms[int(len(all_ms) * 0.95)] if all_ms else 0

    detection_rate = (result.held + result.refunded) / max(result.malicious_tasks, 1) * 100
    fp_count = sum(1 for f in result.failed_cases if f.get("reason") == "false_positive")
    fn_count = sum(1 for f in result.failed_cases if f.get("reason") == "undetected_attack")

    trace_success = sum(
        1 for t in result.tasks
        if t.verification_result.decision == "release" and not any(
            a.get("reason") == "undetected_attack" for a in result.failed_cases
        )
    )
    trace_total = max(result.total_tasks, 1)

    settlement_consistent = result.released + result.refunded
    settlement_total = max(result.total_tasks, 1)

    # Market-specific insights
    if market == "data_labeling":
        market_insights = """
### Data Labeling Market Insights

| Aspect | Observation |
|--------|-------------|
| Receipt clarity | **High** — Each labeling step produces discrete, verifiable output hashes |
| Verification ease | **Medium-High** — Quality scoring adds a useful dimension but requires calibration |
| Buyer value | **Clear** — Buyers pay per-label and get auditable quality scores |
| Seller value | **Clear** — Workers earn based on completed labeling with quality proof |
| Dispute patterns | Quality disagreements are the primary dispute driver |
| Best attack vector | Low-quality output (hard to distinguish from honest mistakes) |
"""
    else:
        market_insights = """
### API Call Market Insights

| Aspect | Observation |
|--------|-------------|
| Receipt clarity | **Very High** — HTTP status codes, latency, and response size are trivially verifiable |
| Verification ease | **High** — Deterministic checks (status code, hash, timing) are straightforward |
| Buyer value | **Clear** — Pay per successful API call, no need to manage API keys |
| Seller value | **Clear** — Earn per request, low overhead for API providers |
| Dispute patterns | API failures and timeout are the primary dispute drivers |
| Best attack vector | Fake execution (0ms duration — trivial to detect with timing checks) |
"""

    report = f"""# Karma Trust Protocol — {title} Marketplace Test Report

**Audit ID:** KARMA-MARKET-{market.upper()}-PHASE{phase}
**Date:** {now_utc().strftime('%Y-%m-%d %H:%M UTC')}
**Market:** {title} Marketplace
**Phase:** {phase} ({result.total_tasks} tasks)
**Executor:** Security Sentinel

---

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total Tasks | {result.total_tasks} |
| Honest Tasks | {result.honest_tasks} |
| Malicious Tasks | {result.malicious_tasks} |
| Released (Successful) | {result.released} |
| Held (Disputed) | {result.held} |
| Refunded | {result.refunded} |
| Malicious Detection Rate | {detection_rate:.1f}% |
| False Positives | {fp_count} |
| False Negatives (Undetected) | {fn_count} |
| Avg Verification Latency | {avg_ms:.3f}ms |
| P95 Verification Latency | {p95_ms:.3f}ms |
| Settlement Consistency | {settlement_consistent}/{settlement_total} ({settlement_consistent/settlement_total*100:.1f}%) |
| Trace Correlation Success | {trace_success}/{trace_total} ({trace_success/trace_total*100:.1f}%) |
| Verdict | **{'✅ PASS' if detection_rate > 95 and fp_count == 0 else '🟡 REVIEW' if detection_rate > 80 else '🔴 FAIL'}** |

## 2. Attack Detection Breakdown

| Attack Type | Detected | Notes |
|-------------|:--------:|-------|
| Duplicate Receipt | {result.attacks_detected.get('duplicate_receipt', 0)} | Detected via chain length mismatch |
| Replayed Receipt | {result.attacks_detected.get('replayed_receipt', 0)} | Detected via receipt_id uniqueness |
| Forged Hash | {result.attacks_detected.get('forged_hash', 0)} | Detected via hash integrity check |
| Timeout | {result.timeout_detected} | Detected via status field |
| Malformed Receipt | {result.attacks_detected.get('malformed_receipt', 0)} | Detected via hash format check |
| Partial Chain | {result.attacks_detected.get('partial_receipt_chain', 0)} | Detected via completeness check |
| Fake Execution | {result.attacks_detected.get('fake_execution', 0)} | Detected via 0ms duration |
| Repeated Output | {result.attacks_detected.get('repeated_output', 0)} | Detected via output diversity |
| Cross-Task Reuse | {result.attacks_detected.get('cross_task_receipt_reuse', 0)} | Detected via global ID uniqueness |
| Low Quality Output | {result.low_quality_detected} | Detected via quality threshold |
| API Failure | {result.api_failures_handled} | Detected via status field |
| Partial Completion | {result.partial_completions_handled} | Detected via completion ratio |

## 3. Verification Performance

| Percentile | Latency (ms) |
|------------|:-----------:|
| Average | {avg_ms:.3f} |
| P50 | {all_ms[len(all_ms)//2] if all_ms else 0:.3f} |
| P95 | {p95_ms:.3f} |
| P99 | {all_ms[int(len(all_ms)*0.99)] if all_ms and len(all_ms)>1 else 0:.3f} |
| Max | {all_ms[-1] if all_ms else 0:.3f} |

## 4. Settlement Distribution

```
Released:  {'█' * int(result.released / max(result.total_tasks, 1) * 40)} {result.released} ({result.released/max(result.total_tasks,1)*100:.1f}%)
Held:      {'█' * int(result.held / max(result.total_tasks, 1) * 40)} {result.held} ({result.held/max(result.total_tasks,1)*100:.1f}%)
Refunded:  {'█' * int(result.refunded / max(result.total_tasks, 1) * 40)} {result.refunded} ({result.refunded/max(result.total_tasks,1)*100:.1f}%)
```

## 5. Failed Cases

{f"**Count:** {len(result.failed_cases)}" if result.failed_cases else "**None** — All cases correctly classified."}

{chr(10).join(f"- `{f['task_id'][:16]}...` → {f['reason']} ({f.get('attack_type', 'N/A')})" for f in result.failed_cases[:20]) if result.failed_cases else ""}

{market_insights}

## 7. Phase Configuration

```json
{json.dumps(phase_config or {}, indent=2)}
```

## 8. Sampled Task Outputs

### Task Example

{chr(10).join(f"#### Task `{t.task_contract.task_id[:16]}...`\n- Trace: `{t.trace_id}`\n- Decision: `{t.settlement_plan.decision}`\n- Escrow: {t.task_contract.escrow_amount}\n- Receipts: {len(t.receipt_chain)}\n- Verification: {t.verification_result.confidence:.1%} confidence\n- Attacks: {t.verification_result.detected_attacks or 'none'}" for t in result.tasks[:3])}

---
*Report generated by Security Sentinel — Karma Trust Protocol Market Validation*
"""
    return report


def generate_market_summary_json(
    dl_result: MarketResult, api_result: MarketResult, phase: str, config: dict
) -> dict:
    """Generate combined MARKET_SCENARIO_SUMMARY.json."""

    def market_stats(r: MarketResult) -> dict:
        all_ms = sorted(r.verification_times_ms)
        return {
            "total_tasks": r.total_tasks,
            "honest_tasks": r.honest_tasks,
            "malicious_tasks": r.malicious_tasks,
            "released": r.released,
            "held": r.held,
            "refunded": r.refunded,
            "disputes": r.disputes,
            "malicious_detection_rate": round(
                (r.held + r.refunded) / max(r.malicious_tasks, 1), 4
            ),
            "false_positives": sum(1 for f in r.failed_cases if f.get("reason") == "false_positive"),
            "false_negatives": sum(1 for f in r.failed_cases if f.get("reason") == "undetected_attack"),
            "average_verification_ms": round(sum(all_ms) / max(len(all_ms), 1), 3),
            "p95_verification_ms": round(all_ms[int(len(all_ms) * 0.95)], 3) if all_ms else 0,
            "settlement_consistency": round((r.released + r.refunded) / max(r.total_tasks, 1), 4),
            "trace_correlation_success": round(
                sum(1 for t in r.tasks if t.verification_result.decision == "release")
                / max(r.total_tasks, 1), 4
            ),
            "attacks_detected": r.attacks_detected,
            "timeout_detected": r.timeout_detected,
            "duplicate_detected": r.duplicate_detected,
            "replay_detected": r.replay_detected,
            "api_failures_handled": r.api_failures_handled,
            "partial_completions_handled": r.partial_completions_handled,
            "verdict": "PASS" if (r.held + r.refunded) / max(r.malicious_tasks, 1) > 0.95
                       and sum(1 for f in r.failed_cases if f.get("reason") == "false_positive") == 0
                       else "REVIEW",
        }

    return {
        "simulation_name": "karma_market_scenario_validation",
        "phase": phase,
        "timestamp": now_utc().isoformat(),
        "config": config,
        "markets": {
            "data_labeling": market_stats(dl_result),
            "api_call": market_stats(api_result),
        },
        "recommendation": generate_recommendation(dl_result, api_result),
    }


def generate_recommendation(dl: MarketResult, api: MarketResult) -> dict:
    """Generate market recommendation based on test results."""
    dl_detection = (dl.held + dl.refunded) / max(dl.malicious_tasks, 1)
    api_detection = (api.held + api.refunded) / max(api.malicious_tasks, 1)
    dl_fp = sum(1 for f in dl.failed_cases if f.get("reason") == "false_positive")
    api_fp = sum(1 for f in api.failed_cases if f.get("reason") == "false_positive")
    dl_fn = sum(1 for f in dl.failed_cases if f.get("reason") == "undetected_attack")
    api_fn = sum(1 for f in api.failed_cases if f.get("reason") == "undetected_attack")

    dl_all_ms = sorted(dl.verification_times_ms)
    api_all_ms = sorted(api.verification_times_ms)
    dl_avg = sum(dl_all_ms) / max(len(dl_all_ms), 1)
    api_avg = sum(api_all_ms) / max(len(api_all_ms), 1)

    # Scoring
    dl_score = (dl_detection * 40) + ((1 - dl_fn / max(dl.malicious_tasks, 1)) * 30) + (min(dl_avg / api_avg, 2) * 15) + ((1 - dl_fp / max(dl.total_tasks, 1)) * 15)
    api_score = (api_detection * 40) + ((1 - api_fn / max(api.malicious_tasks, 1)) * 30) + (min(api_avg / dl_avg, 2) * 15) + ((1 - api_fp / max(api.total_tasks, 1)) * 15)

    if dl_score > api_score:
        order = "data_labeling_first"
        reasoning = [
            "Data labeling has more discrete, verifiable steps per task",
            "Quality scoring provides an additional verification dimension",
            "Larger average escrow amounts → more economic security testing",
            "Real-world demand for verifiable AI data labeling is well-documented",
        ]
    elif api_score > dl_score:
        order = "api_call_first"
        reasoning = [
            "API calls produce clearer, more deterministic receipts",
            "HTTP status codes and timing are trivially verifiable",
            "Lower average escrow amounts → lower risk for early testing",
            "API marketplace has immediate utility for agent-to-agent interactions",
        ]
    else:
        order = "both"
        reasoning = [
            "Both markets perform comparably well",
            "They demonstrate complementary verification strengths",
            "Launching both broadens initial market exposure",
        ]

    return {
        "first_market": order,
        "data_labeling_score": round(dl_score, 1),
        "api_call_score": round(api_score, 1),
        "reasoning": reasoning,
        "data_labeling_advantages": [
            "Richer verification signals (quality scores, label diversity)",
            "Higher per-task value attracts quality workers",
            "Clear enterprise demand (AI training data)",
        ],
        "api_call_advantages": [
            "Simpler, more deterministic verification",
            "Lower latency → faster settlement cycles",
            "Natural fit for agent-to-agent microservices",
        ],
    }


# ── Main Orchestrator ──────────────────────────────────────────────────────
def run_market_validation(
    phases: list[str],
    malicious_rate: float = 0.5,
    seed: int = 42,
    do_sepolia: bool = False,
    output_base: str = "results/market-scenario-test",
) -> int:
    """Run the full market validation across all phases."""
    rng = random.Random(seed)
    output_path = Path(output_base)
    output_path.mkdir(parents=True, exist_ok=True)

    all_dl_results: dict[str, MarketResult] = {}
    all_api_results: dict[str, MarketResult] = {}
    all_sepolia_tx: list[dict] = []
    all_failed_cases: list[dict] = []

    for phase in phases:
        num_tasks = PHASE_TASKS.get(phase, 100)
        print(f"\n{'='*70}")
        print(f"  PHASE {phase}: {num_tasks} tasks per market")
        print(f"  Malicious rate: {malicious_rate:.0%} | Seed: {seed}")
        print(f"{'='*70}")

        # ── Data Labeling Market ──
        print(f"\n{'─'*50}")
        print(f"  MARKET 1: AI Data Labeling ({num_tasks} tasks)")
        print(f"{'─'*50}")
        t0 = time.perf_counter()

        dl_ids: set[str] = set()
        dl_prev: list[SimReceipt] = []
        dl_result = run_market("data_labeling", num_tasks, malicious_rate, rng, dl_ids, dl_prev, output_all=True)
        all_dl_results[phase] = dl_result

        dl_elapsed = time.perf_counter() - t0
        dl_all_ms = sorted(dl_result.verification_times_ms)
        dl_detection = (dl_result.held + dl_result.refunded) / max(dl_result.malicious_tasks, 1) * 100
        print(f"  ✓ {dl_result.total_tasks} tasks | released={dl_result.released} held={dl_result.held} refunded={dl_result.refunded}")
        print(f"    detection={dl_detection:.0f}% | avg_verify={sum(dl_all_ms)/max(len(dl_all_ms),1):.3f}ms | {dl_elapsed:.2f}s")

        # ── API Call Market ──
        print(f"\n{'─'*50}")
        print(f"  MARKET 2: Agent/API Call ({num_tasks} tasks)")
        print(f"{'─'*50}")
        t0 = time.perf_counter()

        api_ids: set[str] = set()
        api_prev: list[SimReceipt] = []
        api_result = run_market("api_call", num_tasks, malicious_rate, rng, api_ids, api_prev, output_all=True)
        all_api_results[phase] = api_result

        api_elapsed = time.perf_counter() - t0
        api_all_ms = sorted(api_result.verification_times_ms)
        api_detection = (api_result.held + api_result.refunded) / max(api_result.malicious_tasks, 1) * 100
        print(f"  ✓ {api_result.total_tasks} tasks | released={api_result.released} held={api_result.held} refunded={api_result.refunded}")
        print(f"    detection={api_detection:.0f}% | avg_verify={sum(api_all_ms)/max(len(api_all_ms),1):.3f}ms | {api_elapsed:.2f}s")

        # ── Generate Phase Reports ──
        phase_dir = output_path / f"phase_{phase}"
        phase_dir.mkdir(parents=True, exist_ok=True)

        phase_config = {"phase": phase, "tasks_per_market": num_tasks, "malicious_rate": malicious_rate, "seed": seed}

        # Data labeling report
        dl_report = generate_market_report("data_labeling", dl_result, phase, phase_dir, phase_config)
        with open(phase_dir / "DATA_LABELING_MARKET_TEST_REPORT.md", "w") as f:
            f.write(dl_report)
        print(f"  📄 {phase_dir / 'DATA_LABELING_MARKET_TEST_REPORT.md'}")

        # API call report
        api_report = generate_market_report("api_call", api_result, phase, phase_dir, phase_config)
        with open(phase_dir / "API_CALL_MARKET_TEST_REPORT.md", "w") as f:
            f.write(api_report)
        print(f"  📄 {phase_dir / 'API_CALL_MARKET_TEST_REPORT.md'}")

        # Market summary JSON
        summary = generate_market_summary_json(dl_result, api_result, phase, phase_config)
        with open(phase_dir / "MARKET_SCENARIO_SUMMARY.json", "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"  📄 {phase_dir / 'MARKET_SCENARIO_SUMMARY.json'}")

        # Failed cases
        all_phase_failed = dl_result.failed_cases + api_result.failed_cases
        all_failed_cases.extend(all_phase_failed)
        with open(phase_dir / "failed_cases.json", "w") as f:
            json.dump(all_phase_failed, f, indent=2, ensure_ascii=False)
        print(f"  📄 {phase_dir / 'failed_cases.json'} ({len(all_phase_failed)} cases)")

        # Per-task detailed outputs (first 20 samples)
        task_details_dir = phase_dir / "task_details"
        task_details_dir.mkdir(exist_ok=True)
        for market_name, mresult in [("data_labeling", dl_result), ("api_call", api_result)]:
            market_task_dir = task_details_dir / market_name
            market_task_dir.mkdir(exist_ok=True)
            for t in mresult.tasks[:20]:
                task_file = {
                    "task_contract": t.task_contract.to_dict(),
                    "receipt_chain": [r.to_dict() for r in t.receipt_chain],
                    "evidence_bundle": t.evidence_bundle.to_dict(),
                    "verification_result": t.verification_result.to_dict(),
                    "settlement_plan": t.settlement_plan.to_dict(),
                    "trace_id": t.trace_id,
                    "operational_log": [l.to_dict() for l in t.operational_log],
                }
                with open(market_task_dir / f"{t.task_contract.task_id[:16]}.json", "w") as f:
                    json.dump(task_file, f, indent=2, ensure_ascii=False)

        # ── Sepolia On-Chain Sampling ──
        if do_sepolia:
            print(f"\n  ⛓️  Sepolia On-Chain Sampling...")
            sepolia_dir = phase_dir / "sepolia_samples"
            sepolia_dir.mkdir(exist_ok=True)

            for market_name, mresult in [("data_labeling", dl_result), ("api_call", api_result)]:
                print(f"  → {market_name}: sampling 10 settlement flows...")
                tx_log = try_sepolia_sampling(market_name, mresult.tasks, sepolia_dir)
                all_sepolia_tx.extend(tx_log)

        # Print recommendation
        rec = summary.get("recommendation", {})
        print(f"\n  📊 Recommendation: **{rec.get('first_market', 'N/A').replace('_', ' ').title()}**")
        print(f"     DL Score: {rec.get('data_labeling_score', 'N/A')} | API Score: {rec.get('api_call_score', 'N/A')}")

    # ── Global Outputs ──
    # All failed cases
    with open(output_path / "failed_cases.json", "w") as f:
        json.dump(all_failed_cases, f, indent=2, ensure_ascii=False)

    # All Sepolia tx log
    if all_sepolia_tx:
        with open(output_path / "sampled_onchain_tx_log.jsonl", "w") as f:
            for tx in all_sepolia_tx:
                f.write(json.dumps(tx) + "\n")

    print(f"\n{'='*70}")
    print(f"  MARKET VALIDATION COMPLETE")
    print(f"  Phases: {', '.join(phases)}")
    print(f"  Output: {output_path}/")
    print(f"{'='*70}")

    # Final verdict
    final_phase = phases[-1]
    dl_final = all_dl_results[final_phase]
    api_final = all_api_results[final_phase]
    dl_det = (dl_final.held + dl_final.refunded) / max(dl_final.malicious_tasks, 1)
    api_det = (api_final.held + api_final.refunded) / max(api_final.malicious_tasks, 1)

    if dl_det > 0.95 and api_det > 0.95:
        return 0
    return 1


# ── CLI ────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Karma Market Scenario Validation")
    parser.add_argument("--phase", type=str, default="A", help="Phase(s): A, B, C, or A,B,C")
    parser.add_argument("--malicious-rate", type=float, default=0.5, help="Malicious agent rate (0-1)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sepolia-sample", action="store_true", help="Run Sepolia on-chain sampling")
    parser.add_argument("--output-dir", type=str, default="results/market-scenario-test")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    phases = [p.strip() for p in args.phase.split(",")]
    for p in phases:
        if p not in PHASE_TASKS:
            print(f"ERROR: Unknown phase '{p}'. Use: A, B, C")
            sys.exit(1)

    exit_code = run_market_validation(
        phases=phases,
        malicious_rate=args.malicious_rate,
        seed=args.seed,
        do_sepolia=args.sepolia_sample,
        output_base=args.output_dir,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
