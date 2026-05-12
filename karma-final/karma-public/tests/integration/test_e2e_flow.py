"""
Karma — End-to-End LangGraph Integration Test
Full task lifecycle: contract → hook → execute → bundle → mock-verify → settle
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from core.schemas import AgentRole, TaskContract, TaskStatus, VerificationDecision
from core.hooks.hook_layer import InMemoryReceiptStore, KarmaHookLayer
from core.evidence.bundle_builder import EvidenceBundleBuilder
from core.verification.engine import MockVerificationEngine
from core.settlement.engine import InMemorySettlementStore, SettlementEngine
from core.settlement.engine import SettlementStore
from agents.runtime.adapter import KarmaRuntimeAgent
from agents.langgraph.workflow import KarmaTaskState, build_karma_graph


# ---------------------------------------------------------------------------
# Mock settlement engine backed by InMemorySettlementStore
# ---------------------------------------------------------------------------

class SimpleSettlementEngine(SettlementEngine):
    def __init__(self):
        self._store = InMemorySettlementStore()

    async def create(self, task_id, client_agent_id, escrow_amount, currency="USD"):
        from core.schemas import SettlementState
        state = SettlementState(
            task_id=task_id,
            escrow_amount=escrow_amount,
            currency=currency,
            client_agent_id=client_agent_id,
            status=TaskStatus.CREATED,
        )
        await self._store.save(state)
        return state

    async def lock(self, task_id, worker_agent_id):
        s = await self._store.get(task_id)
        s.status = TaskStatus.LOCKED
        s.worker_agent_id = worker_agent_id
        await self._store.save(s)
        return s

    async def start(self, task_id):
        s = await self._store.get(task_id)
        s.status = TaskStatus.RUNNING
        await self._store.save(s)
        return s

    async def submit(self, task_id):
        s = await self._store.get(task_id)
        s.status = TaskStatus.SUBMITTED
        await self._store.save(s)
        return s

    async def apply_verification(self, task_id, result):
        s = await self._store.get(task_id)
        if result.decision == VerificationDecision.RELEASE:
            s.status = TaskStatus.RELEASED
            s.released_amount = s.escrow_amount
            s.released_at = datetime.utcnow()
        elif result.decision == VerificationDecision.REFUND:
            s.status = TaskStatus.REFUNDED
            s.refunded_amount = s.escrow_amount
        else:
            s.status = TaskStatus.DISPUTED
        await self._store.save(s)
        return s

    async def fail(self, task_id):
        s = await self._store.get(task_id)
        s.status = TaskStatus.REFUNDED
        s.refunded_amount = s.escrow_amount
        await self._store.save(s)
        return s

    async def get(self, task_id):
        return await self._store.get(task_id)


# ---------------------------------------------------------------------------
# Mock tools
# ---------------------------------------------------------------------------

async def mock_caption_tool(data: dict) -> dict:
    await asyncio.sleep(0.01)
    return {"caption": f"Caption for {data.get('url', 'image')}", "confidence": 0.95}


async def mock_qc_tool(data: dict) -> dict:
    await asyncio.sleep(0.005)
    return {"passed": True, "score": 0.97}


# ---------------------------------------------------------------------------
# Task runner
# ---------------------------------------------------------------------------

async def caption_e2e_runner(contract: TaskContract, agent: KarmaRuntimeAgent):
    results = []
    for i in range(1, 4):
        caption, _ = await agent.run_tool(
            task_id=contract.task_id,
            tool_name="caption.generate",
            tool_fn=mock_caption_tool,
            input_data={"url": f"https://cdn.example.com/{i}.jpg"},
        )
        qc, _ = await agent.run_tool(
            task_id=contract.task_id,
            tool_name="caption.qc",
            tool_fn=mock_qc_tool,
            input_data={"caption": caption["caption"]},
        )
        results.append({**caption, "qc": qc})
    return {"results": results, "count": len(results)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_langgraph_task_flow():
    """
    Full end-to-end: contract → lock → execute → bundle → verify → release
    """
    receipt_store   = InMemoryReceiptStore()
    hooks           = KarmaHookLayer(agent_id="worker-lg-001", receipt_store=receipt_store)
    agent           = KarmaRuntimeAgent(agent_id="worker-lg-001", hook_layer=hooks)
    builder         = EvidenceBundleBuilder(receipt_store=receipt_store)
    verifier        = MockVerificationEngine()
    settler         = SimpleSettlementEngine()

    contract = TaskContract(
        task_id="task-lg-e2e-001",
        client_agent_id="client-lg-001",
        worker_agent_id="worker-lg-001",
        title="E2E Caption Task",
        description="Caption 3 images",
        expected_output_schema={},
        expected_step_count=6,
        escrow_amount=30.0,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )

    graph = build_karma_graph(settler, verifier, builder, agent, caption_e2e_runner)

    initial_state: KarmaTaskState = {
        "task_id":             contract.task_id,
        "agent_id":            "worker-lg-001",
        "task_contract":       contract,
        "settlement":          None,
        "evidence_bundle":     None,
        "verification_result": None,
        "final_result":        None,
        "error":               None,
        "completed_at":        None,
    }

    final_state = await graph.ainvoke(initial_state)

    # Assertions
    assert final_state["error"] is None
    assert final_state["completed_at"] is not None
    assert final_state["settlement"] is not None
    assert final_state["settlement"].status == TaskStatus.RELEASED
    assert final_state["settlement"].released_amount == 30.0
    assert final_state["evidence_bundle"] is not None
    assert final_state["evidence_bundle"].total_steps == 6   # 3 images × 2 tools
    assert final_state["verification_result"] is not None
    assert final_state["verification_result"].decision == VerificationDecision.RELEASE

    # Check receipts persisted
    receipts = await receipt_store.list_by_task(contract.task_id)
    assert len(receipts) == 6
    assert all(r.task_id == contract.task_id for r in receipts)


@pytest.mark.asyncio
async def test_langgraph_handles_tool_failure():
    """
    Task execution failure routes to handle_failure node and refunds.
    """
    receipt_store = InMemoryReceiptStore()
    hooks         = KarmaHookLayer(agent_id="worker-fail-001", receipt_store=receipt_store)
    agent         = KarmaRuntimeAgent(agent_id="worker-fail-001", hook_layer=hooks)
    builder       = EvidenceBundleBuilder(receipt_store=receipt_store)
    verifier      = MockVerificationEngine()
    settler       = SimpleSettlementEngine()

    contract = TaskContract(
        task_id="task-lg-fail-001",
        client_agent_id="client-001",
        worker_agent_id="worker-fail-001",
        title="Failing Task",
        description="Will fail",
        expected_output_schema={},
        expected_step_count=3,
        escrow_amount=10.0,
        deadline_at=datetime.utcnow() + timedelta(minutes=5),
    )

    async def failing_runner(c, a):
        raise RuntimeError("Simulated execution failure")

    graph = build_karma_graph(settler, verifier, builder, agent, failing_runner)

    final_state = await graph.ainvoke({
        "task_id":       contract.task_id,
        "agent_id":      "worker-fail-001",
        "task_contract": contract,
        "settlement":    None, "evidence_bundle": None,
        "verification_result": None, "final_result": None,
        "error": None, "completed_at": None,
    })

    assert final_state["error"] is not None
    assert final_state["settlement"].status == TaskStatus.REFUNDED


@pytest.mark.asyncio
async def test_receipt_hashes_deterministic(sample_contract, receipt_store):
    """
    Same input always produces the same input_hash.
    """
    hooks = KarmaHookLayer(agent_id="worker-hash-001", receipt_store=receipt_store)
    input_data = {"image_url": "https://example.com/img.jpg"}

    _, r1 = await hooks.run_tool(sample_contract.task_id, "tool", mock_caption_tool, input_data)
    hooks.reset_task(sample_contract.task_id)
    _, r2 = await hooks.run_tool(sample_contract.task_id, "tool", mock_caption_tool, input_data)

    assert r1.input_hash == r2.input_hash
