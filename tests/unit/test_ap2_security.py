"""KSA-AP2 reverse-rule regressions (Phase 3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from core.schemas import EvidenceBundle, TaskStatus
from db.session import get_db


@pytest.mark.asyncio
async def test_verify_external_rejects_incomplete_mandate(client: AsyncClient, db_session):
    """KSA-AP2-001: malformed AP2 mandate must not verify."""
    bundle = EvidenceBundle(
        bundle_id="ap2-sec-bundle-1",
        task_id="ap2-sec-task-1",
        task_contract_hash="a" * 64,
        receipt_ids=["r1"],
        receipt_hashes=["b" * 64],
        final_result_hash="b" * 64,
        total_steps=1,
        successful_steps=1,
        failed_steps=0,
        total_duration_ms=1,
        settlement_status=TaskStatus.DELIVERED,
    )
    post = await client.post("/v1/bundles", json=bundle.model_dump(mode="json"))
    assert post.status_code == 201

    bad = await client.post(
        f"/v1/evidence/{bundle.bundle_id}/verify-external",
        json={"ap2_mandate": {"ap2_version": "broken"}},
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_payment_intent_requires_idempotency_in_production(monkeypatch):
    """KSA-AP2-002: production must require Idempotency-Key on payment-intents."""
    from config import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "app_env", "production")
    expires = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    body = {
        "merchantRef": "m-ref-1",
        "payer": "0xa",
        "payee": "0xb",
        "token": "USDC",
        "amount": "1000000",
        "chainId": 11155111,
        "policyId": "policy-1",
        "expiresAt": expires,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/v1/payment-intents", json=body)
    assert r.status_code == 400
    assert "Idempotency" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_human_not_present_rejects_excessive_limits(client: AsyncClient, db_session):
    """KSA-AP2-003: human_not_present_allowed enforces stricter caps on policy save."""
    identity = "hnp-buyer-1"
    resp = await client.put(
        f"/v1/identities/{identity}/automation-policy",
        json={
            "auto_enabled": True,
            "single_limit": 500,
            "daily_limit": 1000,
            "permissions": ["submit_receipt"],
            "high_risk_mode": "always",
            "responsibility_acknowledged": True,
            "human_not_present_allowed": True,
        },
    )
    assert resp.status_code == 400
