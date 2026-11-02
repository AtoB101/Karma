"""Order contract: canonical terms, termsHash, and dual-party signatures.

A binding order contract is the ruling artifact when a trade goes wrong. Both
sides commit to the *same* canonical terms before money moves:

- The terms are normalized into a stable canonical JSON and hashed to a
  ``terms_hash`` (SHA-256, 64 hex chars).
- The buyer signs the ``termsHash`` with an EIP-712 wallet signature.
- The worker (agent) signs the ``termsHash`` with its Ed25519 key.
- ``bind`` anchors ``termsHash`` on-chain as the binding ``scopeHash``.

Only the terms hash is stored on-chain; the full terms live off-chain and are
fetched by ``task_id`` for dispute resolution.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from core.schemas import TaskContract

DOMAIN_NAME = "KarmaOrderContract"
DOMAIN_VERSION = "1"

STATUS_DRAFT = "draft"
STATUS_BUYER_SIGNED = "buyer_signed"
STATUS_SIGNED = "signed"


def _fmt_amount(amount: float) -> str:
    """Fixed 6-decimal string; on-chain USDC uses 6 decimals, never float math."""
    return f"{float(amount):.6f}"


def _iso(dt: datetime) -> str:
    """Normalize to naive UTC + 'Z' so create-time and read-back hashes match."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def build_terms(contract: TaskContract) -> dict[str, Any]:
    """Canonical terms dict. Field order is irrelevant (canonical JSON sorts keys)."""
    # worker_agent_id is intentionally NOT part of terms: the worker is assigned
    # after creation, and the worker's commitment is its own Ed25519 signature
    # (keyed to the worker), not a mutable assignment field.
    return {
        "task_id": contract.task_id,
        "client_agent_id": contract.client_agent_id,
        "title": contract.title,
        "description": contract.description,
        "expected_output_schema": contract.expected_output_schema,
        "expected_step_count": int(contract.expected_step_count),
        "escrow_amount": _fmt_amount(contract.escrow_amount),
        "currency": contract.currency,
        "deadline_at": _iso(contract.deadline_at),
        "quality_standard": contract.quality_standard or "",
        "inspection_standard": contract.inspection_standard or "",
        "shipment_terms": contract.shipment_terms or "",
        "delivery_criteria": contract.delivery_criteria or "",
        "penalty": contract.penalty or "",
        "arbitration_rules": contract.arbitration_rules or "",
    }


def canonical_terms_json(terms: dict[str, Any]) -> str:
    return json.dumps(terms, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def terms_hash_hex(terms: dict[str, Any]) -> str:
    raw = canonical_terms_json(terms).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def terms_hash_bytes32(terms_hash: str) -> str:
    """Normalize a 64-hex terms hash to a 0x-prefixed bytes32 string."""
    h = (terms_hash or "").strip().lower().removeprefix("0x")
    if len(h) != 64:
        raise ValueError("terms_hash must be 64 hex chars (optionally 0x-prefixed)")
    return "0x" + h


# ---------------------------------------------------------------------------
# Buyer signature — EIP-712 wallet signature over termsHash + taskId
# ---------------------------------------------------------------------------

def build_buyer_typed_data(
    terms_hash: str,
    task_id: str,
    chain_id: int,
    verifying_contract: str,
) -> dict[str, Any]:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "OrderContract": [
                {"name": "termsHash", "type": "bytes32"},
                {"name": "taskId", "type": "string"},
            ],
        },
        "primaryType": "OrderContract",
        "domain": {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": int(chain_id),
            "verifyingContract": verifying_contract,
        },
        "message": {
            "termsHash": terms_hash_bytes32(terms_hash),
            "taskId": task_id,
        },
    }


def sign_buyer(
    *,
    private_key: str | bytes,
    terms_hash: str,
    task_id: str,
    chain_id: int,
    verifying_contract: str = "0x0000000000000000000000000000000000000000",
) -> str:
    data = build_buyer_typed_data(terms_hash, task_id, chain_id, verifying_contract)
    msg = encode_typed_data(full_message=data)
    signed = Account.sign_message(msg, private_key=private_key)
    sig = signed.signature
    return "0x" + sig.hex() if isinstance(sig, bytes) else str(sig)


def verify_buyer_signature(
    *,
    buyer_address: str,
    buyer_signature: str,
    terms_hash: str,
    task_id: str,
    chain_id: int,
    verifying_contract: str = "0x0000000000000000000000000000000000000000",
) -> None:
    """Raise ValueError if the buyer signature is missing/invalid or mismatched."""
    sig = (buyer_signature or "").strip()
    if not sig.startswith("0x") or len(sig) < 130:
        raise ValueError("buyer_signature must be a 0x-prefixed ECDSA signature")
    data = build_buyer_typed_data(terms_hash, task_id, chain_id, verifying_contract)
    msg = encode_typed_data(full_message=data)
    try:
        recovered = Account.recover_message(msg, signature=bytes.fromhex(sig[2:]))
    except Exception as exc:
        raise ValueError("invalid buyer_signature (recover failed)") from exc
    if recovered.lower() != (buyer_address or "").strip().lower():
        raise ValueError("buyer_signature does not match buyer_address")


# ---------------------------------------------------------------------------
# Worker signature — Ed25519 signature over termsHash bytes
# ---------------------------------------------------------------------------

def _terms_hash_raw(terms_hash: str) -> bytes:
    return bytes.fromhex((terms_hash or "").strip().lower().replace("0x", ""))


def sign_worker(terms_hash: str, private_key: Ed25519PrivateKey) -> tuple[str, str]:
    """Return (signature_b64, public_key_b64) for a worker signing termsHash."""
    sig = private_key.sign(_terms_hash_raw(terms_hash))
    pub = private_key.public_key().public_bytes_raw()
    return base64.b64encode(sig).decode(), base64.b64encode(pub).decode()


def verify_worker_signature(
    *,
    terms_hash: str,
    signature_b64: str,
    public_key_b64: str,
) -> bool:
    try:
        data = _terms_hash_raw(terms_hash)
        sig = base64.b64decode(signature_b64)
        raw_pub = base64.b64decode(public_key_b64)
        pub = Ed25519PublicKey.from_public_bytes(raw_pub)
        pub.verify(sig, data)
        return True
    except Exception:
        return False
