"""
Regression tests for Sentinel audit (2026-05-18) non-blocking failures.

Those failures were test-harness issues, not production defects — but we keep
explicit regressions so CI stays green in all timezones and with OpenClaw relax env.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from config.settings import settings
from db.session import get_db
from httptest import post_minimal_contract
from services.trade_launch_eip712 import sign_trade_launch_typed_data, verify_trade_launch_buyer_signature
from services.trade_launch_signing import build_trade_launch_attestation
from services.voucher_buyer_commitment import assert_buyer_commitment_for_voucher
from sdk.signing_backend import TradeLaunchSignContext
from tests.helpers.time_test_utils import future_deadline_unix, utc_naive_datetime

from eth_account import Account


def _pin_strict_receipt_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production-like receipt policy (no OpenClaw relax)."""
    monkeypatch.setattr(settings, "receipt_require_signature", True)
    monkeypatch.setattr(settings, "openclaw_local_phase1_auto_relax", False)
    monkeypatch.setattr(settings, "openclaw_relax_delivery_signatures", False)
    monkeypatch.setattr(settings, "trade_launch_require_eip712", True)


@pytest.mark.asyncio
async def test_missing_receipt_signature_rejected_under_strict_policy(client, monkeypatch):
    """Sentinel #1: missing signature must 400 when relax is off (production path)."""
    _pin_strict_receipt_policy(monkeypatch)
    now = utc_naive_datetime()
    await post_minimal_contract(
        client,
        task_id="task-sentinel-missing-sig",
        client_agent_id="client-sentinel-missing-sig",
        escrow_amount=50.0,
        expected_step_count=1,
    )
    resp = await client.post(
        "/v1/receipts",
        json={
            "task_id": "task-sentinel-missing-sig",
            "agent_id": "worker-001",
            "step_index": 1,
            "tool_name": "caption.generate",
            "input_hash": "a" * 64,
            "output_hash": "b" * 64,
            "started_at": now.isoformat(),
            "ended_at": (now + timedelta(milliseconds=50)).isoformat(),
            "duration_ms": 50,
            "status": "success",
        },
    )
    assert resp.status_code == 400
    assert "signature" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_missing_receipt_signature_allowed_only_when_relax_explicit(client, db_session, monkeypatch):
    """Documents why integration tests must pin strict policy when relax env is set."""
    monkeypatch.setattr(settings, "openclaw_local_phase1_auto_relax", True)
    monkeypatch.setattr(settings, "trade_launch_require_eip712", False)
    monkeypatch.setattr(settings, "receipt_require_signature", True)
    monkeypatch.setattr(settings, "openclaw_relax_delivery_signatures", None)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    now = utc_naive_datetime()
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await post_minimal_contract(
                ac,
                task_id="task-sentinel-relax-on",
                client_agent_id="client-sentinel-relax",
                escrow_amount=10.0,
                expected_step_count=1,
            )
            resp = await ac.post(
                "/v1/receipts",
                json={
                    "task_id": "task-sentinel-relax-on",
                    "agent_id": "worker-001",
                    "step_index": 1,
                    "tool_name": "t",
                    "input_hash": "a" * 64,
                    "output_hash": "b" * 64,
                    "started_at": now.isoformat(),
                    "ended_at": (now + timedelta(milliseconds=1)).isoformat(),
                    "duration_ms": 1,
                    "status": "success",
                },
            )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.clear()


def test_trade_launch_attestation_deadline_stable_in_any_timezone(monkeypatch):
    """Sentinel #2: deadline must be UTC-based so GMT+7 CI does not expire immediately."""
    monkeypatch.setattr(settings, "trade_launch_require_eip712", True)
    monkeypatch.setattr(settings, "voucher_require_eip712", True)

    deadline = future_deadline_unix(offset_seconds=3600)
    assert deadline > future_deadline_unix(offset_seconds=0)

    acct = Account.create()
    ctx = TradeLaunchSignContext(
        buyer_identity_id="buyer-tz",
        seller_identity_id="seller-tz",
        requirement_fingerprint="c" * 64,
        amount=10.0,
        task_type="api.caption",
        task_precision=1.0,
        launch_nonce="nonce-tz",
        deadline_unix=deadline,
        chain_id=11155111,
        verifying_contract="0x0000000000000000000000000000000000000000",
    )
    sig = sign_trade_launch_typed_data(private_key=acct.key, typed_data=ctx.to_typed_data())
    verify_trade_launch_buyer_signature(
        buyer_wallet_address=acct.address,
        buyer_signature=sig,
        typed_data=ctx.to_typed_data(),
    )
    att = build_trade_launch_attestation(ctx=ctx, buyer_wallet_address=acct.address)
    mode = assert_buyer_commitment_for_voucher(
        buyer_signature=sig,
        buyer_wallet_address=acct.address,
        progress_rule_spec={"trade_launch_attestation": att},
        buyer_identity_id="buyer-tz",
        seller_identity_id="seller-tz",
        amount=10.0,
        bill_credit_amount=10.0,
        currency="USDC",
        task_type="api.caption",
        task_description_hash="d" * 64,
        progress_rule_hash="e" * 64,
        evidence_requirement_hash="f" * 64,
        nonce="n1",
        expiry_time=utc_naive_datetime(offset=timedelta(hours=1)),
    )
    assert mode == "trade_launch"
