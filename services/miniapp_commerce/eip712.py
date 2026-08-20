"""EIP-712 typed data helpers for Intent Package / Bill (off-chain signing surface)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


DOMAIN = {
    "name": "KarmaTelegramMiniApp",
    "version": "1",
    "chainId": 0,  # filled at runtime
    "verifyingContract": "0x0000000000000000000000000000000000000000",
}

INTENT_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "IntentPackage": [
        {"name": "intentId", "type": "string"},
        {"name": "offerId", "type": "string"},
        {"name": "buyer", "type": "address"},
        {"name": "seller", "type": "address"},
        {"name": "token", "type": "address"},
        {"name": "amount", "type": "uint256"},
        {"name": "deadline", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
    ],
}


def build_intent_typed_data(
    *,
    chain_id: int,
    intent_id: str,
    offer_id: str,
    buyer: str,
    seller: str,
    token: str,
    amount: int,
    deadline: int,
    nonce: int,
    verifying_contract: str = "0x0000000000000000000000000000000000000000",
) -> dict[str, Any]:
    domain = {
        **DOMAIN,
        "chainId": int(chain_id),
        "verifyingContract": verifying_contract,
    }
    message = {
        "intentId": intent_id,
        "offerId": offer_id,
        "buyer": buyer,
        "seller": seller,
        "token": token,
        "amount": str(int(amount)),
        "deadline": int(deadline),
        "nonce": int(nonce),
    }
    return {
        "types": INTENT_TYPES,
        "primaryType": "IntentPackage",
        "domain": domain,
        "message": message,
    }


def digest_typed_data(typed: dict[str, Any]) -> str:
    """Deterministic digest for audit / mock sign (not a full EIP-712 hash)."""
    raw = json.dumps(typed, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
