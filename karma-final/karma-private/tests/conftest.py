"""
Karma Private Runtime — Test Configuration & Fixtures
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from core.schemas import (
    AgentRole, EvidenceBundle, ExecutionReceipt,
    TaskContract, TaskStatus, ToolStatus,
)
from core.hooks.hook_layer import InMemoryReceiptStore
from core.reputation.in_memory_store import InMemoryPrivateReputationStore
from core.fraud.detector import FraudDetector
from core.behavior.analyzer import BehaviorAnalyzer
from core.risk.scorer import RiskScorer


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def receipt_store():
    return InMemoryReceiptStore()


@pytest.fixture
def reputation_store():
    return InMemoryPrivateReputationStore()


@pytest.fixture
def fraud_detector():
    return FraudDetector()


@pytest.fixture
def behavior_analyzer():
    return BehaviorAnalyzer()


@pytest.fixture
def risk_scorer():
    return RiskScorer()


@pytest.fixture
def sample_contract() -> TaskContract:
    return TaskContract(
        task_id="priv-test-task-001",
        client_agent_id="client-priv-001",
        worker_agent_id="worker-priv-001",
        title="Private Test Task",
        description="Testing private engine",
        expected_output_schema={"type": "object"},
        expected_step_count=5,
        escrow_amount=100.0,
        currency="USD",
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )


@pytest.fixture
def make_receipt():
    def _make(
        task_id: str,
        step: int,
        status: ToolStatus = ToolStatus.SUCCESS,
        duration_ms: int = 150,
        tool_name: str | None = None,
        output_hash: str | None = None,
    ) -> ExecutionReceipt:
        base = datetime(2025, 1, 1, 12, 0, 0) + timedelta(seconds=step * 3)
        return ExecutionReceipt(
            task_id=task_id,
            agent_id="worker-priv-001",
            step_index=step,
            tool_name=tool_name or f"tool.step{step}",
            input_hash="a" * 64,
            output_hash=output_hash or (("b" * 62) + f"{step:02d}"),
            started_at=base,
            ended_at=base + timedelta(milliseconds=duration_ms),
            duration_ms=duration_ms,
            status=status,
        )
    return _make


@pytest.fixture
def make_bundle():
    def _make(
        task_id: str,
        receipts: list[ExecutionReceipt],
        contract_hash: str = "c" * 64,
        agent_signature: str | None = None,
    ) -> EvidenceBundle:
        import hashlib, json
        successful = sum(1 for r in receipts if r.status == ToolStatus.SUCCESS)
        failed     = sum(1 for r in receipts if r.status == ToolStatus.FAILURE)

        def _hash(r):
            raw = json.dumps(r.model_dump(), sort_keys=True, separators=(",",":"), default=str)
            return hashlib.sha256(raw.encode()).hexdigest()

        return EvidenceBundle(
            task_id=task_id,
            task_contract_hash=contract_hash,
            receipt_ids=[r.receipt_id for r in receipts],
            receipt_hashes=[_hash(r) for r in receipts],
            final_result_hash="f" * 64,
            total_steps=len(receipts),
            successful_steps=successful,
            failed_steps=failed,
            total_duration_ms=sum(r.duration_ms for r in receipts),
            agent_signature=agent_signature,
        )
    return _make
