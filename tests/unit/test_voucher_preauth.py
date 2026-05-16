"""Phase 1 — preauth evaluation for auto accept/reject."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from db.models.orm import AgentAutomationPolicyModel, CapacityModel, VoucherModel
from core.schemas import VoucherStatus
from services.voucher_preauth import evaluate_seller_preauth, evaluate_buyer_preauth_for_create


@pytest.mark.asyncio
async def test_seller_auto_accept_when_rules_match(db_session):
    seller = "seller-preauth-1"
    buyer = "buyer-preauth-1"
    db_session.add(
        AgentAutomationPolicyModel(
            karma_identity_id=seller,
            auto_enabled=True,
            single_limit=100.0,
            daily_limit=500.0,
            permissions=["verify_voucher"],
            high_risk_mode="always",
            responsibility_acknowledged=True,
            preauth_enabled=True,
            auto_accept_incoming=True,
            allowed_task_types=["api.caption"],
            task_precision_min=0.5,
            task_precision_max=2.0,
            trusted_counterparty_ids=[buyer],
            payment_code_ttl_seconds=3600,
            responsibility_boundary_id="scene-v1",
            policy_version=1,
        )
    )
    db_session.add(
        CapacityModel(
            identity_id=buyer,
            total_locked_usdc=50.0,
            total_bill_credits=50.0,
            available_credits=50.0,
        )
    )
    voucher = VoucherModel(
        voucher_id="v-preauth-1",
        buyer_identity_id=buyer,
        seller_identity_id=seller,
        amount=10.0,
        bill_credit_amount=10.0,
        task_type="api.caption",
        task_description_hash="h1",
        progress_rule_hash="h2",
        evidence_requirement_hash="h3",
        expiry_time=datetime.utcnow() + timedelta(hours=1),
        nonce="n1",
        buyer_signature="0xsig",
        status=VoucherStatus.CREATED.value,
        task_precision=1.0,
        payment_mode="preauth",
    )
    db_session.add(voucher)
    await db_session.flush()

    ev = await evaluate_seller_preauth(db_session, seller_identity_id=seller, voucher=voucher)
    assert ev.accept is True


@pytest.mark.asyncio
async def test_seller_reject_precision_mismatch(db_session):
    seller = "seller-preauth-2"
    db_session.add(
        AgentAutomationPolicyModel(
            karma_identity_id=seller,
            auto_enabled=True,
            single_limit=100.0,
            daily_limit=500.0,
            permissions=[],
            high_risk_mode="always",
            responsibility_acknowledged=True,
            preauth_enabled=True,
            auto_accept_incoming=True,
            allowed_task_types=[],
            task_precision_min=2.0,
            task_precision_max=5.0,
            trusted_counterparty_ids=[],
            payment_code_ttl_seconds=3600,
            policy_version=1,
        )
    )
    voucher = VoucherModel(
        voucher_id="v-preauth-2",
        buyer_identity_id="buyer-x",
        seller_identity_id=seller,
        amount=5.0,
        bill_credit_amount=5.0,
        task_type="api.caption",
        task_description_hash="h1",
        progress_rule_hash="h2",
        evidence_requirement_hash="h3",
        expiry_time=datetime.utcnow() + timedelta(hours=1),
        nonce="n2",
        buyer_signature="0xsig",
        status=VoucherStatus.CREATED.value,
        task_precision=1.0,
        payment_mode="preauth",
    )
    db_session.add(voucher)
    await db_session.flush()
    ev = await evaluate_seller_preauth(db_session, seller_identity_id=seller, voucher=voucher)
    assert ev.accept is False
    assert ev.code == "precision_mismatch"


@pytest.mark.asyncio
async def test_buyer_preauth_blocks_untrusted_seller(db_session):
    buyer_policy = AgentAutomationPolicyModel(
        karma_identity_id="buyer-y",
        auto_enabled=False,
        single_limit=50.0,
        daily_limit=100.0,
        permissions=[],
        high_risk_mode="always",
        responsibility_acknowledged=True,
        preauth_enabled=True,
        trusted_counterparty_ids=["seller-ok"],
        policy_version=1,
    )
    ev = await evaluate_buyer_preauth_for_create(
        buyer_policy,
        seller_identity_id="seller-bad",
        amount=10.0,
        task_type="api.caption",
        task_precision=1.0,
    )
    assert ev.accept is False
