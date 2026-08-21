"""MiniApp commerce order state machine (MVP).

Tracks Intent → Offer → Order → Lock → Evidence → Verify → Settle.
Settlement to Bilateral is gated by VerificationEngine PASS.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    SIGNED = "SIGNED"
    POLICY_CHECKED = "POLICY_CHECKED"
    LOCKED = "LOCKED"
    EXECUTED = "EXECUTED"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    VERIFIED = "VERIFIED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    REJECTED = "REJECTED"


@dataclass
class MiniAppOrder:
    order_id: str
    buyer_identity_id: str
    seller_identity_id: str | None
    builder_address: str | None  # BUILDER attribution for FeeBridge.developer
    intent: dict[str, Any]
    offer: dict[str, Any] | None = None
    status: OrderStatus = OrderStatus.DRAFT
    amount_usdc: str = "0"
    buyer_wallet: str | None = None
    seller_wallet: str | None = None
    binding_id: int | None = None
    evidence: dict[str, Any] | None = None
    verification_run_id: str | None = None
    created_at: int = 0
    updated_at: int = 0
    signatures: dict[str, str] = field(default_factory=dict)
    policy_result: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)


_LOCK = Lock()
_ORDERS: dict[str, MiniAppOrder] = {}


def _touch(order: MiniAppOrder, note: str) -> None:
    order.updated_at = int(time.time())
    order.history.append({"at": order.updated_at, "status": order.status.value, "note": note})


def create_order(
    *,
    buyer_identity_id: str,
    intent: dict[str, Any],
    buyer_wallet: str | None = None,
    builder_address: str | None = None,
) -> MiniAppOrder:
    oid = "ord_" + secrets.token_hex(10)
    order = MiniAppOrder(
        order_id=oid,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=None,
        builder_address=(builder_address.lower() if builder_address else None),
        intent=dict(intent),
        amount_usdc=str(intent.get("amount_usdc") or "0"),
        buyer_wallet=(buyer_wallet.lower() if buyer_wallet else None),
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )
    _touch(order, "created")
    with _LOCK:
        _ORDERS[oid] = order
    return order


def get_order(order_id: str) -> MiniAppOrder | None:
    with _LOCK:
        return _ORDERS.get(order_id)


def attach_offer(order_id: str, offer: dict[str, Any], *, seller_identity_id: str, seller_wallet: str | None = None) -> MiniAppOrder:
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    order.offer = dict(offer)
    order.seller_identity_id = seller_identity_id
    order.seller_wallet = (seller_wallet.lower() if seller_wallet else None)
    if offer.get("amount_usdc") is not None:
        order.amount_usdc = str(offer["amount_usdc"])
    if offer.get("builder_address"):
        order.builder_address = str(offer["builder_address"]).lower()
    order.status = OrderStatus.QUOTED
    _touch(order, "offer_attached")
    return order


def sign_order(order_id: str, *, role: str, signature: str) -> MiniAppOrder:
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    order.signatures[role] = signature
    if "buyer" in order.signatures and "seller" in order.signatures:
        order.status = OrderStatus.SIGNED
        _touch(order, "both_signed")
    else:
        _touch(order, f"signed:{role}")
    return order


def apply_policy(order_id: str, policy: dict[str, Any]) -> MiniAppOrder:
    """Payment policy check — Agent cannot bypass user limits."""
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.status not in {OrderStatus.SIGNED, OrderStatus.QUOTED, OrderStatus.POLICY_CHECKED}:
        raise ValueError(f"invalid status for policy: {order.status}")

    amount = float(order.amount_usdc or 0)
    single = float(policy.get("single_limit_usdc") or 1e18)
    daily = float(policy.get("daily_limit_usdc") or 1e18)
    spent_today = float(policy.get("spent_today_usdc") or 0)
    if policy.get("infinite_approve") is True:
        raise PermissionError("infinite USDC approve forbidden")
    if amount > single:
        order.status = OrderStatus.REJECTED
        order.policy_result = {"ok": False, "reason": "single_limit_exceeded"}
        _touch(order, "policy_rejected")
        raise PermissionError("single_limit_exceeded")
    if spent_today + amount > daily:
        order.status = OrderStatus.REJECTED
        order.policy_result = {"ok": False, "reason": "daily_limit_exceeded"}
        _touch(order, "policy_rejected")
        raise PermissionError("daily_limit_exceeded")

    allowed_agents = policy.get("allowed_agents") or []
    if allowed_agents and order.seller_identity_id and order.seller_identity_id not in allowed_agents:
        order.status = OrderStatus.REJECTED
        order.policy_result = {"ok": False, "reason": "agent_not_allowlisted"}
        _touch(order, "policy_rejected")
        raise PermissionError("agent_not_allowlisted")

    # Self-deal flag (GMV credit handled by karma8 Mirror; we still record)
    self_deal = bool(
        order.buyer_wallet and order.seller_wallet and order.buyer_wallet == order.seller_wallet
    )
    order.policy_result = {
        "ok": True,
        "self_deal": self_deal,
        "single_limit_usdc": str(single),
        "daily_limit_usdc": str(daily),
        "spent_today_usdc": str(spent_today),
    }
    order.status = OrderStatus.POLICY_CHECKED
    _touch(order, "policy_ok")
    return order


def mark_locked(order_id: str, *, binding_id: int | None = None) -> MiniAppOrder:
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.status != OrderStatus.POLICY_CHECKED:
        raise ValueError("policy check required before lock")
    order.binding_id = binding_id
    order.status = OrderStatus.LOCKED
    _touch(order, "locked")
    return order


def submit_evidence(order_id: str, evidence: dict[str, Any]) -> MiniAppOrder:
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.status not in {OrderStatus.LOCKED, OrderStatus.EXECUTED, OrderStatus.EVIDENCE_SUBMITTED}:
        raise ValueError("order must be locked before evidence")
    order.evidence = dict(evidence)
    order.status = OrderStatus.EVIDENCE_SUBMITTED
    _touch(order, "evidence_submitted")
    return order


def mark_verified(order_id: str, *, run_id: str) -> MiniAppOrder:
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    order.verification_run_id = run_id
    order.status = OrderStatus.VERIFIED
    _touch(order, "verified")
    return order


def mark_settled(order_id: str) -> MiniAppOrder:
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.status != OrderStatus.VERIFIED:
        raise ValueError("verification PASS required before settle")
    order.status = OrderStatus.SETTLED
    _touch(order, "settled")
    return order


def list_orders_for_identity(identity_id: str) -> list[MiniAppOrder]:
    with _LOCK:
        return [
            o
            for o in _ORDERS.values()
            if o.buyer_identity_id == identity_id or o.seller_identity_id == identity_id
        ]


def reset_for_tests() -> None:
    with _LOCK:
        _ORDERS.clear()
