"""Runtime Gateway — create key, permissions, and HMAC response headers."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from services.runtime_wallet import build_create_key_message


@pytest.mark.asyncio
async def test_runtime_create_key_and_permissions(client: AsyncClient, db_session):
    acct = Account.create()
    wallet = acct.address
    identity = "buyer-runtime-test-1"
    perms = sorted(["request_voucher", "submit_receipt", "sync_task_status"])
    expire = datetime.utcnow() + timedelta(days=30)
    msg = build_create_key_message(
        karma_identity_id=identity,
        wallet_address=wallet,
        permissions=perms,
        single_limit=100.0,
        daily_limit=500.0,
        expire_time=expire,
        agent_name="test-agent",
        agent_binding=None,
    )
    signed = acct.sign_message(encode_defunct(text=msg))

    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": wallet,
            "karma_identity_id": identity,
            "wallet_signature": signed.signature.hex(),
            "permissions": perms,
            "single_limit": 100.0,
            "daily_limit": 500.0,
            "expire_time": expire.isoformat(),
            "agent_name": "test-agent",
        },
    )
    assert resp.status_code == 201, resp.text
    assert "X-Karma-Response-Signature" in resp.headers
    data = resp.json()
    assert data["runtime_key"].startswith("KRM_RT_")
    rt = data["runtime_key"]

    pr = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": rt})
    assert pr.status_code == 200
    body = pr.json()
    assert body["key_id"] == data["key_id"]
    assert set(body["permissions"]) == set(perms)
