"""Phase 1 E2E — payment code manual accept + preauth auto reject/accept."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from config.settings import settings
from db.models.orm import AgentAutomationPolicyModel, CapacityModel


@pytest.mark.asyncio
async def test_manual_payment_code_accept(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ledger_require_party_actor", False)
    buyer, seller = "buyer-pc-1", "seller-pc-1"
    db_session.add(
        CapacityModel(
            identity_id=buyer,
            total_locked_usdc=100.0,
            total_bill_credits=100.0,
            available_credits=100.0,
        )
    )
    await db_session.commit()

    create = await client.post(
        "/v1/payment-codes",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 15.0,
            "bill_credit_amount": 15.0,
            "task_type": "api.caption",
            "task_precision": 1.0,
            "task_description_hash": "auto",
            "progress_rule_hash": "auto",
            "evidence_requirement_hash": "auto",
            "buyer_signature": "0xtest",
            "payment_mode": "manual",
            "ttl_seconds": 3600,
        },
    )
    assert create.status_code == 201, create.text
    vid = create.json()["voucher"]["voucher_id"]
    assert create.json()["payment_code"]["version"] == "payment_code_v1"

    accept = await client.post(
        f"/v1/payment-codes/{vid}/accept",
        json={"seller_identity_id": seller},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_preauth_auto_reject_precision(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ledger_require_party_actor", False)
    buyer, seller = "buyer-pc-2", "seller-pc-2"
    db_session.add(
        CapacityModel(
            identity_id=buyer,
            total_locked_usdc=50.0,
            total_bill_credits=50.0,
            available_credits=50.0,
        )
    )
    db_session.add(
        AgentAutomationPolicyModel(
            karma_identity_id=buyer,
            auto_enabled=True,
            single_limit=100.0,
            daily_limit=200.0,
            permissions=["submit_receipt"],
            high_risk_mode="always",
            responsibility_acknowledged=True,
            preauth_enabled=True,
            allowed_task_types=["api.caption"],
            payment_code_ttl_seconds=3600,
            responsibility_boundary_id="b1",
            policy_version=1,
        )
    )
    db_session.add(
        AgentAutomationPolicyModel(
            karma_identity_id=seller,
            auto_enabled=True,
            single_limit=100.0,
            daily_limit=200.0,
            permissions=["verify_voucher"],
            high_risk_mode="always",
            responsibility_acknowledged=True,
            preauth_enabled=True,
            auto_accept_incoming=True,
            task_precision_min=5.0,
            task_precision_max=10.0,
            trusted_counterparty_ids=[buyer],
            responsibility_boundary_id="b1",
            policy_version=1,
        )
    )
    await db_session.commit()

    create = await client.post(
        "/v1/payment-codes",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 10.0,
            "bill_credit_amount": 10.0,
            "task_type": "api.caption",
            "task_precision": 1.0,
            "task_description_hash": "auto",
            "progress_rule_hash": "auto",
            "evidence_requirement_hash": "auto",
            "buyer_signature": "0xtest",
            "payment_mode": "preauth",
            "ttl_seconds": 3600,
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["auto_result"]["action"] == "rejected"
    assert body["voucher"]["status"] == "rejected"

    events = await client.get(
        f"/v1/vouchers/{body['voucher']['voucher_id']}/events",
        params={"identity_id": buyer},
    )
    assert events.status_code == 200
    types = [e["event_type"] for e in events.json()["events"]]
    assert "voucher.rejected" in types
