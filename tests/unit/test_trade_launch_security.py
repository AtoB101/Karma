"""Trade launch EIP-712 security regressions (KSA-TL-*)."""

from __future__ import annotations

import time

import pytest
from eth_account import Account
from fastapi import HTTPException

from config.settings import settings
from services.trade_launch_signing import build_sign_context, verify_trade_launch_commitment
from services.trade_launch_eip712 import sign_trade_launch_typed_data


@pytest.mark.asyncio
async def test_expired_trade_launch_attestation_rejected():
    from services.trade_launch_signing import (
        build_trade_launch_attestation,
        verify_trade_launch_attestation_signature,
    )
    from sdk.signing_backend import TradeLaunchSignContext

    acct = Account.create()
    ctx = TradeLaunchSignContext(
        buyer_identity_id="b",
        seller_identity_id="s",
        requirement_fingerprint="f" * 64,
        amount=1.0,
        task_type="api.generic",
        task_precision=1.0,
        launch_nonce="n1",
        deadline_unix=int(time.time()) - 3600,
        chain_id=11155111,
        verifying_contract="0x0000000000000000000000000000000000000000",
    )
    sig = sign_trade_launch_typed_data(private_key=acct.key, typed_data=ctx.to_typed_data())
    att = build_trade_launch_attestation(ctx=ctx, buyer_wallet_address=acct.address)

    with pytest.raises(ValueError, match="expired"):
        verify_trade_launch_attestation_signature(attestation=att, buyer_signature=sig)


@pytest.mark.asyncio
async def test_wrong_wallet_trade_launch_signature_rejected(db_session, monkeypatch):
    monkeypatch.setattr(settings, "trade_launch_require_eip712", True)
    signer = Account.create()
    other = Account.create()
    from db.models.orm import IdentityProfileModel
    from datetime import datetime

    buyer, seller = "tl-buyer-wrong", "tl-seller-wrong"
    db_session.add(
        IdentityProfileModel(
            identity_id=buyer,
            display_id="TL-WRONG",
            legal_identity_status="bound",
            status="active",
            bound_wallet_address=other.address,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    req = "generic task 3 USDC precision 1.0"
    ctx = build_sign_context(
        buyer_identity_id=buyer,
        seller_identity_id=seller,
        requirement_text=req,
        amount=3.0,
        task_type="api.generic",
        task_precision=1.0,
        launch_idempotency_key="wrong-wallet-nonce",
        chain_anchor_hash=None,
    )
    sig = sign_trade_launch_typed_data(private_key=signer.key, typed_data=ctx.to_typed_data())

    with pytest.raises(HTTPException) as exc:
        await verify_trade_launch_commitment(
            db_session,
            buyer_identity_id=buyer,
            seller_identity_id=seller,
            requirement_text=req,
            amount=3.0,
            task_type="api.generic",
            task_precision=1.0,
            buyer_signature=sig,
            launch_idempotency_key="wrong-wallet-nonce",
            chain_anchor_hash=None,
        )
    assert exc.value.status_code == 403
