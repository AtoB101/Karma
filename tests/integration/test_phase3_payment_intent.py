"""Phase 3 — PaymentIntent lifecycle with settlement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_payment_intent_create_bind_settle(client: AsyncClient, db_session):
    expires = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    headers = {"Idempotency-Key": "phase3-intent-test-key-001"}
    body = {
        "merchantRef": "merchant-order-99",
        "payer": "buyer-identity-1",
        "payee": "seller-identity-1",
        "token": "USDC",
        "amount": "1000000",
        "chainId": 11155111,
        "policyId": "policy-default",
        "expiresAt": expires.isoformat().replace("+00:00", "Z"),
    }
    create = await client.post("/v1/payment-intents", json=body, headers=headers)
    assert create.status_code == 201
    intent = create.json()
    assert intent["intentId"].startswith("pi_")
    assert intent["status"] == "created"

    task_id = "phase3-task-001"
    bind = await client.post(
        f"/v1/payment-intents/{intent['intentId']}/bind",
        json={"taskId": task_id},
    )
    assert bind.status_code == 200
    assert bind.json()["status"] == "authorized"

    from services.payment_intent_service import mark_intents_settled_for_task

    n = await mark_intents_settled_for_task(db_session, task_id)
    await db_session.commit()
    assert n == 1

    get_resp = await client.get(f"/v1/payment-intents/{intent['intentId']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "settled"


@pytest.mark.asyncio
async def test_payment_intent_idempotent_create(client: AsyncClient):
    expires = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    headers = {"Idempotency-Key": "phase3-idem-key-002"}
    body = {
        "merchantRef": "merchant-order-idem",
        "payer": "buyer-a",
        "payee": "seller-b",
        "token": "USDC",
        "amount": "500000",
        "chainId": 1,
        "policyId": "p1",
        "expiresAt": expires.isoformat().replace("+00:00", "Z"),
    }
    r1 = await client.post("/v1/payment-intents", json=body, headers=headers)
    r2 = await client.post("/v1/payment-intents", json=body, headers=headers)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["intentId"] == r2.json()["intentId"]
