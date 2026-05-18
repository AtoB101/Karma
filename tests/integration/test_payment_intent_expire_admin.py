"""Admin maintenance — expire stale payment intents."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from config.settings import settings
from db.models.orm import PaymentIntentModel


@pytest.mark.asyncio
async def test_admin_expire_stale_payment_intents(client_sec, db_session, monkeypatch):
    monkeypatch.setattr(settings, "payment_intent_expire_enabled", True)
    monkeypatch.setattr(settings, "admin_actor_ids", "sec-route-default")

    expires = (datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None)
    headers = {"Idempotency-Key": "expire-admin-test-001"}
    body = {
        "merchantRef": "expired-m",
        "payer": "a",
        "payee": "b",
        "token": "USDC",
        "amount": "1000",
        "chainId": 1,
        "policyId": "p",
        "expiresAt": expires.isoformat() + "Z",
    }
    create = await client_sec.post("/v1/payment-intents", json=body, headers=headers)
    assert create.status_code == 201
    intent_id = create.json()["intentId"]

    row = await db_session.get(PaymentIntentModel, intent_id)
    assert row is not None
    row.expires_at = datetime.utcnow() - timedelta(hours=2)
    row.status = "created"
    await db_session.flush()

    exp = await client_sec.post("/v1/admin/maintenance/expire-payment-intents")
    assert exp.status_code == 200
    assert exp.json()["expired_count"] >= 1

    get_resp = await client_sec.get(f"/v1/payment-intents/{intent_id}")
    assert get_resp.json()["status"] == "expired"
