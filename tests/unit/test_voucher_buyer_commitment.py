"""Unified voucher buyer commitment (trade launch vs authorization voucher)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from eth_account import Account

from config.settings import settings
from tests.helpers.time_test_utils import future_deadline_unix, utc_naive_datetime
from services.trade_launch_eip712 import sign_trade_launch_typed_data
from services.trade_launch_signing import build_trade_launch_attestation
from sdk.signing_backend import TradeLaunchSignContext
from services.voucher_buyer_commitment import assert_buyer_commitment_for_voucher


def test_trade_launch_attestation_satisfies_voucher_commitment(monkeypatch):
    monkeypatch.setattr(settings, "trade_launch_require_eip712", True)
    monkeypatch.setattr(settings, "voucher_require_eip712", True)

    acct = Account.create()
    ctx = TradeLaunchSignContext(
        buyer_identity_id="buyer-x",
        seller_identity_id="seller-y",
        requirement_fingerprint="c" * 64,
        amount=10.0,
        task_type="api.caption",
        task_precision=1.0,
        launch_nonce="nonce-abc",
        deadline_unix=future_deadline_unix(offset_seconds=600),
        chain_id=11155111,
        verifying_contract="0x0000000000000000000000000000000000000000",
    )
    sig = sign_trade_launch_typed_data(private_key=acct.key, typed_data=ctx.to_typed_data())
    att = build_trade_launch_attestation(ctx=ctx, buyer_wallet_address=acct.address)

    mode = assert_buyer_commitment_for_voucher(
        buyer_signature=sig,
        buyer_wallet_address=acct.address,
        progress_rule_spec={"trade_launch_attestation": att},
        buyer_identity_id="buyer-x",
        seller_identity_id="seller-y",
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
