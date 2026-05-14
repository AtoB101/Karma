"""P2 — auto-arbitration uses evidence bundle receipt hash + step metadata integrity."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract

from core.schemas import ExecutionReceipt, ToolStatus
from services.signing import signing_service


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
        tool_name="p2.arb.step",
        input_hash="ab" * 32,
        output_hash="cd" * 32,
        started_at=base,
        ended_at=base + timedelta(milliseconds=80),
        duration_ms=80,
        status=ToolStatus.SUCCESS,
    )
    r.signature = signing_service.sign_receipt(r)
    return r.model_dump(mode="json")


@pytest.mark.asyncio
async def test_auto_arbitrate_buyer_wins_when_bundle_receipt_hashes_tampered(client: AsyncClient):
    task_id = "task-p2-bundle-hash-tamper"
    buyer = "buyer-p2-bht"
    seller = "seller-p2-bht"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 55.0})
    await post_minimal_contract(
        client,
        task_id=task_id,
        client_agent_id=buyer,
        escrow_amount=55.0,
        expected_step_count=5,
    )
    v = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 55.0,
            "currency": "USDC",
            "bill_credit_amount": 55.0,
            "task_type": "p2.bundle.test",
            "task_description_hash": "a" * 64,
            "progress_rule_hash": "b" * 64,
            "evidence_requirement_hash": "c" * 64,
            "expiry_time": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
            "nonce": "nonce-p2-bht",
            "buyer_signature": "sig-p2-bht",
        },
    )
    vid = v.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": 55.0, "currency": "USD", "voucher_id": vid},
    )
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    rec = await client.post("/v1/receipts", json=_signed_receipt_dict(task_id=task_id, agent_id=seller))
    assert rec.status_code == 201, rec.text
    rid = rec.json()["receipt_id"]

    bundle = {
        "task_id": task_id,
        "task_contract_hash": "cc" * 32,
        "receipt_ids": [rid],
        "receipt_hashes": ["ff" * 32],
        "final_result_hash": "ee" * 32,
        "total_steps": 1,
        "successful_steps": 1,
        "failed_steps": 0,
        "total_duration_ms": 80,
        "settlement_status": "delivered",
    }
    bresp = await client.post("/v1/bundles", json=bundle)
    assert bresp.status_code == 201, bresp.text

    await client.post(f"/v1/settlement/{task_id}/submit", json={})
    d = await client.post(f"/v1/settlement/{task_id}/dispute", json={"reason": "p2 bundle hash test"})
    assert d.status_code == 200

    arb = await client.post(f"/v1/settlement/{task_id}/auto-arbitrate", json={})
    assert arb.status_code == 200
    body = arb.json()
    assert body["status"] == "refunded"
    assert body["released_amount"] == 0.0
    assert body["refunded_amount"] == 55.0
    notes = (body.get("arbitration_notes") or "").lower()
    assert "hash" in notes or "integrity" in notes


@pytest.mark.asyncio
async def test_auto_arbitrate_format_error_when_bundle_step_counts_inconsistent(client: AsyncClient):
    task_id = "task-p2-bundle-step-bad"
    buyer = "buyer-p2-steps"
    seller = "seller-p2-steps"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 40.0})
    await post_minimal_contract(
        client,
        task_id=task_id,
        client_agent_id=buyer,
        escrow_amount=40.0,
        expected_step_count=5,
    )
    v = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 40.0,
            "currency": "USDC",
            "bill_credit_amount": 40.0,
            "task_type": "p2.bundle.steps",
            "task_description_hash": "a" * 64,
            "progress_rule_hash": "b" * 64,
            "evidence_requirement_hash": "c" * 64,
            "expiry_time": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
            "nonce": "nonce-p2-steps",
            "buyer_signature": "sig-p2-steps",
        },
    )
    await client.post(f"/v1/vouchers/{v.json()['voucher_id']}/accept", json={"seller_identity_id": seller})
    await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": 40.0, "currency": "USD", "voucher_id": v.json()["voucher_id"]},
    )
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    rec = await client.post("/v1/receipts", json=_signed_receipt_dict(task_id=task_id, agent_id=seller))
    rid = rec.json()["receipt_id"]

    from core.evidence.bundle_builder import execution_receipt_bundle_digest

    er = ExecutionReceipt(**rec.json())
    good_hash = execution_receipt_bundle_digest(er)

    bundle = {
        "task_id": task_id,
        "task_contract_hash": "11" * 32,
        "receipt_ids": [rid],
        "receipt_hashes": [good_hash],
        "final_result_hash": "22" * 32,
        "total_steps": 99,
        "successful_steps": 1,
        "failed_steps": 0,
        "total_duration_ms": 80,
        "settlement_status": "delivered",
    }
    assert (await client.post("/v1/bundles", json=bundle)).status_code == 201

    await client.post(f"/v1/settlement/{task_id}/submit", json={})
    await client.post(f"/v1/settlement/{task_id}/dispute", json={"reason": "step meta"})
    arb = await client.post(f"/v1/settlement/{task_id}/auto-arbitrate", json={})
    assert arb.status_code == 200
    assert arb.json()["status"] == "refunded"
    assert arb.json()["released_amount"] == 0.0
    notes = (arb.json().get("arbitration_notes") or "").lower()
    assert "format error" in notes or "step" in notes
