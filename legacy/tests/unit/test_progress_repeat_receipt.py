"""Regression: a multi-milestone task reports progress more than once.

The second receipt used to be rejected with
``409 invalid status transition: progress_submitted -> progress_submitted``,
because ``VALID_TRANSITIONS`` had no self-edge for that status - even though
the route is built for a stream of receipts (it rejects progress / claimed
rollbacks and duplicate evidence hashes, which only makes sense if more than
one receipt is expected).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract


def _progress(task_id: str, seller: str, *, percent: float, tag: str) -> dict:
    return {
        "task_id": task_id,
        "seller_identity_id": seller,
        "progress_percent": percent,
        "claimed_value_percent": percent,
        "evidence_hash": (tag + "0" * 64)[:64],
        "runtime_log_hash": (tag + "1" * 64)[:64],
        "seller_signature": "sig-" + tag,
        "validation_method": "seller_attested",
    }


async def _task_in_progress(client: AsyncClient, *, task_id: str, buyer: str, seller: str) -> None:
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100})
    await post_minimal_contract(
        client, task_id=task_id, client_agent_id=buyer, escrow_amount=10.0, expected_step_count=2
    )
    await client.post(
        "/v1/settlement/create",
        json={
            "task_id": task_id,
            "client_agent_id": buyer,
            "escrow_amount": 10.0,
            "currency": "USD",
        },
    )
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})


@pytest.mark.asyncio
async def test_second_progress_receipt_is_accepted(client: AsyncClient):
    task_id = "task-progress-repeat"
    buyer = "buyer-progress-repeat"
    seller = "seller-progress-repeat"
    await _task_in_progress(client, task_id=task_id, buyer=buyer, seller=seller)

    first = await client.post(
        "/v1/progress", json=_progress(task_id, seller, percent=30, tag="a")
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/v1/progress", json=_progress(task_id, seller, percent=100, tag="b")
    )
    assert second.status_code == 201, second.text

    rows = await client.get(f"/v1/progress/task/{task_id}")
    assert rows.status_code == 200, rows.text
    assert len(rows.json()) == 2

    state = await client.get(f"/v1/settlement/{task_id}")
    assert state.json()["status"] == "progress_submitted"


@pytest.mark.asyncio
async def test_progress_rollback_is_still_rejected(client: AsyncClient):
    task_id = "task-progress-rollback"
    buyer = "buyer-progress-rollback"
    seller = "seller-progress-rollback"
    await _task_in_progress(client, task_id=task_id, buyer=buyer, seller=seller)

    first = await client.post(
        "/v1/progress", json=_progress(task_id, seller, percent=80, tag="c")
    )
    assert first.status_code == 201, first.text

    back = await client.post(
        "/v1/progress", json=_progress(task_id, seller, percent=40, tag="d")
    )
    assert back.status_code == 409
    assert "rollback" in back.json()["detail"]


def test_state_machine_keeps_progress_submitted_self_edge():
    from core.schemas import TaskStatus
    from core.settlement.engine import can_transition

    assert can_transition(TaskStatus.PROGRESS_SUBMITTED, TaskStatus.PROGRESS_SUBMITTED)
    assert can_transition(TaskStatus.IN_PROGRESS, TaskStatus.PROGRESS_SUBMITTED)
    # A confirmed milestone still cannot silently fall back to "submitted".
    assert not can_transition(TaskStatus.PROGRESS_CONFIRMED, TaskStatus.PROGRESS_SUBMITTED)

