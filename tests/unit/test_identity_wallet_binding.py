"""Wallet ↔ identity binding on Runtime Key mint."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException
from httpx import AsyncClient

from config.settings import settings
from db.models.orm import IdentityProfileModel
from services.identity_wallet_binding import ensure_wallet_authorized_for_runtime_key, get_bound_wallet
from services.runtime_wallet import build_create_key_message


@pytest.mark.asyncio
async def test_auto_bind_wallet_on_first_create_key(db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_auto_bind_wallet_on_create_key", True)
    monkeypatch.setattr(settings, "runtime_require_wallet_identity_binding", False)
    acct = Account.create()
    await ensure_wallet_authorized_for_runtime_key(
        db_session,
        karma_identity_id="id-bind-1",
        wallet_address=acct.address,
    )
    bound = await get_bound_wallet(db_session, "id-bind-1")
    assert bound.lower() == acct.address.lower()


@pytest.mark.asyncio
async def test_reject_mismatched_wallet_when_binding_required(db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_auto_bind_wallet_on_create_key", True)
    monkeypatch.setattr(settings, "runtime_require_wallet_identity_binding", True)
    acct1 = Account.create()
    acct2 = Account.create()
    await ensure_wallet_authorized_for_runtime_key(
        db_session, karma_identity_id="id-bind-2", wallet_address=acct1.address
    )
    with pytest.raises(HTTPException) as exc:
        await ensure_wallet_authorized_for_runtime_key(
            db_session, karma_identity_id="id-bind-2", wallet_address=acct2.address
        )
    assert "does not match" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_create_key_rejects_wrong_wallet_after_bind(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_auto_bind_wallet_on_create_key", True)
    monkeypatch.setattr(settings, "runtime_require_wallet_identity_binding", True)
    identity = "id-bind-api"
    acct1 = Account.create()
    acct2 = Account.create()
    db_session.add(
        IdentityProfileModel(
            identity_id=identity,
            display_id="Karma-ID-TEST01",
            legal_identity_status="unbound",
            status="active",
            bound_wallet_address=acct1.address.lower(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    await db_session.flush()

    expire = datetime.utcnow() + timedelta(days=7)
    perms = ["sync_task_status"]
    msg = build_create_key_message(
        karma_identity_id=identity,
        wallet_address=acct2.address,
        permissions=perms,
        single_limit=10.0,
        daily_limit=100.0,
        expire_time=expire,
        agent_name="a",
        agent_binding=None,
    )
    signed = acct2.sign_message(encode_defunct(text=msg))
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct2.address,
            "karma_identity_id": identity,
            "wallet_signature": signed.signature.hex(),
            "permissions": perms,
            "single_limit": 10.0,
            "daily_limit": 100.0,
            "expire_time": expire.isoformat(),
            "agent_name": "a",
        },
    )
    assert resp.status_code == 403
