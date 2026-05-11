"""
PRIVATE Tests — Verification Engine
Tests all private checks including anti-cheat, fraud detection,
behavior scoring, and decision thresholds.

DO NOT commit to public repository.
"""
from datetime import datetime, timedelta

import pytest

from core.schemas import (
    EvidenceBundle, ExecutionReceipt, TaskContract, ToolStatus,
    VerificationDecision,
)
from core.hooks.hook_layer import InMemoryReceiptStore
from core.verification.engine import PrivateVerificationEngine

# Import fraud/behavior for combined tests
from core.fraud.detector import FraudDetector
from core.behavior.analyzer import BehaviorAnalyzer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_receipt(
    task_id: str,
    step: int,
    status=ToolStatus.SUCCESS,
    duration_ms: int = 150,
    tool_name: str | None = None,
    output_hash: str | None = None,
) -> ExecutionReceipt:
    base = datetime(2025, 1, 1, 12, 0, 0) + timedelta(seconds=step * 2)
    return ExecutionReceipt(
        task_id=task_id,
        agent_id="worker-001",
        step_index=step,
        tool_name=tool_name or f"tool.step{step}",
        input_hash="a" * 64,
        output_hash=output_hash or ("b" * 62 + f"{step:02d}"),
        started_at=base,
        ended_at=base + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        status=status,
    )


def _make_contract(task_id: str, steps: int = 5) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        client_agent_id="client-001",
        worker_agent_id="worker-001",
        title="Private Test Task",
        description="desc",
        expected_output_schema={},
        expected_step_count=steps,
        escrow_amount=100.0,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )


class MockSigner:
    def verify(self, data: bytes, sig: str) -> bool:
        return sig == "valid-sig"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return PrivateVerificationEngine(
        signing_service=MockSigner(),
        receipt_store=InMemoryReceiptStore(),
    )


async def _load_store(task_id, receipts):
    store = InMemoryReceiptStore()
    for r in receipts:
        await store.save(r)
    return store


# ---------------------------------------------------------------------------
# RELEASE scenarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_checks_pass_releases(engine):
    task_id = "t-release"
    receipts = [_make_receipt(task_id, i, duration_ms=100 + i * 30) for i in range(1, 6)]
    store = await _load_store(task_id, receipts)
    engine.receipt_store = store

    from services.signing import signing_service
    import json
    from core.evidence.bundle_builder import EvidenceBundleBuilder
    from services.signing import sha256_of

    contract = _make_contract(task_id, steps=5)
    contract.contract_hash = sha256_of(contract.model_dump(exclude={"contract_hash"}))

    builder = EvidenceBundleBuilder(receipt_store=store, signer=signing_service)
    bundle = await builder.build(contract, {"final": "output"})

    engine2 = PrivateVerificationEngine(
        signing_service=signing_service,
        receipt_store=store,
    )
    result = await engine2.verify(bundle, contract)
    assert result.decision == VerificationDecision.RELEASE


# ---------------------------------------------------------------------------
# ANTI-CHEAT: instant execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_instant_execution_triggers_refund():
    task_id = "t-instant"
    # All receipts complete in < 10ms — looks fake
    receipts = [_make_receipt(task_id, i, duration_ms=2) for i in range(1, 4)]
    store = await _load_store(task_id, receipts)

    from core.fraud.detector import FraudDetector
    fd = FraudDetector()
    contract = _make_contract(task_id)
    from core.schemas import EvidenceBundle
    bundle = EvidenceBundle(
        task_id=task_id, task_contract_hash="x" * 64,
        receipt_ids=[], receipt_hashes=[], final_result_hash="y" * 64,
        total_steps=3, successful_steps=3, failed_steps=0, total_duration_ms=6,
    )
    report = fd.detect(bundle, contract, receipts)
    assert report.is_fraudulent
    assert any(s.signal_type == "instant_execution" for s in report.signals)


