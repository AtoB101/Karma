"""Quote / Negotiation / Intent Package / Bill for MiniApp commerce."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


_LOCK = Lock()


@dataclass
class Quote:
    quote_id: str
    offer_id: str
    buyer_identity_id: str
    seller_identity_id: str
    amount_usdc: str
    terms: dict
    status: str = "open"  # open|accepted|rejected|expired
    created_at: int = 0
    expires_at: int = 0


@dataclass
class Negotiation:
    negotiation_id: str
    quote_id: str
    messages: list[dict] = field(default_factory=list)
    status: str = "open"  # open|agreed|failed
    agreed_amount_usdc: str | None = None
    created_at: int = 0


@dataclass
class IntentPackage:
    intent_id: str
    order_id: str | None
    typed_data: dict
    digest: str
    buyer_signature: str | None = None
    seller_signature: str | None = None
    status: str = "draft"  # draft|buyer_signed|fully_signed
    created_at: int = 0


@dataclass
class Bill:
    bill_id: str
    order_id: str
    buyer_wallet: str | None
    seller_wallet: str | None
    amount_usdc: str
    status: str = "created"  # created|locked|settled|refunded|disputed
    binding_id: int | None = None
    created_at: int = 0


_QUOTES: dict[str, Quote] = {}
_NEGO: dict[str, Negotiation] = {}
_INTENTS: dict[str, IntentPackage] = {}
_BILLS: dict[str, Bill] = {}


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def create_quote(
    *,
    offer_id: str,
    buyer_identity_id: str,
    seller_identity_id: str,
    amount_usdc: str,
    terms: dict | None = None,
    ttl_seconds: int = 3600,
) -> Quote:
    now = int(time.time())
    q = Quote(
        quote_id=_id("quo"),
        offer_id=offer_id,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        amount_usdc=str(amount_usdc),
        terms=dict(terms or {}),
        created_at=now,
        expires_at=now + ttl_seconds,
    )
    with _LOCK:
        _QUOTES[q.quote_id] = q
    return q


def start_negotiation(quote_id: str) -> Negotiation:
    if quote_id not in _QUOTES:
        raise KeyError("quote not found")
    n = Negotiation(negotiation_id=_id("neg"), quote_id=quote_id, created_at=int(time.time()))
    with _LOCK:
        _NEGO[n.negotiation_id] = n
    return n


def propose(negotiation_id: str, *, role: str, amount_usdc: str, note: str = "") -> Negotiation:
    with _LOCK:
        n = _NEGO[negotiation_id]
        n.messages.append(
            {"at": int(time.time()), "role": role, "amount_usdc": str(amount_usdc), "note": note}
        )
        return n


def agree(negotiation_id: str, *, amount_usdc: str) -> Negotiation:
    with _LOCK:
        n = _NEGO[negotiation_id]
        n.status = "agreed"
        n.agreed_amount_usdc = str(amount_usdc)
        q = _QUOTES[n.quote_id]
        q.amount_usdc = str(amount_usdc)
        q.status = "accepted"
        return n


def build_intent_package(
    *,
    order_id: str,
    buyer_wallet: str,
    seller_wallet: str,
    amount_usdc: str,
    scope: dict,
    chain_id: int | None = None,
) -> IntentPackage:
    """EIP-712 typed data for bilateral intent (structure; client signs)."""
    cid = int(chain_id or os.getenv("KARMA_SIWE_CHAIN_ID") or "11155111")
    verifying_contract = (os.getenv("KARMA_BILATERAL") or "0x0000000000000000000000000000000000000000").lower()
    typed = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "KarmaIntent": [
                {"name": "orderId", "type": "string"},
                {"name": "buyer", "type": "address"},
                {"name": "seller", "type": "address"},
                {"name": "amountUsdc", "type": "string"},
                {"name": "scopeHash", "type": "bytes32"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "KarmaIntent",
        "domain": {
            "name": "KarmaIntent",
            "version": "1",
            "chainId": cid,
            "verifyingContract": verifying_contract,
        },
        "message": {
            "orderId": order_id,
            "buyer": buyer_wallet.lower(),
            "seller": seller_wallet.lower(),
            "amountUsdc": str(amount_usdc),
            "scopeHash": "0x" + hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
            "deadline": int(time.time()) + 86400,
        },
    }
    digest = hashlib.sha256(json.dumps(typed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    pkg = IntentPackage(
        intent_id=_id("int"),
        order_id=order_id,
        typed_data=typed,
        digest=digest,
        created_at=int(time.time()),
    )
    with _LOCK:
        _INTENTS[pkg.intent_id] = pkg
    return pkg


def sign_intent(intent_id: str, *, role: str, signature: str) -> IntentPackage:
    with _LOCK:
        pkg = _INTENTS[intent_id]
        if role == "buyer":
            pkg.buyer_signature = signature
            pkg.status = "buyer_signed" if not pkg.seller_signature else "fully_signed"
        elif role == "seller":
            pkg.seller_signature = signature
            pkg.status = "fully_signed" if pkg.buyer_signature else "draft"
        else:
            raise ValueError("role must be buyer|seller")
        if pkg.buyer_signature and pkg.seller_signature:
            pkg.status = "fully_signed"
        return pkg


def create_bill(
    *,
    order_id: str,
    buyer_wallet: str | None,
    seller_wallet: str | None,
    amount_usdc: str,
) -> Bill:
    b = Bill(
        bill_id=_id("bill"),
        order_id=order_id,
        buyer_wallet=(buyer_wallet.lower() if buyer_wallet else None),
        seller_wallet=(seller_wallet.lower() if seller_wallet else None),
        amount_usdc=str(amount_usdc),
        created_at=int(time.time()),
    )
    with _LOCK:
        _BILLS[b.bill_id] = b
    return b


def get_bill_by_order(order_id: str) -> Bill | None:
    with _LOCK:
        for b in _BILLS.values():
            if b.order_id == order_id:
                return b
    return None


def update_bill(order_id: str, **fields: Any) -> Bill:
    b = get_bill_by_order(order_id)
    if not b:
        raise KeyError("bill not found")
    for k, v in fields.items():
        if hasattr(b, k):
            setattr(b, k, v)
    return b


def get_quote(quote_id: str) -> Quote | None:
    with _LOCK:
        return _QUOTES.get(quote_id)


def get_intent(intent_id: str) -> IntentPackage | None:
    with _LOCK:
        return _INTENTS.get(intent_id)


def reset_for_tests() -> None:
    with _LOCK:
        _QUOTES.clear()
        _NEGO.clear()
        _INTENTS.clear()
        _BILLS.clear()
