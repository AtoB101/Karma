"""Full trade order launch — decompose, accept, settlement, execution kickoff."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from config.settings import settings
from db.models.orm import AgentAutomationPolicyModel, CapacityModel, RuntimeKeyModel
from services.agent_automation_policy import upsert_automation_policy


async def _seed_party(db, identity: str, *, seller: bool = False):
    await upsert_automation_policy(
        db,
        karma_identity_id=identity,
        auto_enabled=True,
        single_limit=100.0,
        daily_limit=500.0,
        permissions=["submit_receipt", "verify_voucher", "update_progress"],
        high_risk_mode="always",
        responsibility_acknowledged=True,
        preauth_enabled=True,
        auto_accept_incoming=seller,
        auto_execute_pipeline=True,
        allowed_task_types=["api.caption"],
        task_precision_min=0.5,
        task_precision_max=5.0,
        trusted_counterparty_ids=[],
        responsibility_boundary_id="scene-test",
    )
    db.add(
        RuntimeKeyModel(
            key_id=f"key-{identity}",
            secret_hash="$2b$12$testtesttesttesttesttesttesttesttesttesttest",
            wallet_address="0x" + "ab" * 20,
            karma_identity_id=identity,
            permissions=["submit_receipt", "verify_voucher", "update_progress"],
            single_limit=100.0,
            daily_limit=500.0,
            expire_at=datetime.utcnow() + timedelta(days=3),
            agent_name="test",
            status="active",
        )
    )


@pytest.mark.asyncio
async def test_launch_full_pipeline(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ledger_require_party_actor", False)
    buyer, seller = "buyer-launch-1", "seller-launch-1"
    db_session.add(
        CapacityModel(
            identity_id=buyer,
            total_locked_usdc=200.0,
            total_bill_credits=200.0,
            available_credits=200.0,
        )
    )
    await _seed_party(db_session, buyer, seller=False)
    await _seed_party(db_session, seller, seller=True)
    policy = await db_session.get(AgentAutomationPolicyModel, seller)
    if policy:
        policy.trusted_counterparty_ids = [buyer]
    await db_session.commit()

    resp = await client.post(
        "/v1/trade/orders/launch",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "requirement_text": "caption 字幕任务 金额 15 USDC 精度 1.2",
            "buyer_signature": "0xlaunch",
            "task_type": "api.caption",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "execution_started"
    assert body["decomposed"]["task_type"] == "api.caption"
    assert body["readiness"]["buyer"] is True
    assert body["readiness"]["seller"] is True
