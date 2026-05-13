"""P0 — EIP-712 typed-data signing for Authorization Voucher (buyer commitment)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

DOMAIN_NAME = "KarmaAuthorizationVoucher"
DOMAIN_VERSION = "1"

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _as_bytes32_hex(value: str) -> str:
    v = (value or "").strip().lower()
    if v.startswith("0x"):
        v = v[2:]
    if not _HEX64.fullmatch(v):
        raise ValueError("hash fields must be 64 hex chars (optionally 0x-prefixed)")
    return "0x" + v


def _usdc_micro(amount: float) -> int:
    return int(round(float(amount) * 1_000_000))


def build_authorization_voucher_typed_data(
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    amount: float,
    bill_credit_amount: float,
    currency: str,
    task_type: str,
    task_description_hash: str,
    progress_rule_hash: str,
    evidence_requirement_hash: str,
    nonce: str,
    expiry_time: datetime,
    chain_id: int,
    verifying_contract: str,
) -> dict[str, Any]:
    """Full EIP-712 payload for `encode_typed_data(full_message=...)`."""
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
            "AuthorizationVoucher": [
                {"name": "buyerIdentityId", "type": "string"},
                {"name": "sellerIdentityId", "type": "string"},
                {"name": "billCreditMicro", "type": "uint256"},
                {"name": "amountMicro", "type": "uint256"},
                {"name": "currency", "type": "string"},
                {"name": "taskType", "type": "string"},
                {"name": "taskDescriptionHash", "type": "bytes32"},
                {"name": "progressRuleHash", "type": "bytes32"},
                {"name": "evidenceRequirementHash", "type": "bytes32"},
                {"name": "nonce", "type": "string"},
                {"name": "expiryUnix", "type": "uint256"},
            ],
        },
        "primaryType": "AuthorizationVoucher",
        "domain": {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": int(chain_id),
            "verifyingContract": vc,
        },
        "message": {
            "buyerIdentityId": buyer_identity_id,
            "sellerIdentityId": seller_identity_id,
            "billCreditMicro": _usdc_micro(bill_credit_amount),
            "amountMicro": _usdc_micro(amount),
            "currency": currency,
            "taskType": task_type,
            "taskDescriptionHash": _as_bytes32_hex(task_description_hash),
            "progressRuleHash": _as_bytes32_hex(progress_rule_hash),
            "evidenceRequirementHash": _as_bytes32_hex(evidence_requirement_hash),
            "nonce": nonce,
            "expiryUnix": int(expiry_time.replace(tzinfo=None).timestamp()),
        },
    }


def sign_authorization_voucher(
    *,
    private_key: str | bytes,
    buyer_identity_id: str,
    seller_identity_id: str,
    amount: float,
    bill_credit_amount: float,
    currency: str,
    task_type: str,
    task_description_hash: str,
    progress_rule_hash: str,
    evidence_requirement_hash: str,
    nonce: str,
    expiry_time: datetime,
    chain_id: int,
    verifying_contract: str = "0x0000000000000000000000000000000000000000",
) -> str:
    """Returns 0x-hex ECDSA signature (65 bytes) suitable for `buyer_signature` API field."""
    data = build_authorization_voucher_typed_data(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        amount=amount,
        bill_credit_amount=bill_credit_amount,
        currency=currency,
        task_type=task_type,
        task_description_hash=task_description_hash,
        progress_rule_hash=progress_rule_hash,
        evidence_requirement_hash=evidence_requirement_hash,
        nonce=nonce,
        expiry_time=expiry_time,
        chain_id=chain_id,
        verifying_contract=verifying_contract,
    )
    msg = encode_typed_data(full_message=data)
    signed = Account.sign_message(msg, private_key=private_key)
    sig = signed.signature
    if isinstance(sig, bytes):
        return "0x" + sig.hex()
    return str(sig) if str(sig).startswith("0x") else "0x" + str(sig)


def verify_authorization_voucher_buyer(
    *,
    buyer_wallet_address: str,
    buyer_signature: str,
    buyer_identity_id: str,
    seller_identity_id: str,
    amount: float,
    bill_credit_amount: float,
    currency: str,
    task_type: str,
    task_description_hash: str,
    progress_rule_hash: str,
    evidence_requirement_hash: str,
    nonce: str,
    expiry_time: datetime,
    chain_id: int,
    verifying_contract: str = "0x0000000000000000000000000000000000000000",
) -> None:
    """Raises ValueError if signature missing/invalid or signer != buyer_wallet_address."""
    sig = (buyer_signature or "").strip()
    if not sig.startswith("0x") or len(sig) < 130:
        raise ValueError("buyer_signature must be a 0x-prefixed ECDSA signature")

    data = build_authorization_voucher_typed_data(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        amount=amount,
        bill_credit_amount=bill_credit_amount,
        currency=currency,
        task_type=task_type,
        task_description_hash=task_description_hash,
        progress_rule_hash=progress_rule_hash,
        evidence_requirement_hash=evidence_requirement_hash,
        nonce=nonce,
        expiry_time=expiry_time,
        chain_id=chain_id,
        verifying_contract=verifying_contract,
    )
    msg = encode_typed_data(full_message=data)
    try:
        recovered = Account.recover_message(msg, signature=bytes.fromhex(sig[2:]))
    except Exception as exc:
        raise ValueError("invalid buyer_signature (recover failed)") from exc

    expected = buyer_wallet_address.strip().lower()
    if recovered.lower() != expected:
        raise ValueError("buyer_signature does not match buyer_wallet_address")