# ---------------------------------------------------------------------------
# FRAUD: duplicate outputs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_output_hash_detected():
    task_id = "t-dup"
    same_hash = "c" * 64
    receipts = [_make_receipt(task_id, i, output_hash=same_hash) for i in range(1, 6)]
    store = await _load_store(task_id, receipts)

    from core.fraud.detector import FraudDetector
    from core.schemas import EvidenceBundle
    fd = FraudDetector()
    contract = _make_contract(task_id)
    bundle = EvidenceBundle(
        task_id=task_id, task_contract_hash="x" * 64,
        receipt_ids=[], receipt_hashes=[], final_result_hash="y" * 64,
        total_steps=5, successful_steps=5, failed_steps=0, total_duration_ms=500,
    )
    report = fd.detect(bundle, contract, receipts)
    assert any(s.signal_type == "duplicate_output_hash" for s in report.signals)


# ---------------------------------------------------------------------------
# FRAUD: self-dealing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_self_dealing_detected():
    from core.schemas import TaskContract, EvidenceBundle
    from core.fraud.detector import FraudDetector
    from datetime import datetime, timedelta

    contract = TaskContract(
        client_agent_id="same-agent",
        worker_agent_id="same-agent",   # same!
        title="t", description="d",
        expected_output_schema={},
        expected_step_count=1,
        escrow_amount=10.0,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )
    bundle = EvidenceBundle(
        task_id=contract.task_id, task_contract_hash="x" * 64,
        receipt_ids=[], receipt_hashes=[], final_result_hash="y" * 64,
        total_steps=0, successful_steps=0, failed_steps=0, total_duration_ms=0,
    )
    report = FraudDetector().detect(bundle, contract, [])
    assert report.is_fraudulent
    assert any(s.signal_type == "self_dealing" for s in report.signals)


# ---------------------------------------------------------------------------
# BEHAVIOR: bot detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_uniform_timing_flagged_as_bot():
    task_id = "t-bot"
    # Exactly 100ms every step — robotic
    receipts = [_make_receipt(task_id, i, duration_ms=100) for i in range(1, 10)]
    ba = BehaviorAnalyzer()
    profile = ba.analyze(task_id, "worker-bot", receipts)
    # Uniform timing = low behavior score
    assert profile.timing_variance_cv < 0.05


# ---------------------------------------------------------------------------
# REPUTATION: score delta table
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_task_increases_score():
    from core.reputation.system import PrivateReputationSystem
    from core.reputation.in_memory_store import InMemoryPrivateReputationStore
    from core.schemas import AgentRole, TaskStatus

    store = InMemoryPrivateReputationStore()
    system = PrivateReputationSystem(store)
    snap1 = await system.update("agent-rep", AgentRole.WORKER, TaskStatus.RELEASED, verification_confidence=0.98)
    snap2 = await system.update("agent-rep", AgentRole.WORKER, TaskStatus.RELEASED, verification_confidence=0.98)
    assert snap2.score > snap1.score


@pytest.mark.asyncio
async def test_failed_task_decreases_score():
    from core.reputation.system import PrivateReputationSystem
    from core.reputation.in_memory_store import InMemoryPrivateReputationStore
    from core.schemas import AgentRole, TaskStatus

    store = InMemoryPrivateReputationStore()
    system = PrivateReputationSystem(store)
    snap1 = await system.update("agent-fail", AgentRole.WORKER, TaskStatus.RELEASED)
    snap2 = await system.update("agent-fail", AgentRole.WORKER, TaskStatus.FAILED)
    assert snap2.score < snap1.score


@pytest.mark.asyncio
async def test_wash_trade_zeroes_score():
    from core.reputation.system import PrivateReputationSystem
    from core.reputation.in_memory_store import InMemoryPrivateReputationStore
    from core.schemas import AgentRole, TaskStatus

    store = InMemoryPrivateReputationStore()
    system = PrivateReputationSystem(store)
    await system.update("wash-agent", AgentRole.WORKER, TaskStatus.RELEASED)
    snap = await system.update("wash-agent", AgentRole.WORKER, TaskStatus.RELEASED, is_wash_trade=True)
    assert snap.score == 0.0
