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

from services import persist_json


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


class FulfillmentStatus(str, Enum):
    """商户履约子状态机（与主状态机并行，面向用户展示）。

    PENDING_ACCEPT 等待接单 -> ACCEPTED 已接单 -> PROCESSING 处理中 ->
    DELIVERED 等待交付验收 -> VERIFIED 验收通过 -> SETTLED 已结算；
    异常分支：DISPUTED 争议中 / REFUNDED 已退款。
    """

    PENDING_ACCEPT = "PENDING_ACCEPT"
    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    VERIFIED = "VERIFIED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"


_FULFILLMENT_LABELS = {
    "PENDING_ACCEPT": "等待接单",
    "ACCEPTED": "已接单",
    "PROCESSING": "处理中",
    "DELIVERED": "等待交付验收",
    "VERIFIED": "验收通过",
    "SETTLED": "验收成功已结算",
    "DISPUTED": "争议中",
    "REFUNDED": "已退款",
}


@dataclass
class MiniAppOrder:
    order_id: str
    buyer_identity_id: str
    seller_identity_id: str | None
    builder_address: str | None  # BUILDER attribution for FeeBridge.developer
    intent: dict[str, Any]
    offer: dict[str, Any] | None = None
    status: OrderStatus = OrderStatus.DRAFT
    fulfillment_status: FulfillmentStatus = FulfillmentStatus.PENDING_ACCEPT
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


def _order_to_dict(order: MiniAppOrder) -> dict[str, Any]:
    from dataclasses import asdict

    d = asdict(order)
    d["status"] = order.status.value
    d["fulfillment_status"] = order.fulfillment_status.value
    return d


def _persist() -> None:
    persist_json.save("orders", {"orders": [_order_to_dict(o) for o in _ORDERS.values()]})


def _load() -> None:
    for d in persist_json.load("orders").get("orders", []):
        try:
            d = dict(d)
            d["status"] = OrderStatus(d.get("status") or "DRAFT")
            d["fulfillment_status"] = FulfillmentStatus(d.get("fulfillment_status") or "PENDING_ACCEPT")
            o = MiniAppOrder(**d)
        except (TypeError, ValueError):
            continue
        _ORDERS[o.order_id] = o


_load()


def _touch(order: MiniAppOrder, note: str) -> None:
    order.updated_at = int(time.time())
    order.history.append({"at": order.updated_at, "status": order.status.value, "note": note})
    _persist()


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
    order.fulfillment_status = FulfillmentStatus.PENDING_ACCEPT
    _touch(order, "offer_attached")
    return order


def accept_order(order_id: str) -> MiniAppOrder:
    """商家接单：等待接单 -> 已接单。允许在签名/锁定前后接单。"""
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.fulfillment_status != FulfillmentStatus.PENDING_ACCEPT:
        raise ValueError(f"cannot accept from fulfillment: {order.fulfillment_status}")
    if order.status not in {OrderStatus.QUOTED, OrderStatus.SIGNED, OrderStatus.POLICY_CHECKED, OrderStatus.LOCKED}:
        raise ValueError(f"cannot accept from status: {order.status}")
    order.fulfillment_status = FulfillmentStatus.ACCEPTED
    _touch(order, "fulfillment_accepted")
    return order


def start_processing(order_id: str) -> MiniAppOrder:
    """商家开始处理：已接单 -> 处理中。要求资金已锁定（保护买家）。"""
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.status != OrderStatus.LOCKED:
        raise ValueError("funds must be locked before processing")
    if order.fulfillment_status != FulfillmentStatus.ACCEPTED:
        raise ValueError(f"cannot start processing from fulfillment: {order.fulfillment_status}")
    order.fulfillment_status = FulfillmentStatus.PROCESSING
    _touch(order, "fulfillment_processing")
    return order


def deliver_order(order_id: str, evidence: dict[str, Any]) -> MiniAppOrder:
    """商家交付：处理中 -> 等待交付验收。同时提交交付证据（evidence bundle）。"""
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.status != OrderStatus.LOCKED:
        raise ValueError("funds must be locked before delivery")
    if order.fulfillment_status not in {FulfillmentStatus.ACCEPTED, FulfillmentStatus.PROCESSING}:
        raise ValueError(f"cannot deliver from fulfillment: {order.fulfillment_status}")
    order.evidence = dict(evidence)
    order.status = OrderStatus.EVIDENCE_SUBMITTED
    order.fulfillment_status = FulfillmentStatus.DELIVERED
    _touch(order, "evidence_submitted")
    _touch(order, "fulfillment_delivered")
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
    # 兼容旧路径（直接 submit_evidence 不走接单/处理）：履约状态自动推进到等待验收
    if order.fulfillment_status in {
        FulfillmentStatus.PENDING_ACCEPT,
        FulfillmentStatus.ACCEPTED,
        FulfillmentStatus.PROCESSING,
    }:
        order.fulfillment_status = FulfillmentStatus.DELIVERED
    _touch(order, "evidence_submitted")
    return order


