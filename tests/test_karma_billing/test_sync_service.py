"""Tests for ReceiptSyncService — three-route fanout pipeline."""

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from packages.karma_billing.schema import (
    UniversalReceipt,
    ScenarioType,
    ReceiptType,
    ReceiptStatus,
    compute_payload_hash,
)
from packages.karma_billing.sync_service import (
    ReceiptSyncService,
    InMemoryPubSub,
    IncrementalMerkleAccumulator,
    SyncRouteStatus,
)


def make_test_receipt(task_id: str = "task-test", step: int = 0,
                      scenario: ScenarioType = ScenarioType.S1_DELEGATION,
                      receipt_id: str | None = None) -> UniversalReceipt:
    """Create a test receipt."""
    return UniversalReceipt(
        receipt_id=receipt_id or str(uuid.uuid4()),
        task_id=task_id,
        scenario=scenario,
        step_index=step,
        generator_did="did:karma:generator",
        buyer_did="did:karma:buyer",
        seller_did="did:karma:seller",
        receipt_type=ReceiptType.S1_INTENT_CREATED,
        input_hash=hashlib.sha256(b"test-input").hexdigest(),
        output_hash=hashlib.sha256(b"test-output").hexdigest(),
        scenario_data={"note": "test sync"},
        created_at=datetime.now(timezone.utc),
    )


# ── InMemoryPubSub Tests ──────────────────────────────────────────────────────


def test_pubsub_subscribe_and_publish():
    """Messages are delivered to subscribers."""
    pubsub = InMemoryPubSub()
    received: list[dict] = []

    def callback(msg: dict) -> None:
        received.append(msg)

    pubsub.subscribe("test-channel", callback)
    pubsub.publish("test-channel", {"event": "test", "data": 42})

    assert len(received) == 1
    assert received[0]["data"] == 42


def test_pubsub_multiple_subscribers():
    """Multiple subscribers on same channel all receive messages."""
    pubsub = InMemoryPubSub()
    received_a: list[dict] = []
    received_b: list[dict] = []

    pubsub.subscribe("ch", lambda m: received_a.append(m))
    pubsub.subscribe("ch", lambda m: received_b.append(m))
    pubsub.publish("ch", {"x": 1})

    assert len(received_a) == 1
    assert len(received_b) == 1


def test_pubsub_unsubscribe():
    """Unsubscribed callbacks stop receiving."""
    pubsub = InMemoryPubSub()
    received: list[dict] = []

    def cb(msg: dict) -> None:
        received.append(msg)

    pubsub.subscribe("ch", cb)
    pubsub.unsubscribe("ch", cb)
    pubsub.publish("ch", {"x": 1})

    assert len(received) == 0


def test_pubsub_no_subscribers_no_error():
    """Publishing to a channel with no subscribers doesn't raise."""
    pubsub = InMemoryPubSub()
    pubsub.publish("empty", {"x": 1})  # Should not raise


def test_pubsub_subscriber_count():
    """Subscriber count is tracked correctly."""
    pubsub = InMemoryPubSub()
    assert pubsub.subscriber_count.get("ch", 0) == 0

    pubsub.subscribe("ch", lambda m: None)
    assert pubsub.subscriber_count["ch"] == 1


# ── IncrementalMerkleAccumulator Tests ────────────────────────────────────────


def test_merkle_empty_root_is_none():
    """Empty tree has no root."""
    m = IncrementalMerkleAccumulator()
    assert m.compute_root() is None


def test_merkle_single_leaf():
    """Single leaf root equals leaf hash."""
    m = IncrementalMerkleAccumulator()
    leaf = hashlib.sha256(b"leaf1").digest()
    m.append(leaf)
    root = m.compute_root()
    assert root is not None
    assert root == leaf.hex()


def test_merkle_two_leaves():
    """Two-leaf Merkle tree works."""
    m = IncrementalMerkleAccumulator()
    leaf1 = hashlib.sha256(b"a").digest()
    leaf2 = hashlib.sha256(b"b").digest()
    m.append(leaf1)
    m.append(leaf2)
    root = m.compute_root()
    expected = hashlib.sha256(leaf1 + leaf2).hexdigest()
    assert root == expected


def test_merkle_three_leaves():
    """Three-leaf tree: (0+1) paired, then paired with (2+2) — last element duplicated."""
    m = IncrementalMerkleAccumulator()
    l0 = hashlib.sha256(b"0").digest()
    l1 = hashlib.sha256(b"1").digest()
    l2 = hashlib.sha256(b"2").digest()
    m.append(l0)
    m.append(l1)
    m.append(l2)

    node01 = hashlib.sha256(l0 + l1).digest()
    node22 = hashlib.sha256(l2 + l2).digest()  # last element duplicated (Bitcoin-style)
    expected = hashlib.sha256(node01 + node22).hexdigest()
    assert m.compute_root() == expected


