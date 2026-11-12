"""Runtime Key daily spend persistence."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from config.settings import settings
from services.runtime_daily_spend import get_daily_used_async, record_daily_spend_async
from services.runtime_key_service import create_runtime_key_record
from services.runtime_wallet import build_create_key_message


@pytest.mark.asyncio
async def test_daily_spend_persists_in_db(db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_daily_spend_persist", True)
    acct = Account.create()
    token, row = await create_runtime_key_record(
        db=db_session,
        wallet_address=acct.address,
        karma_identity_id="buyer-daily-db",
        permissions=["request_voucher"],
        single_limit=100.0,
        daily_limit=500.0,
        expire_at=datetime.utcnow() + timedelta(days=1),
        agent_name="t",
        agent_binding=None,
    )
    assert token.startswith("KRM_RT_")
    await record_daily_spend_async(db_session, key_id=row.key_id, amount=25.0)
    await record_daily_spend_async(db_session, key_id=row.key_id, amount=10.0)
    used = await get_daily_used_async(db_session, row.key_id)
    assert used == pytest.approx(35.0)


@pytest.mark.asyncio
async def test_check_limits_uses_persisted_daily_used(db_session, monkeypatch):
    from services.runtime_key_service import check_single_and_daily_limits, create_runtime_key_record

    monkeypatch.setattr(settings, "runtime_daily_spend_persist", True)
    _, row = await create_runtime_key_record(
        db=db_session,
        wallet_address=Account.create().address,
        karma_identity_id="buyer-limit",
        permissions=["request_voucher"],
        single_limit=30.0,
        daily_limit=50.0,
        expire_at=datetime.utcnow() + timedelta(days=1),
        agent_name="t",
        agent_binding=None,
    )
    await record_daily_spend_async(db_session, key_id=row.key_id, amount=25.0)
    used = await get_daily_used_async(db_session, row.key_id)
    with pytest.raises(Exception) as exc:
        check_single_and_daily_limits(
            key_id=row.key_id,
            amount=10.0,
            single_limit=50.0,
            daily_limit=30.0,
            daily_used=used,
        )
    from fastapi import HTTPException

    assert isinstance(exc.value, HTTPException)
    assert "daily_limit" in str(exc.value.detail).lower()
