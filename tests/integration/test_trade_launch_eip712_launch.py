"""Trade launch with EIP-712 buyer signature enforced."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from eth_account import Account
from httpx import AsyncClient

from config.settings import settings
from db.models.orm import CapacityModel, IdentityProfileModel, RuntimeKeyModel
from services.agent_automation_policy import upsert_automation_policy
from services.trade_launch_signing import build_signing_preview


async def _seed_party(db, identity: str, wallet: str, *, seller: bool = False):
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
        responsibility_boundary_id="scene-eip712",
    )
    db.add(
        IdentityProfileModel(
            identity_id=identity,
            display_id=f"ID-{identity[:6]}",
            legal_identity_status="bound",
            status="active",
            bound_wallet_address=wallet,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    db.add(
        RuntimeKeyModel(
            key_id=f"key-{identity}",
            secret_hash="$2b$12$testtesttesttesttesttesttesttesttesttesttest",
            wallet_address=wallet,
            karma_identity_id=identity,
            permissions=["submit_receipt"],
            single_limit=100.0,
            daily_limit=500.0,
            expire_at=datetime.utcnow() + timedelta(days=1),
            agent_name="test",
            status="active",
        )
    )


@pytest.mark.asyncio
async def test_launch_with_eip712_signature(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "trade_launch_require_eip712", True)
    monkeypatch.setattr(settings, "ledger_require_party_actor", False)

    acct = Account.create()
    wallet = acct.address
    buyer, seller = "buyer-eip712", "seller-eip712"

    db_session.add(
        CapacityModel(
            identity_id=buyer,
            total_locked_usdc=200.0,
            total_bill_credits=200.0,
            available_credits=200.0,
        )
    )
    await _seed_party(db_session, buyer, wallet, seller=False)
    await _seed_party(db_session, seller, wallet, seller=True)
    from db.models.orm import AgentAutomationPolicyModel

    pol = await db_session.get(AgentAutomationPolicyModel, seller)
    if pol:
        pol.trusted_counterparty_ids = [buyer]
    await db_session.commit()

    preview = await build_signing_preview(
        db_session,
        buyer_identity_id=buyer,
        seller_identity_id=seller,
        requirement_text="caption 字幕 15 USDC 精度 1.2",
        amount=None,
        task_type="api.caption",
        task_precision=None,
        launch_idempotency_key="trade-eip712-launch-key",
        chain_anchor_hash=None,
    )
    from services.trade_launch_eip712 import sign_trade_launch_typed_data

    sig = sign_trade_launch_typed_data(private_key=acct.key, typed_data=preview["typed_data"])

    resp = await client.post(
        "/v1/trade/orders/launch",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "requirement_text": "caption 字幕 15 USDC 精度 1.2",
            "buyer_signature": sig,
            "task_type": "api.caption",
        },
        headers={"Idempotency-Key": "trade-eip712-launch-key"},
    )
    assert resp.status_code == 201, resp.text
