"""过期授权码必须把额度还回来 —— 否则用户会被自己看不见的占用锁死。

线上实测（2026-09-19）：4 张停在 accepted 的授权码把买方的 available_credits 吃成 0，
而链上该钱包还有 12 USDC 真划得动 —— 结果一单也开不出来。这些用例钉死：到期就作废、
占用原样退回、额度不会凭空变多。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete

from core.schemas import VoucherStatus
from db.models.orm import CapacityModel, VoucherModel
from services import voucher_reaper

BUYER = "kid_reaper_buyer"
SELLER = "kid_reaper_seller"


def voucher(
    voucher_id: str,
    *,
    status: str = VoucherStatus.ACCEPTED.value,
    credit: float = 8.0,
    expires_in_hours: float = -1.0,
) -> VoucherModel:
    return VoucherModel(
        voucher_id=voucher_id,
        buyer_identity_id=BUYER,
        seller_identity_id=SELLER,
        amount=credit,
        currency="USDC",
        bill_credit_amount=credit,
        task_type="f6-reaper",
        task_description_hash="0" * 64,
        progress_rule_hash="0" * 64,
        evidence_requirement_hash="0" * 64,
        expiry_time=datetime.utcnow() + timedelta(hours=expires_in_hours),
        nonce=voucher_id,
        buyer_signature="0x" + "00" * 65,
        status=status,
    )


def capacity(*, available: float, reserved: float, total: float) -> CapacityModel:
    return CapacityModel(
        identity_id=BUYER,
        total_locked_usdc=total,
        total_bill_credits=total,
        available_credits=available,
        reserved_credits=reserved,
    )


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(VoucherModel).where(VoucherModel.buyer_identity_id == BUYER))
    await db_session.execute(delete(CapacityModel).where(CapacityModel.identity_id == BUYER))
    await db_session.commit()
    yield
    await db_session.execute(delete(VoucherModel).where(VoucherModel.buyer_identity_id == BUYER))
    await db_session.execute(delete(CapacityModel).where(CapacityModel.identity_id == BUYER))
    await db_session.commit()


async def _load(db, voucher_id: str) -> VoucherModel:
    return await db.get(VoucherModel, voucher_id)


@pytest.mark.asyncio
async def test_an_expired_accepted_voucher_gives_the_credits_back(db_session):
    db_session.add(capacity(available=0.0, reserved=22.0, total=22.0))
    db_session.add(voucher("v-accepted", credit=8.0))
    await db_session.commit()

    out = await voucher_reaper.expire_due(db_session)

    assert out == [{"voucher_id": "v-accepted", "identity_id": BUYER, "released_usdc": 8.0}]
    row = await _load(db_session, "v-accepted")
    assert row.status == VoucherStatus.EXPIRED.value
    cap = await db_session.get(CapacityModel, BUYER)
    assert cap.available_credits == 8.0
    assert cap.reserved_credits == 14.0
    assert cap.total_bill_credits == 22.0  # 只是在桶之间搬，责任总额不变


@pytest.mark.asyncio
async def test_a_live_voucher_is_left_alone(db_session):
    db_session.add(capacity(available=0.0, reserved=8.0, total=8.0))
    db_session.add(voucher("v-live", credit=8.0, expires_in_hours=+24))
    await db_session.commit()

    assert await voucher_reaper.expire_due(db_session) == []
    row = await _load(db_session, "v-live")
    assert row.status == VoucherStatus.ACCEPTED.value
    cap = await db_session.get(CapacityModel, BUYER)
    assert cap.available_credits == 0.0
    assert cap.reserved_credits == 8.0


@pytest.mark.asyncio
async def test_an_unaccepted_expired_voucher_is_expired_without_touching_the_ledger(db_session):
    db_session.add(capacity(available=5.0, reserved=0.0, total=5.0))
    db_session.add(voucher("v-created", status=VoucherStatus.CREATED.value, credit=8.0))
    await db_session.commit()

    assert await voucher_reaper.expire_due(db_session) == []
    row = await _load(db_session, "v-created")
    assert row.status == VoucherStatus.EXPIRED.value
    cap = await db_session.get(CapacityModel, BUYER)
    assert cap.available_credits == 5.0
    assert cap.reserved_credits == 0.0


@pytest.mark.asyncio
async def test_credits_are_never_invented_when_the_reservation_is_already_gone(db_session):
    """占用已经不在（别的路径释放过）：券照样作废，但额度不会凭空变多。"""
    db_session.add(capacity(available=3.0, reserved=0.0, total=3.0))
    db_session.add(voucher("v-double", credit=8.0))
    await db_session.commit()

    assert await voucher_reaper.expire_due(db_session) == []
    row = await _load(db_session, "v-double")
    assert row.status == VoucherStatus.EXPIRED.value
    cap = await db_session.get(CapacityModel, BUYER)
    assert cap.available_credits == 3.0
    assert cap.reserved_credits == 0.0


@pytest.mark.asyncio
async def test_the_sweep_can_be_switched_off(db_session, monkeypatch):
    monkeypatch.setattr(voucher_reaper.settings, "voucher_expiry_sweep_enabled", False)
    db_session.add(capacity(available=0.0, reserved=8.0, total=8.0))
    db_session.add(voucher("v-off", credit=8.0))
    await db_session.commit()

    assert await voucher_reaper.expire_due(db_session) == []
    row = await _load(db_session, "v-off")
    assert row.status == VoucherStatus.ACCEPTED.value