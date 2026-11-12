"""
Console live-write smoke: exercise the same HTTP write sequence the static
console buttons call (capacity → settlement → receipt → buyer-accept).

Runs in-process via ASGI TestClient (no external uvicorn required).
For a browser check against a live API, see docs/public-testing/CONSOLE_LAST_MILE-zh.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract

from core.schemas import ExecutionReceipt, ToolStatus
from services.signing import signing_service


def _voucher_json(*, buyer: str, seller: str, amount: float, nonce: str) -> dict:
    h = "aa" * 32
    exp = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": amount,
        "bill_credit_amount": amount,
        "task_type": "console.live_write_smoke",
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": exp,
        "nonce": nonce,
        "buyer_signature": "0x" + "11" * 65,
        "currency": "USDC",
    }


def _signed_receipt(*, task_id: str, agent_id: str) -> dict:
    base = datetime.utcnow().replace(microsecond=0)
    r = ExecutionReceipt(
        task_id=task_id,
        agent_id=agent_id,
        step_index=1,
        tool_name="console.smoke.step",
        input_hash="ab" * 32,
        output_hash="cd" * 32,
        started_at=base,
        ended_at=base + timedelta(milliseconds=100),
        duration_ms=100,
        status=ToolStatus.SUCCESS,
    )
    r.signature = signing_service.sign_receipt(r)
    return r.model_dump(mode="json")


@pytest.mark.asyncio
async def test_console_live_write_happy_path(client: AsyncClient):
    """Mirrors Payments/Receiving console actions through to settled."""
    buyer, seller = "console-smoke-buyer", "console-smoke-seller"
    tid = "task-console-live-write"

    # capacity-lock
    lock = await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100.0})
    assert lock.status_code == 200, lock.text
    cap = (await client.get(f"/v1/capacity/{buyer}")).json()
    assert cap["available_credits"] == 100.0

    await post_minimal_contract(
        client, task_id=tid, client_agent_id=buyer, escrow_amount=40.0
    )

    v = await client.post(
        "/v1/vouchers",
        json=_voucher_json(buyer=buyer, seller=seller, amount=40.0, nonce="console-smoke-1"),
    )
    assert v.status_code == 201, v.text
    vid = v.json()["voucher_id"]
    acc = await client.post(
        f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller}
    )
    assert acc.status_code == 200, acc.text

    # settlement create + pending + lock (Payments)
    create = await client.post(
        "/v1/settlement/create",
        json={
            "task_id": tid,
            "client_agent_id": buyer,
            "escrow_amount": 40.0,
            "currency": "USD",
            "voucher_id": vid,
        },
    )
    assert create.status_code in (200, 201), create.text

    pending = await client.post(f"/v1/settlement/{tid}/pending", json={})
    assert pending.status_code == 200, pending.text

    locked = await client.post(
        f"/v1/settlement/{tid}/lock", json={"worker_agent_id": seller}
    )
    assert locked.status_code == 200, locked.text

    # start + submit (Receiving)
    start = await client.post(f"/v1/settlement/{tid}/start", json={})
    assert start.status_code == 200, start.text
    submit = await client.post(f"/v1/settlement/{tid}/submit", json={})
    assert submit.status_code == 200, submit.text

    rec = await client.post("/v1/receipts", json=_signed_receipt(task_id=tid, agent_id=seller))
    assert rec.status_code == 201, rec.text

    # settlement-buyer-accept
    done = await client.post(f"/v1/settlement/{tid}/buyer-accept", json={})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "settled"

    # read helpers used by Overview polling
    st = await client.get(f"/v1/settlement/{tid}")
    assert st.status_code == 200
    health = await client.get("/health")
    assert health.status_code == 200
