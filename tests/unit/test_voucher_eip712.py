"""Unit tests — EIP-712 Authorization Voucher signing."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from eth_account import Account

from services.voucher_eip712 import (
    sign_authorization_voucher,
    verify_authorization_voucher_buyer,
)


@pytest.mark.parametrize("bad_sig", ["", "0xabc", "0x" + "00" * 60])
def test_verify_rejects_bad_signatures(bad_sig: str):
    exp = datetime.utcnow() + timedelta(hours=1)
    with pytest.raises(ValueError):
        verify_authorization_voucher_buyer(
            buyer_wallet_address="0x" + "11" * 20,
            buyer_signature=bad_sig,
            buyer_identity_id="buyer-1",
            seller_identity_id="seller-1",
            amount=1.0,
            bill_credit_amount=1.0,
            currency="USDC",
            task_type="t",
            task_description_hash="aa" * 32,
            progress_rule_hash="bb" * 32,
            evidence_requirement_hash="cc" * 32,
            nonce="n1",
            expiry_time=exp,
            chain_id=1,
        )


def test_sign_and_verify_round_trip():
    acct = Account.create()
    exp = datetime.utcnow() + timedelta(hours=2)
    h = "dd" * 32
    sig = sign_authorization_voucher(
        private_key=acct.key,
        buyer_identity_id="id-buyer",
        seller_identity_id="id-seller",
        amount=10.5,
        bill_credit_amount=10.5,
        currency="USDC",
        task_type="api",
        task_description_hash=h,
        progress_rule_hash=h,
        evidence_requirement_hash=h,
        nonce="nonce-712",
        expiry_time=exp,
        chain_id=31337,
    )
    verify_authorization_voucher_buyer(
        buyer_wallet_address=acct.address,
        buyer_signature=sig,
        buyer_identity_id="id-buyer",
        seller_identity_id="id-seller",
        amount=10.5,
        bill_credit_amount=10.5,
        currency="USDC",
        task_type="api",
        task_description_hash=h,
        progress_rule_hash=h,
        evidence_requirement_hash=h,
        nonce="nonce-712",
        expiry_time=exp,
        chain_id=31337,
    )


def test_wrong_wallet_fails():
    alice = Account.create()
    bob = Account.create()
    exp = datetime.utcnow() + timedelta(hours=1)
    h = "ee" * 32
    sig = sign_authorization_voucher(
        private_key=alice.key,
        buyer_identity_id="b",
        seller_identity_id="s",
        amount=1.0,
        bill_credit_amount=1.0,
        currency="USDC",
        task_type="t",
        task_description_hash=h,
        progress_rule_hash=h,
        evidence_requirement_hash=h,
        nonce="x",
        expiry_time=exp,
        chain_id=1,
    )
    with pytest.raises(ValueError, match="does not match"):
        verify_authorization_voucher_buyer(
            buyer_wallet_address=bob.address,
            buyer_signature=sig,
            buyer_identity_id="b",
            seller_identity_id="s",
            amount=1.0,
            bill_credit_amount=1.0,
            currency="USDC",
            task_type="t",
            task_description_hash=h,
            progress_rule_hash=h,
            evidence_requirement_hash=h,
            nonce="x",
            expiry_time=exp,
            chain_id=1,
        )
