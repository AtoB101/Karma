"""E2E-style integration: runtime safety mode + dispute + arbitration + capacity release."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract, post_success_execution_receipt


def _voucher_body(*, buyer: str, seller: str, amount: float, nonce: str) -> dict:
    h = "aa" * 32
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": amount,
        "bill_credit_amount": amount,
        "task_type": "e2e.safety.dispute",
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
        "nonce": nonce,
        "buyer_signature": "0x" + "11" * 65,
        "currency": "USDC",
    }


async def _reset_safety(client_sec: AsyncClient) -> None:
    await client_sec.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": False, "reason": "test cleanup", "actor_id": "e2e-suite"},
    )


@pytest.mark.asyncio
async def test_safety_mode_blocks_new_business_allows_dispute_arbitration_and_unused_release(
    client: AsyncClient,
    client_sec: AsyncClient,
):
    await _reset_safety(client_sec)
    try:
        buyer, seller = "e2e-sm-buyer", "e2e-sm-seller"
        tid = "task-e2e-safety-001"
        tid2 = "task-e2e-safety-002"

        await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100.0})
        await post_minimal_contract(client, task_id=tid, client_agent_id=buyer, escrow_amount=50.0, expected_step_count=3)
        v = await client.post("/v1/vouchers", json=_voucher_body(buyer=buyer, seller=seller, amount=50.0, nonce="e2e-sm-n1"))
        assert v.status_code == 201, v.text
        vid = v.json()["voucher_id"]
        await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})

        await client.post(
            "/v1/settlement/create",
            json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 50.0, "currency": "USD", "voucher_id": vid},
        )
        await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": seller})
        await client.post(f"/v1/settlement/{tid}/start", json={})
        await client.post(f"/v1/settlement/{tid}/submit", json={})
        await post_success_execution_receipt(client, task_id=tid, agent_id=seller)

        await post_minimal_contract(client, task_id=tid2, client_agent_id=buyer, escrow_amount=10.0, expected_step_count=1)

        on = await client_sec.post(
            "/v1/security/runtime/safety-mode",
            json={"enabled": True, "reason": "e2e drill", "actor_id": "e2e-suite"},
        )
        assert on.status_code == 200
        assert on.json()["enabled"] is True

        blocked_lock = await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 1.0})
        assert blocked_lock.status_code == 503
        assert "safety mode" in blocked_lock.json()["detail"].lower()

        blocked_v = await client.post(
            "/v1/vouchers",
            json=_voucher_body(buyer=buyer, seller=seller, amount=5.0, nonce="e2e-sm-n2"),
        )
        assert blocked_v.status_code == 503

        blocked_settle = await client.post(
            "/v1/settlement/create",
            json={"task_id": tid2, "client_agent_id": buyer, "escrow_amount": 10.0, "currency": "USD"},
        )
        assert blocked_settle.status_code == 503

        d = await client.post(f"/v1/settlement/{tid}/dispute", json={"reason": "e2e dispute under safety"})
        assert d.status_code == 200
        assert d.json()["status"] == "disputed"

        bad_accept = await client.post(f"/v1/settlement/{tid}/buyer-accept", json={})
        assert bad_accept.status_code == 409
        assert "delivered" in bad_accept.json()["detail"].lower()

        arb = await client.post(f"/v1/settlement/{tid}/auto-arbitrate", json={})
        assert arb.status_code == 200
        assert arb.json()["status"] in ("refunded", "settled")

        cap = (await client.get(f"/v1/capacity/{buyer}")).json()
        avail = float(cap.get("available_credits", 0.0))
        if avail > 1e-3:
            rel_amt = min(5.0, avail)
            rel = await client.post(f"/v1/capacity/{buyer}/release", json={"amount": rel_amt})
            assert rel.status_code == 200, rel.text
    finally:
        await _reset_safety(client_sec)
