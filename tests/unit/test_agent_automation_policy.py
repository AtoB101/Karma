"""Automation policy persistence and Runtime Key mint alignment."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from config.settings import settings
from services.agent_automation_policy import upsert_automation_policy
from services.runtime_wallet import build_create_key_message


@pytest.mark.asyncio
async def test_put_automation_policy_requires_responsibility_ack(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_api_keys", "op:op-secret-123456789012")
    resp = await client.put(
        "/v1/identities/buyer-policy-1/automation-policy",
        headers={"X-Karma-Api-Key": "karma_op_op-secret-123456789012"},
        json={
            "auto_enabled": True,
            "single_limit": 50,
            "daily_limit": 200,
            "permissions": ["submit_receipt"],
            "high_risk_mode": "always",
            "responsibility_acknowledged": False,
        },
    )
    assert resp.status_code == 400
    assert "responsibility" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_runtime_create_key_rejected_without_policy(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_require_saved_automation_policy", True)
    acct = Account.create()
    perms = ["submit_receipt", "sync_task_status"]
    expire = datetime.utcnow() + timedelta(days=7)
    msg = build_create_key_message(
        karma_identity_id="buyer-no-policy",
        wallet_address=acct.address,
        permissions=perms,
        single_limit=10.0,
        daily_limit=100.0,
        expire_time=expire,
        agent_name="a",
        agent_binding=None,
    )
    signed = acct.sign_message(encode_defunct(text=msg))
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": "buyer-no-policy",
            "wallet_signature": signed.signature.hex(),
            "permissions": perms,
            "single_limit": 10.0,
            "daily_limit": 100.0,
            "expire_time": expire.isoformat(),
            "agent_name": "a",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_runtime_create_key_matches_saved_policy(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_require_saved_automation_policy", True)
    identity = "buyer-policy-ok"
    await upsert_automation_policy(
        db_session,
        karma_identity_id=identity,
        auto_enabled=True,
        single_limit=100.0,
        daily_limit=500.0,
        permissions=["submit_receipt", "sync_task_status"],
        high_risk_mode="always",
        responsibility_acknowledged=True,
    )
    await db_session.commit()

    acct = Account.create()
    perms = sorted(["submit_receipt", "sync_task_status"])
    expire = datetime.utcnow() + timedelta(days=7)
    msg = build_create_key_message(
        karma_identity_id=identity,
        wallet_address=acct.address,
        permissions=perms,
        single_limit=50.0,
        daily_limit=200.0,
        expire_time=expire,
        agent_name="a",
        agent_binding=None,
    )
    signed = acct.sign_message(encode_defunct(text=msg))
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": identity,
            "wallet_signature": signed.signature.hex(),
            "permissions": perms,
            "single_limit": 50.0,
            "daily_limit": 200.0,
            "expire_time": expire.isoformat(),
            "agent_name": "a",
        },
    )
    assert resp.status_code == 201, resp.text
