"""Sign x402 PAYMENT-SIGNATURE payloads with configured EVM key."""

from __future__ import annotations

import base64
import json
import secrets
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct

from sdk.x402.models import PaymentProof, PaymentRequiredAccept


def usdc_amount_to_atomic(amount_usdc: float) -> int:
    """USDC 6 decimals."""
    if amount_usdc < 0:
        raise ValueError("amount must be non-negative")
    return int(round(amount_usdc * 1_000_000))


def build_payment_payload(
    *,
    accept: PaymentRequiredAccept,
    resource_url: str,
    payer_address: str,
) -> dict[str, Any]:
    return {
        "x402Version": 1,
        "scheme": accept.scheme,
        "network": accept.network,
        "asset": accept.asset,
        "payTo": accept.pay_to,
        "maxAmountRequired": accept.max_amount_required,
        "resource": resource_url or accept.resource,
        "payer": payer_address,
        "nonce": secrets.token_hex(16),
    }


def sign_payment_payload(*, private_key: str, payload: dict[str, Any]) -> tuple[str, str]:
    """Return (payment_signature_b64, payload_digest_hex)."""
    acct = Account.from_key(private_key.strip())
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signed = acct.sign_message(encode_defunct(text=canonical))
    sig_hex = signed.signature.hex()
    if not sig_hex.startswith("0x"):
        sig_hex = "0x" + sig_hex
    b64 = base64.urlsafe_b64encode(
        json.dumps(
            {"payload": payload, "signature": sig_hex, "signer": acct.address},
            separators=(",", ":"),
        ).encode()
    ).decode()
    digest = "0x" + signed.message_hash.hex()
    return b64, digest

