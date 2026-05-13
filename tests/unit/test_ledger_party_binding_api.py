"""Ledger (capacity + voucher) party binding when auth enforcement is on."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from config.settings import settings
from db.models.orm import CapacityModel
from db.session import get_db


def _voucher_body(*, buyer: str, seller: str, nonce: str) -> dict:
    h = "a" * 64
    exp = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": 10.0,
        "bill_credit_amount": 10.0,
        "task_type": "ledger.bind.test",
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": exp,
        "nonce": nonce,
        "buyer_signature": "0x" + "11" * 65,
        "currency": "USDC",
    }


@pytest.mark.asyncio
async def test_capacity_lock_rejects_cross_identity_actor(db_session):
    original_enforce = settings.auth_enforce_protected_routes
    original_ledger = settings.ledger_require_party_actor
    original_keys = settings.auth_api_keys
    try:
        settings.auth_enforce_protected_routes = True
        settings.ledger_require_party_actor = True
        settings.auth_api_keys = "buyer-ledger-1:secret-one-123456,other-ledger:secret-two-123456"

        now = datetime.utcnow()
        db_session.add(
            CapacityModel(
                identity_id="buyer-ledger-1",
                total_locked_usdc=100.0,
                total_bill_credits=100.0,
                available_credits=100.0,
                reserved_credits=0.0,
                in_progress_credits=0.0,
                confirmed_progress_credits=0.0,
                disputed_credits=0.0,
                pending_settlement_credits=0.0,
                burned_credits=0.0,
                released_credits=0.0,
                updated_at=now,
            )
        )
        await db_session.flush()

        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            bad = await client.post(
                "/v1/capacity/buyer-ledger-1/lock",
                json={"amount": 1.0},
                headers={"X-Karma-Api-Key": "karma_other-ledger_secret-two-123456"},
            )
            assert bad.status_code == 403

            ok = await client.post(
                "/v1/capacity/buyer-ledger-1/lock",
                json={"amount": 1.0},
                headers={"X-Karma-Api-Key": "karma_buyer-ledger-1_secret-one-123456"},
            )
            assert ok.status_code == 200, ok.text
    finally:
        settings.auth_enforce_protected_routes = original_enforce
        settings.ledger_require_party_actor = original_ledger
        settings.auth_api_keys = original_keys
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_voucher_create_rejects_non_buyer_actor(db_session):
    original_enforce = settings.auth_enforce_protected_routes
    original_ledger = settings.ledger_require_party_actor
    original_keys = settings.auth_api_keys
    try:
        settings.auth_enforce_protected_routes = True
        settings.ledger_require_party_actor = True
        settings.auth_api_keys = "buyer-v:secret-b-123456,seller-v:secret-s-123456"

        now = datetime.utcnow()
        db_session.add(
            CapacityModel(
                identity_id="buyer-v",
                total_locked_usdc=50.0,
                total_bill_credits=50.0,
                available_credits=50.0,
                reserved_credits=0.0,
                in_progress_credits=0.0,
                confirmed_progress_credits=0.0,
                disputed_credits=0.0,
                pending_settlement_credits=0.0,
                burned_credits=0.0,
                released_credits=0.0,
                updated_at=now,
            )
        )
        await db_session.flush()

        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        body = _voucher_body(buyer="buyer-v", seller="seller-v", nonce="nonce-ledger-1")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            bad = await client.post(
                "/v1/vouchers",
                json=body,
                headers={"X-Karma-Api-Key": "karma_seller-v_secret-s-123456"},
            )
            assert bad.status_code == 403

            ok = await client.post(
                "/v1/vouchers",
                json=body,
                headers={"X-Karma-Api-Key": "karma_buyer-v_secret-b-123456"},
            )
            assert ok.status_code == 201, ok.text
    finally:
        settings.auth_enforce_protected_routes = original_enforce
        settings.ledger_require_party_actor = original_ledger
        settings.auth_api_keys = original_keys
        app.dependency_overrides.clear()
