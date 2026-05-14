"""P0 acceptance tests — engineering kickoff §5.4 (minimal responsibility loop)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract

from core.schemas import ExecutionReceipt, ToolStatus
from services.signing import signing_service


def _voucher_json(
    *,
    buyer: str,
    seller: str,
    amount: float = 50.0,
    nonce: str = "n-p0-1",
    buyer_signature: str = "0x" + "11" * 65,
) -> dict:
    h = "aa" * 32
    exp = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": amount,
        "bill_credit_amount": amount,
        "task_type": "p0.acceptance",
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": exp,
        "nonce": nonce,
        "buyer_signature": buyer_signature,
        "currency": "USDC",
    }


def _signed_receipt_dict(
    *,
    task_id: str,
    agent_id: str,
    step_index: int = 1,
) -> dict:
    base = datetime.utcnow().replace(microsecond=0)
    r = ExecutionReceipt(
        task_id=task_id,
        agent_id=agent_id,
        step_index=step_index,
        tool_name="p0.step",
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
async def test_p0_voucher_accept_moves_capacity(client: AsyncClient):
    buyer, seller = "p0-buyer-cap", "p0-seller-cap"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100.0})
    cap0 = (await client.get(f"/v1/capacity/{buyer}")).json()
    assert cap0["available_credits"] == 100.0
    assert cap0["reserved_credits"] == 0.0

    v = await client.post("/v1/vouchers", json=_voucher_json(buyer=buyer, seller=seller, amount=40.0, nonce="nonce-a"))
    assert v.status_code == 201, v.text
    vid = v.json()["voucher_id"]

    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})

    cap1 = (await client.get(f"/v1/capacity/{buyer}")).json()
    assert cap1["available_credits"] == 60.0
    assert cap1["reserved_credits"] == 40.0


@pytest.mark.asyncio
async def test_p0_voucher_double_accept_rejected(client: AsyncClient):
    buyer, seller = "p0-buyer-dup", "p0-seller-dup"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 50.0})
    v = await client.post("/v1/vouchers", json=_voucher_json(buyer=buyer, seller=seller, amount=20.0, nonce="nonce-dup"))
    vid = v.json()["voucher_id"]
    r1 = await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    assert r1.status_code == 200
    r2 = await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_p0_buyer_accept_requires_success_receipt(client: AsyncClient):
    buyer, seller = "p0-buyer-bacc", "p0-seller-bacc"
    tid = "task-p0-bacc"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 80.0})
    await post_minimal_contract(
        client,
        task_id=tid,
        client_agent_id=buyer,
        escrow_amount=30.0,
        expected_step_count=5,
    )
    v = await client.post("/v1/vouchers", json=_voucher_json(buyer=buyer, seller=seller, amount=30.0, nonce="nonce-bacc"))
    vid = v.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})

    await client.post(
        "/v1/settlement/create",
        json={
            "task_id": tid,
            "client_agent_id": buyer,
            "escrow_amount": 30.0,
            "currency": "USD",
            "voucher_id": vid,
        },
    )
    await client.post(f"/v1/settlement/{tid}/pending", json={})
    await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{tid}/start", json={})
    await client.post(f"/v1/settlement/{tid}/submit", json={})

    bad = await client.post(f"/v1/settlement/{tid}/buyer-accept", json={})
    assert bad.status_code == 409
    assert "receipt" in bad.json()["detail"].lower()

    good_rec = await client.post("/v1/receipts", json=_signed_receipt_dict(task_id=tid, agent_id=seller))
    assert good_rec.status_code == 201, good_rec.text

    ok = await client.post(f"/v1/settlement/{tid}/buyer-accept", json={})
    assert ok.status_code == 200
    assert ok.json()["status"] == "settled"


@pytest.mark.asyncio
async def test_p0_dispute_moves_reserved_to_disputed(client: AsyncClient):
    buyer, seller = "p0-buyer-disp", "p0-seller-disp"
    tid = "task-p0-disp"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100.0})
    await post_minimal_contract(
        client,
        task_id=tid,
        client_agent_id=buyer,
        escrow_amount=35.0,
        expected_step_count=5,
    )
    v = await client.post("/v1/vouchers", json=_voucher_json(buyer=buyer, seller=seller, amount=35.0, nonce="nonce-disp"))
    vid = v.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})

    await client.post(
        "/v1/settlement/create",
        json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 35.0, "voucher_id": vid},
    )
    await client.post(f"/v1/settlement/{tid}/pending", json={})
    await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{tid}/start", json={})
    await client.post(f"/v1/settlement/{tid}/submit", json={})

    cap_before = (await client.get(f"/v1/capacity/{buyer}")).json()
    assert cap_before["reserved_credits"] >= 35.0
    assert cap_before["disputed_credits"] == 0.0

    d = await client.post(f"/v1/settlement/{tid}/dispute", json={"reason": "p0 test"})
    assert d.status_code == 200

    cap_after = (await client.get(f"/v1/capacity/{buyer}")).json()
    assert cap_after["disputed_credits"] >= 35.0 - 1e-6


@pytest.mark.asyncio
async def test_p0_settlement_records_burn_on_buyer_accept(client: AsyncClient):
    buyer, seller = "p0-buyer-burn", "p0-seller-burn"
    tid = "task-p0-burn"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 60.0})
    await post_minimal_contract(
        client,
        task_id=tid,
        client_agent_id=buyer,
        escrow_amount=25.0,
        expected_step_count=5,
    )
    v = await client.post("/v1/vouchers", json=_voucher_json(buyer=buyer, seller=seller, amount=25.0, nonce="nonce-burn"))
    vid = v.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})

    await client.post(
        "/v1/settlement/create",
        json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 25.0, "voucher_id": vid},
    )
    await client.post(f"/v1/settlement/{tid}/pending", json={})
    await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{tid}/start", json={})
    await client.post(f"/v1/settlement/{tid}/submit", json={})
    await client.post("/v1/receipts", json=_signed_receipt_dict(task_id=tid, agent_id=seller))

    cap0 = (await client.get(f"/v1/capacity/{buyer}")).json()
    burned0 = cap0["burned_credits"]

    await client.post(f"/v1/settlement/{tid}/buyer-accept", json={})

    cap1 = (await client.get(f"/v1/capacity/{buyer}")).json()
    assert cap1["burned_credits"] >= burned0 + 25.0 - 1e-6


@pytest.mark.asyncio
async def test_p0_global_capacity_anchor_not_breached(client: AsyncClient):
    await client.post("/v1/capacity/p0-anchor-a/lock", json={"amount": 10.0})
    await client.post("/v1/capacity/p0-anchor-b/lock", json={"amount": 20.0})
    r = await client.post("/v1/capacity/p0-anchor-a/lock", json={"amount": 5.0})
    assert r.status_code == 200
    body = r.json()
    assert body["total_bill_credits"] <= body["total_locked_usdc"] + 1e-9


@pytest.mark.asyncio
async def test_p0_voucher_eip712_enforced_on_create(client: AsyncClient):
    import api.routes.vouchers as voucher_routes

    acct = __import__("eth_account").Account.create()
    buyer, seller = "p0-buyer-eip", "p0-seller-eip"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 50.0})

    orig = voucher_routes.settings
    voucher_routes.settings = orig.model_copy(update={"voucher_require_eip712": True, "testnet_chain_id": 31337})
    try:
        h = "ff" * 32
        exp = datetime.utcnow() + timedelta(hours=3)
        from services.voucher_eip712 import sign_authorization_voucher

        sig = sign_authorization_voucher(
            private_key=acct.key,
            buyer_identity_id=buyer,
            seller_identity_id=seller,
            amount=15.0,
            bill_credit_amount=15.0,
            currency="USDC",
            task_type="p0",
            task_description_hash=h,
            progress_rule_hash=h,
            evidence_requirement_hash=h,
            nonce="eip-nonce-1",
            expiry_time=exp,
            chain_id=31337,
        )

        bad = await client.post(
            "/v1/vouchers",
            json={
                "buyer_identity_id": buyer,
                "seller_identity_id": seller,
                "amount": 15.0,
                "bill_credit_amount": 15.0,
                "task_type": "p0",
                "task_description_hash": h,
                "progress_rule_hash": h,
                "evidence_requirement_hash": h,
                "expiry_time": exp.isoformat(),
                "nonce": "eip-nonce-1",
                "buyer_signature": sig,
                "currency": "USDC",
            },
        )
        assert bad.status_code == 400

        ok = await client.post(
            "/v1/vouchers",
            json={
                "buyer_identity_id": buyer,
                "seller_identity_id": seller,
                "amount": 15.0,
                "bill_credit_amount": 15.0,
                "task_type": "p0",
                "task_description_hash": h,
                "progress_rule_hash": h,
                "evidence_requirement_hash": h,
                "expiry_time": exp.isoformat(),
                "nonce": "eip-nonce-1",
                "buyer_signature": sig,
                "currency": "USDC",
                "buyer_wallet_address": acct.address,
            },
        )
        assert ok.status_code == 201, ok.text
    finally:
        voucher_routes.settings = orig
