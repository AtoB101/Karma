"""Trade launch EIP-712 signing (Phase 1)."""

from __future__ import annotations

from eth_account import Account

from services.trade_launch_eip712 import (
    build_trade_launch_typed_data,
    sign_trade_launch_typed_data,
    verify_trade_launch_buyer_signature,
)
from sdk.signing_backend import TradeLaunchSignContext, get_signing_backend


def test_trade_launch_sign_and_verify_roundtrip():
    acct = Account.create()
    typed = build_trade_launch_typed_data(
        buyer_identity_id="buyer-a",
        seller_identity_id="seller-b",
        requirement_fingerprint="a" * 64,
        amount=12.5,
        task_type="api.caption",
        task_precision=1.2,
        launch_nonce="idem-test-001",
        deadline_unix=4_000_000_000,
        chain_id=11155111,
        verifying_contract="0x0000000000000000000000000000000000000000",
        chain_anchor_hash=None,
    )
    sig = sign_trade_launch_typed_data(private_key=acct.key, typed_data=typed)
    verify_trade_launch_buyer_signature(
        buyer_wallet_address=acct.address,
        buyer_signature=sig,
        typed_data=typed,
    )


def test_env_signing_backend(monkeypatch):
    acct = Account.create()
    monkeypatch.setattr(
        "config.settings.settings.karma_signing_backend",
        "env",
    )
    raw_key = acct.key
    hex_key = raw_key.hex() if hasattr(raw_key, "hex") else str(raw_key)
    monkeypatch.setattr("config.settings.settings.karma_signing_dev_private_key", hex_key)
    backend = get_signing_backend()
    assert backend.backend_id == "env"
    ctx = TradeLaunchSignContext(
        buyer_identity_id="b",
        seller_identity_id="s",
        requirement_fingerprint="b" * 64,
        amount=1.0,
        task_type="api.generic",
        task_precision=1.0,
        launch_nonce="n1",
        deadline_unix=4_000_000_000,
        chain_id=11155111,
        verifying_contract="0x0000000000000000000000000000000000000000",
    )
    sig = backend.sign_trade_launch(ctx)
    verify_trade_launch_buyer_signature(
        buyer_wallet_address=acct.address,
        buyer_signature=sig,
        typed_data=ctx.to_typed_data(),
    )
