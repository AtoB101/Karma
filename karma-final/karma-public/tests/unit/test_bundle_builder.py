"""
Tests — Evidence Bundle Builder
"""
from datetime import datetime, timedelta

import pytest

from core.schemas import ExecutionReceipt, TaskContract, TaskStatus, ToolStatus
from core.hooks.hook_layer import InMemoryReceiptStore
from core.evidence.bundle_builder import EvidenceBundleBuilder


def _make_receipt(task_id: str, step: int, status=ToolStatus.SUCCESS) -> ExecutionReceipt:
    now = datetime.utcnow()
    return ExecutionReceipt(
        task_id=task_id,
        agent_id="worker-001",
        step_index=step,
        tool_name=f"tool.{step}",
        input_hash="a" * 64,
        output_hash="b" * 64,
        started_at=now,
        ended_at=now + timedelta(milliseconds=100),
        duration_ms=100,
        status=status,
    )


def _make_contract(task_id: str, steps: int = 3) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        client_agent_id="client-001",
        title="Test",
        description="Test",
        expected_output_schema={},
        expected_step_count=steps,
        escrow_amount=10.0,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )


@pytest.fixture
async def store_with_receipts():
    store = InMemoryReceiptStore()
    task_id = "task-bundle-001"
    for i in range(1, 4):
        await store.save(_make_receipt(task_id, i))
    return store, task_id


@pytest.mark.asyncio
async def test_bundle_contains_all_receipts(store_with_receipts):
    store, task_id = store_with_receipts
    contract = _make_contract(task_id, steps=3)
    builder = EvidenceBundleBuilder(receipt_store=store)
    bundle = await builder.build(contract, {"output": "final"})

    assert bundle.task_id == task_id
    assert bundle.total_steps == 3
    assert bundle.successful_steps == 3
    assert bundle.failed_steps == 0
    assert len(bundle.receipt_ids) == 3
    assert len(bundle.receipt_hashes) == 3


@pytest.mark.asyncio
async def test_bundle_counts_failures():
    store = InMemoryReceiptStore()
    task_id = "task-fail"
    await store.save(_make_receipt(task_id, 1, ToolStatus.SUCCESS))
    await store.save(_make_receipt(task_id, 2, ToolStatus.FAILURE))
    await store.save(_make_receipt(task_id, 3, ToolStatus.SUCCESS))

    builder = EvidenceBundleBuilder(receipt_store=store)
    bundle = await builder.build(_make_contract(task_id), {})

    assert bundle.successful_steps == 2
    assert bundle.failed_steps == 1


@pytest.mark.asyncio
async def test_bundle_has_contract_hash():
    store = InMemoryReceiptStore()
    task_id = "task-hash"
    await store.save(_make_receipt(task_id, 1))
    contract = _make_contract(task_id)
    builder = EvidenceBundleBuilder(receipt_store=store)
    bundle = await builder.build(contract, {})

    assert bundle.task_contract_hash
    assert len(bundle.task_contract_hash) == 64


@pytest.mark.asyncio
async def test_bundle_status_is_submitted():
    store = InMemoryReceiptStore()
    task_id = "task-status"
    await store.save(_make_receipt(task_id, 1))
    builder = EvidenceBundleBuilder(receipt_store=store)
    bundle = await builder.build(_make_contract(task_id), {})
    assert bundle.settlement_status == TaskStatus.SUBMITTED


@pytest.mark.asyncio
async def test_bundle_signed_by_signer():
    from core.evidence.bundle_builder import BundleSigner

    class MockSigner(BundleSigner):
        def sign_bundle(self, payload):
            return "mock-signature"

    store = InMemoryReceiptStore()
    task_id = "task-sign"
    await store.save(_make_receipt(task_id, 1))
    builder = EvidenceBundleBuilder(receipt_store=store, signer=MockSigner())
    bundle = await builder.build(_make_contract(task_id), {})
    assert bundle.agent_signature == "mock-signature"


@pytest.mark.asyncio
async def test_empty_receipts_bundle():
    store = InMemoryReceiptStore()
    builder = EvidenceBundleBuilder(receipt_store=store)
    bundle = await builder.build(_make_contract("task-empty"), {})
    assert bundle.total_steps == 0
    assert bundle.successful_steps == 0