def mark_verified(order_id: str, *, run_id: str) -> MiniAppOrder:
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    order.verification_run_id = run_id
    order.status = OrderStatus.VERIFIED
    order.fulfillment_status = FulfillmentStatus.VERIFIED
    _touch(order, "verified")
    return order


def mark_settled(order_id: str) -> MiniAppOrder:
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.status != OrderStatus.VERIFIED:
        raise ValueError("verification PASS required before settle")
    order.status = OrderStatus.SETTLED
    order.fulfillment_status = FulfillmentStatus.SETTLED
    _touch(order, "settled")
    return order


def mark_refunded(order_id: str) -> MiniAppOrder:
    """争议仲裁退款：订单进入 REFUNDED。已结算订单不允许退款。"""
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.status == OrderStatus.SETTLED:
        raise ValueError("already settled — cannot refund")
    order.status = OrderStatus.REFUNDED
    order.fulfillment_status = FulfillmentStatus.REFUNDED
    _touch(order, "refunded")
    return order


def mark_disputed(order_id: str) -> MiniAppOrder:
    """开争议：履约状态标记为争议中（主状态不动，由仲裁结果决定）。"""
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.fulfillment_status in {FulfillmentStatus.SETTLED, FulfillmentStatus.REFUNDED}:
        return order
    order.fulfillment_status = FulfillmentStatus.DISPUTED
    _touch(order, "fulfillment_disputed")
    return order


def restore_fulfillment(order_id: str) -> MiniAppOrder:
    """争议解决（非退款结局）后，按主状态推断恢复履约状态。"""
    order = get_order(order_id)
    if not order:
        raise KeyError("order not found")
    if order.fulfillment_status != FulfillmentStatus.DISPUTED:
        return order
    if order.status == OrderStatus.EVIDENCE_SUBMITTED:
        order.fulfillment_status = FulfillmentStatus.DELIVERED
    elif order.status in {OrderStatus.VERIFIED, OrderStatus.SETTLED}:
        order.fulfillment_status = FulfillmentStatus(order.status.value)
    else:
        order.fulfillment_status = FulfillmentStatus.ACCEPTED
    _touch(order, "fulfillment_restored")
    return order


def fulfillment_label(order: MiniAppOrder) -> str:
    return _FULFILLMENT_LABELS.get(order.fulfillment_status.value, order.fulfillment_status.value)


def list_orders_for_identity(identity_id: str) -> list[MiniAppOrder]:
    with _LOCK:
        return [
            o
            for o in _ORDERS.values()
            if o.buyer_identity_id == identity_id or o.seller_identity_id == identity_id
        ]


def orders_as_buyer(identity_id: str) -> list[MiniAppOrder]:
    """买家付款订单（我付钱买的）。"""
    with _LOCK:
        return [o for o in _ORDERS.values() if o.buyer_identity_id == identity_id]


def orders_as_seller(identity_id: str) -> list[MiniAppOrder]:
    """卖家收款订单（别人付钱给我的）。"""
    with _LOCK:
        return [o for o in _ORDERS.values() if o.seller_identity_id == identity_id]


_IN_PROGRESS_STATUSES = {"LOCKED", "EXECUTED", "EVIDENCE_SUBMITTED", "VERIFIED"}
_DISPUTE_STATUSES = {"REJECTED"}


def orders_in_progress(identity_id: str) -> list[MiniAppOrder]:
    """正在进行的订单（锁仓到验收阶段）。"""
    with _LOCK:
        return [
            o for o in _ORDERS.values()
            if (o.buyer_identity_id == identity_id or o.seller_identity_id == identity_id)
            and o.status.value in _IN_PROGRESS_STATUSES
        ]


def orders_in_dispute(identity_id: str) -> list[MiniAppOrder]:
    """争议/退款订单。"""
    with _LOCK:
        return [
            o for o in _ORDERS.values()
            if (o.buyer_identity_id == identity_id or o.seller_identity_id == identity_id)
            and (o.status.value in _DISPUTE_STATUSES or o.fulfillment_status.value == "DISPUTED")
        ]


def order_detail(order_id: str) -> dict[str, Any] | None:
    """订单详情摘要。"""
    o = get_order(order_id)
    if not o:
        return None
    return {
        "order_id": o.order_id,
        "status": o.status.value,
        "fulfillment_status": o.fulfillment_status.value,
        "fulfillment_label": fulfillment_label(o),
        "amount_usdc": o.amount_usdc,
        "buyer_identity_id": o.buyer_identity_id,
        "seller_identity_id": o.seller_identity_id,
        "buyer_wallet": o.buyer_wallet,
        "seller_wallet": o.seller_wallet,
        "intent": o.intent,
        "offer": o.offer,
        "evidence": o.evidence,
        "created_at": o.created_at,
        "updated_at": o.updated_at,
        "history": o.history,
        "policy_result": o.policy_result,
    }


def reset_for_tests() -> None:
    with _LOCK:
        _ORDERS.clear()
        persist_json.delete("orders")
