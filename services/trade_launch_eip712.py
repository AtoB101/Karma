"""EIP-712 typed data for trade order launch (Phase 1 — Open Wallet signing)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

DOMAIN_NAME = "KarmaTradeLaunch"
DOMAIN_VERSION = "1"

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_ZERO_BYTES32 = "0x" + "00" * 32


def _as_bytes32_hex(value: str | None) -> str:
    if not value or not str(value).strip():
        return _ZERO_BYTES32
    v = str(value).strip().lower()
    if v.startswith("0x"):
        v = v[2:]
    if not _HEX64.fullmatch(v):
        raise ValueError("hash fields must be 64 hex chars (optionally 0x-prefixed)")
    return "0x" + v


def _usdc_micro(amount: float) -> int:
    return int(round(float(amount) * 1_000_000))


def _precision_scaled(task_precision: float) -> int:
    return int(round(float(task_precision) * 1_000_000))


def build_trade_launch_typed_data(
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_fingerprint: str,
    amount: float,
    task_type: str,
    task_precision: float,
    launch_nonce: str,
    deadline_unix: int,
    chain_id: int,
    verifying_contract: str,
    chain_anchor_hash: str | None = None,
) -> dict[str, Any]:
    """Full EIP-712 payload for ``encode_typed_data(full_message=...)``."""
    vc = verifying_contract.strip()
    if not vc.startswith("0x") or len(vc) != 42:
        raise ValueError("verifying_contract must be a 20-byte 0x-prefixed address")

    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TradeLaunchIntent": [
                {"name": "buyerIdentityId", "type": "string"},
                {"name": "sellerIdentityId", "type": "string"},
                {"name": "requirementFingerprint", "type": "bytes32"},
                {"name": "amountMicro", "type": "uint256"},
                {"name": "taskType", "type": "string"},
                {"name": "taskPrecisionMicro", "type": "uint256"},
                {"name": "chainAnchorHash", "type": "bytes32"},
                {"name": "launchNonce", "type": "string"},
                {"name": "deadlineUnix", "type": "uint256"},
            ],
        },
        "primaryType": "TradeLaunchIntent",
        "domain": {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": int(chain_id),
            "verifyingContract": vc,
        },
        "message": {
            "buyerIdentityId": buyer_identity_id,
            "sellerIdentityId": seller_identity_id,
            "requirementFingerprint": _as_bytes32_hex(requirement_fingerprint),
            "amountMicro": _usdc_micro(amount),
            "taskType": task_type,
            "taskPrecisionMicro": _precision_scaled(task_precision),
            "chainAnchorHash": _as_bytes32_hex(chain_anchor_hash),
            "launchNonce": launch_nonce,
            "deadlineUnix": int(deadline_unix),
        },
    }


def sign_trade_launch_typed_data(*, private_key: str | bytes, typed_data: dict[str, Any]) -> str:
    msg = encode_typed_data(full_message=typed_data)
    signed = Account.sign_message(msg, private_key=private_key)
    sig = signed.signature
    if isinstance(sig, bytes):
        return "0x" + sig.hex()
    text = str(sig)
    return text if text.startswith("0x") else "0x" + text


def verify_trade_launch_buyer_signature(
    *,
    buyer_wallet_address: str,
    buyer_signature: str,
    typed_data: dict[str, Any],
) -> None:
    sig = (buyer_signature or "").strip()
    if not sig.startswith("0x") or len(sig) < 130:
        raise ValueError("buyer_signature must be a 0x-prefixed ECDSA signature")

    msg = encode_typed_data(full_message=typed_data)
    try:
        recovered = Account.recover_message(msg, signature=bytes.fromhex(sig[2:]))
    except Exception as exc:
        raise ValueError("invalid buyer_signature (recover failed)") from exc

    expected = buyer_wallet_address.strip().lower()
    if recovered.lower() != expected:
        raise ValueError("buyer_signature does not match bound buyer wallet")


def default_launch_deadline_unix() -> int:
    from config.settings import settings

    ttl = int(getattr(settings, "trade_launch_signature_ttl_seconds", 600) or 600)
    return int(datetime.now(timezone.utc).timestamp()) + ttl