def test_merkle_leaf_count():
    """Leaf count tracks correctly."""
    m = IncrementalMerkleAccumulator()
    assert m.leaf_count == 0
    m.append(hashlib.sha256(b"x").digest())
    assert m.leaf_count == 1


def test_merkle_mark_anchored():
    """Mark anchored increments counter and returns root."""
    m = IncrementalMerkleAccumulator()
    m.append(hashlib.sha256(b"x").digest())
    assert m.anchor_count == 0
    root = m.mark_anchored()
    assert root is not None
    assert m.anchor_count == 1


# ── ReceiptSyncService Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_service_basic():
    """Receipt flows through all three routes."""
    svc = ReceiptSyncService()
    receipt = make_test_receipt(task_id="task-sync-1")

    result = await svc.sync(receipt)

    assert result.receipt_id == receipt.receipt_id
    # PG is skipped (no hook), pubsub succeeds, merkle succeeds
    assert result.pg_status == SyncRouteStatus.SKIPPED
    assert result.pubsub_status == SyncRouteStatus.SUCCESS
    assert result.merkle_status == SyncRouteStatus.SUCCESS
    assert result.all_succeeded is True


@pytest.mark.asyncio
async def test_sync_service_pubsub_receives_messages():
    """Subscribed callbacks receive receipt messages."""
    pubsub = InMemoryPubSub()
    received: list[dict] = []

    pubsub.subscribe(
        "karma:billing:receipts:task-pubsub",
        lambda m: received.append(m),
    )

    svc = ReceiptSyncService(pubsub=pubsub)
    receipt = make_test_receipt(task_id="task-pubsub")

    await svc.sync(receipt)

    assert len(received) == 1
    assert received[0]["receipt_id"] == receipt.receipt_id


@pytest.mark.asyncio
async def test_sync_service_merkle_accumulates():
    """Merkle accumulator grows with each receipt."""
    svc = ReceiptSyncService()
    assert svc.merkle.leaf_count == 0

    r1 = make_test_receipt(task_id="task-merk")
    r2 = make_test_receipt(task_id="task-merk", step=1)

    await svc.sync(r1)
    assert svc.merkle.leaf_count == 1

    await svc.sync(r2)
    assert svc.merkle.leaf_count == 2

    root = svc.get_merkle_root()
    assert root is not None


@pytest.mark.asyncio
async def test_sync_service_pg_hook_called():
    """PostgreSQL insert hook is invoked."""
    hook_calls: list[UniversalReceipt] = []

    async def pg_hook(receipt: UniversalReceipt) -> None:
        hook_calls.append(receipt)

    svc = ReceiptSyncService()
    svc.set_pg_insert_hook(pg_hook)

    receipt = make_test_receipt()
    await svc.sync(receipt)

    assert len(hook_calls) == 1
    assert hook_calls[0].receipt_id == receipt.receipt_id


@pytest.mark.asyncio
async def test_sync_service_pg_hook_error_does_not_block_others():
    """PG hook failure is isolated — pubsub and merkle still succeed."""
    async def failing_hook(receipt: UniversalReceipt) -> None:
        raise RuntimeError("Simulated DB error")

    svc = ReceiptSyncService()
    svc.set_pg_insert_hook(failing_hook)

    receipt = make_test_receipt()
    result = await svc.sync(receipt)

    assert result.pg_status == SyncRouteStatus.FAILED
    assert "Simulated DB error" in str(result.errors)
    # Other routes still succeed
    assert result.pubsub_status == SyncRouteStatus.SUCCESS
    assert result.merkle_status == SyncRouteStatus.SUCCESS
    assert result.all_succeeded is False


@pytest.mark.asyncio
async def test_sync_service_anchoring_threshold():
    """Anchoring triggers when receipt count reaches threshold."""
    svc = ReceiptSyncService(anchoring_threshold=3)

    for i in range(3):
        r = make_test_receipt(task_id="task-anchor", step=i)
        result = await svc.sync(r)
        if i < 2:
            assert result.anchoring_triggered is False
        else:
            assert result.anchoring_triggered is True


@pytest.mark.asyncio
async def test_multiple_tasks_independent():
    """Receipts from different tasks are tracked independently."""
    svc = ReceiptSyncService(anchoring_threshold=5)

    for i in range(5):
        await svc.sync(make_test_receipt(task_id="task-a", step=i))

    result = await svc.sync(make_test_receipt(task_id="task-b", step=0))
    # task-b only has 1 receipt, should not trigger anchoring
    assert result.anchoring_triggered is False
