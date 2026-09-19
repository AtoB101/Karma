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

@pytest.mark.asyncio
async def test_try_reserve_daily_spend_caps_atomically(db_session, monkeypatch):
    """日限额的判定和记账必须是同一次原子操作 —— 否则并发能顶穿上限。"""
    from services.runtime_daily_spend import try_reserve_daily_spend

    monkeypatch.setattr(settings, "runtime_daily_spend_persist", True)
    _, row = await create_runtime_key_record(
        db=db_session,
        wallet_address=Account.create().address,
        karma_identity_id="buyer-reserve",
        permissions=["request_voucher"],
        single_limit=5.0,
        daily_limit=11.0,
        expire_at=datetime.utcnow() + timedelta(days=1),
        agent_name="t",
        agent_binding=None,
    )
    assert await try_reserve_daily_spend(
        db_session, key_id=row.key_id, amount=5.0, daily_limit=11.0
    ) is True
    assert await try_reserve_daily_spend(
        db_session, key_id=row.key_id, amount=5.0, daily_limit=11.0
    ) is True
    # 10 + 5 > 11：这一笔必须被拒，且不能悄悄加进账里
    assert await try_reserve_daily_spend(
        db_session, key_id=row.key_id, amount=5.0, daily_limit=11.0
    ) is False
    used = await get_daily_used_async(db_session, row.key_id)
    assert used == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_daily_spend_add_never_loses_updates(db_session, monkeypatch):
    """行已存在时走 UPDATE 自增，连续加账不能丢更新。"""
    monkeypatch.setattr(settings, "runtime_daily_spend_persist", True)
    _, row = await create_runtime_key_record(
        db=db_session,
        wallet_address=Account.create().address,
        karma_identity_id="buyer-add",
        permissions=["request_voucher"],
        single_limit=5.0,
        daily_limit=100.0,
        expire_at=datetime.utcnow() + timedelta(days=1),
        agent_name="t",
        agent_binding=None,
    )
    for amount in (1.0, 2.0, 3.0):
        await record_daily_spend_async(db_session, key_id=row.key_id, amount=amount)
    used = await get_daily_used_async(db_session, row.key_id)
    assert used == pytest.approx(6.0)


def test_runtime_gateway_reserves_daily_spend_atomically():
    """闸门必须用原子占额度那条路径；退回"读-算-写"就等于没有日上限。"""
    import pathlib

    src = pathlib.Path("api/routes/runtime_gateway.py").read_text(encoding="utf-8")
    assert "try_reserve_daily_spend" in src
    assert "record_daily_spend_async" not in src
