"""P1 — execution receipt templates bound to voucher.task_type (public API)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract

from core.schemas import ApiExecutionReceiptExtension, ExecutionReceipt, ToolStatus
from services.signing import signing_service


def _voucher_json(*, buyer: str, seller: str, task_type: str, nonce: str) -> dict:
    h = "aa" * 32
    exp = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": 25.0,
        "bill_credit_amount": 25.0,
        "task_type": task_type,
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": exp,
        "nonce": nonce,
        "buyer_signature": "0x" + "11" * 65,
        "currency": "USDC",
    }


def _signed_receipt(
    *,
    task_id: str,
    agent_id: str,
    step_index: int = 1,
    extension: ApiExecutionReceiptExtension | None = None,
) -> dict:
    base = datetime.utcnow().replace(microsecond=0)
    r = ExecutionReceipt(
        task_id=task_id,
        agent_id=agent_id,
        step_index=step_index,
        tool_name="http.call",
        input_hash="ab" * 32,
        output_hash="cd" * 32,
        started_at=base,
        ended_at=base + timedelta(milliseconds=100),
        duration_ms=100,
        status=ToolStatus.SUCCESS,
        extension=extension,
    )
    r.signature = signing_service.sign_receipt(r)
    return r.model_dump(mode="json")


@pytest.mark.asyncio
async def test_p1_api_task_rejects_receipt_without_extension(client: AsyncClient):
    buyer, seller = "p1-buyer-api", "p1-seller-api"
    tid = "task-p1-api-missing-ext"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 60.0})
    await post_minimal_contract(
        client,
        task_id=tid,
        client_agent_id=buyer,
        escrow_amount=25.0,
        expected_step_count=5,
    )
    v = await client.post("/v1/vouchers", json=_voucher_json(buyer=buyer, seller=seller, task_type="api.echo", nonce="nonce-p1-api-1"))
    assert v.status_code == 201, v.text
    vid = v.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    await client.post(
        "/v1/settlement/create",
        json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 25.0, "currency": "USD", "voucher_id": vid},
    )

    payload = _signed_receipt(task_id=tid, agent_id=seller, extension=None)
    resp = await client.post("/v1/receipts", json=payload)
    assert resp.status_code == 400
    assert "extension" in resp.json()["detail"].lower() or "requires" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_p1_api_task_accepts_signed_api_extension(client: AsyncClient):
    buyer, seller = "p1-buyer-api2", "p1-seller-api2"
    tid = "task-p1-api-with-ext"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 60.0})
    await post_minimal_contract(
        client,
        task_id=tid,
        client_agent_id=buyer,
        escrow_amount=25.0,
        expected_step_count=5,
    )
    v = await client.post("/v1/vouchers", json=_voucher_json(buyer=buyer, seller=seller, task_type="api.echo", nonce="nonce-p1-api-2"))
    vid = v.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    await client.post(
        "/v1/settlement/create",
        json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 25.0, "currency": "USD", "voucher_id": vid},
    )

    ext = ApiExecutionReceiptExtension(
        request_hash="11" * 32,
        response_hash="22" * 32,
        http_status_code=200,
        latency_ms=15,
    )
    payload = _signed_receipt(task_id=tid, agent_id=seller, extension=ext)
    resp = await client.post("/v1/receipts", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["extension"]["kind"] == "api"
    assert body["extension"]["http_status_code"] == 200

    get_r = await client.get(f"/v1/receipts/{body['receipt_id']}")
    assert get_r.status_code == 200
    assert get_r.json()["extension"]["request_hash"] == "11" * 32


@pytest.mark.asyncio
async def test_p1_generic_task_rejects_typed_extension(client: AsyncClient):
    buyer, seller = "p1-buyer-gen", "p1-seller-gen"
    tid = "task-p1-gen-ext"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 60.0})
    await post_minimal_contract(
        client,
        task_id=tid,
        client_agent_id=buyer,
        escrow_amount=25.0,
        expected_step_count=5,
    )
    v = await client.post("/v1/vouchers", json=_voucher_json(buyer=buyer, seller=seller, task_type="p1.generic", nonce="nonce-p1-gen"))
    vid = v.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    await client.post(
        "/v1/settlement/create",
        json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 25.0, "currency": "USD", "voucher_id": vid},
    )

    ext = ApiExecutionReceiptExtension(
        request_hash="11" * 32,
        response_hash="22" * 32,
        http_status_code=200,
        latency_ms=15,
    )
    payload = _signed_receipt(task_id=tid, agent_id=seller, extension=ext)
    resp = await client.post("/v1/receipts", json=payload)
    assert resp.status_code == 400
