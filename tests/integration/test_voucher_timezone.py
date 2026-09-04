"""Regression tests for voucher expiry_time timezone handling.

Covers the 500 bug: naive-vs-aware datetime comparison on voucher create.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from config.settings import settings
from db.models.orm import CapacityModel


def _voucher_body(*, buyer: str, seller: str, expiry: str, nonce: str) -> dict:
    h = "aa" * 32
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": 5.0,
        "bill_credit_amount": 5.0,
        "task_type": "tz.regression",
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": expiry,
        "nonce": nonce,
        "buyer_signature": "0x" + "11" * 65,
        "currency": "USDC",
    }


async def _seed_capacity(db_session, buyer: str, amount: float = 100.0) -> None:
    db_session.add(
        CapacityModel(
            identity_id=buyer,
            total_locked_usdc=amount,
            total_bill_credits=amount,
            available_credits=amount,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_voucher_aware_utc_expiry_ok(client: AsyncClient, db_session):
    """Aware UTC expiry (with +00:00 offset) must not 500."""
    buyer, seller = "tz-aware-buyer", "tz-aware-seller"
    await _seed_capacity(db_session, buyer)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    r = await client.post(
        "/v1/vouchers",
        json=_voucher_body(buyer=buyer, seller=seller, expiry=expiry, nonce="tz-aware-1"),
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_voucher_aware_nonutc_offset_expiry_ok(client: AsyncClient, db_session):
    """Aware non-UTC offset (+08:00) must not 500 (the original bug class)."""
    buyer, seller = "tz-0800-buyer", "tz-0800-seller"
    await _seed_capacity(db_session, buyer)
    tz = timezone(timedelta(hours=8))
    expiry = (datetime.now(tz) + timedelta(hours=2)).isoformat()
    r = await client.post(
        "/v1/vouchers",
        json=_voucher_body(buyer=buyer, seller=seller, expiry=expiry, nonce="tz-0800-1"),
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_voucher_naive_expiry_ok(client: AsyncClient, db_session):
    """Naive expiry (no offset) is treated as UTC and must be accepted."""
    buyer, seller = "tz-naive-buyer", "tz-naive-seller"
    await _seed_capacity(db_session, buyer)
    expiry = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    r = await client.post(
        "/v1/vouchers",
        json=_voucher_body(buyer=buyer, seller=seller, expiry=expiry, nonce="tz-naive-1"),
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_voucher_past_expiry_rejected(client: AsyncClient, db_session):
    """Past expiry must be rejected (400), not crash."""
    buyer, seller = "tz-past-buyer", "tz-past-seller"
    await _seed_capacity(db_session, buyer)
    expiry = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = await client.post(
        "/v1/vouchers",
        json=_voucher_body(buyer=buyer, seller=seller, expiry=expiry, nonce="tz-past-1"),
    )
    assert r.status_code == 400, r.text
