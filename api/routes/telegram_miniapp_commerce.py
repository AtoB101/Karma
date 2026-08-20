"""MiniApp commerce + verification + settlement orchestration routes."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.economy_surface import surface_payload
from services.identity_gateway import store
from services.miniapp_commerce import intent_discovery, orders
from services.telegram import SessionError, get_session
from services.verification_engine import (
    assert_pass_for_settle,
    run_verification,
)

router = APIRouter()


def _require_session(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing session")
    try:
        return get_session(authorization.split(" ", 1)[1].strip())
    except SessionError as exc:
        raise HTTPException(401, str(exc)) from exc


class IntentBody(BaseModel):
    text: str
    amount_usdc: str | None = None


class CreateOrderBody(BaseModel):
    intent: dict
    offer_id: str | None = None
    offer: dict | None = None


class SignBody(BaseModel):
    order_id: str
    role: str = Field(pattern="^(buyer|seller)$")
    signature: str


class EvidenceBody(BaseModel):
    order_id: str
    evidence: dict


class VerifyBody(BaseModel):
    order_id: str
    risk_flags: list[str] | None = None


class LockBody(BaseModel):
    order_id: str
    binding_id: int | None = None


class SettleBody(BaseModel):
    order_id: str


@router.post("/chat/intent")
def chat_intent(body: IntentBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        intent = intent_discovery.parse_chat_intent(body.text, default_amount=body.amount_usdc)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    offers = intent_discovery.rank_offers(intent, intent_discovery.DEFAULT_OFFER_CATALOG)
    return {"intent": intent, "offers": offers}


@router.get("/discovery/offers")
def discovery_offers(scene_id: str | None = None, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    intent = {"scene_id": scene_id or "digital", "amount_usdc": "100"}
    return {"offers": intent_discovery.rank_offers(intent, intent_discovery.DEFAULT_OFFER_CATALOG)}


@router.post("/commerce/orders")
def create_order(body: CreateOrderBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not sess.identity_id:
        raise HTTPException(400, "bind identity before creating orders")
    offer = body.offer
    if body.offer_id and not offer:
        offer = next(
            (o for o in intent_discovery.DEFAULT_OFFER_CATALOG if o.get("offer_id") == body.offer_id),
            None,
        )
        if not offer:
            raise HTTPException(404, "offer not found")
    order = orders.create_order(
        buyer_identity_id=sess.identity_id,
        intent=body.intent,
        buyer_wallet=sess.wallet,
        builder_address=(offer or {}).get("builder_address"),
    )
    if offer:
        orders.attach_offer(
            order.order_id,
            offer,
            seller_identity_id=str(offer.get("seller_identity_id") or "kid_unknown_seller"),
            seller_wallet=offer.get("seller_wallet"),
        )
        order = orders.get_order(order.order_id)
    return _order_json(order)


@router.get("/commerce/orders/{order_id}")
def get_order(order_id: str, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    order = orders.get_order(order_id)
    if not order:
        raise HTTPException(404, "order not found")
    return _order_json(order)


@router.post("/commerce/orders/sign")
def sign_order(body: SignBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        order = orders.sign_order(body.order_id, role=body.role, signature=body.signature)
    except KeyError as exc:
        raise HTTPException(404, "order not found") from exc
    return _order_json(order)


@router.post("/commerce/orders/policy-check")
def policy_check(body: LockBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    ident = store.get_by_id(sess.identity_id) if sess.identity_id else None
    policy = ident.payment_policy if ident else {"single_limit_usdc": "500"}
    try:
        order = orders.apply_policy(body.order_id, policy)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _order_json(order)


@router.post("/settlement/lock")
def settlement_lock(body: LockBody, authorization: str | None = Header(default=None)):
    """Orchestrate Bilateral lock after policy check. On-chain tx is external/relayer."""
    _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    if order.status.value == "SIGNED":
        # auto policy if not done
        ident = store.get_by_id(order.buyer_identity_id)
        policy = ident.payment_policy if ident else {"single_limit_usdc": "500"}
        try:
            orders.apply_policy(body.order_id, policy)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    try:
        order = orders.mark_locked(body.order_id, binding_id=body.binding_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        **_order_json(order),
        "bilateral": {
            "action": "lock",
            "note": "Client/relayer submits Bilateral.lock; binding_id optional until confirmed",
            "builder_address": order.builder_address,
            "fee_bridge_order_id": f"bytes32(bindingId) when settled",
        },
    }


@router.post("/evidence/bundles")
def submit_evidence(body: EvidenceBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        order = orders.submit_evidence(body.order_id, body.evidence)
    except KeyError as exc:
        raise HTTPException(404, "order not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _order_json(order)


@router.post("/verification/runs")
def verification_runs(body: VerifyBody, authorization: str | None = Header(default=None)):
    """★ Core VerificationEngine — must PASS before settle."""
    _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    if not order.evidence:
        raise HTTPException(409, "evidence required")
    run = run_verification(
        order_id=order.order_id,
        intent=order.intent,
        evidence=order.evidence,
        risk_flags=body.risk_flags,
    )
    if run.status.value == "PASS":
        orders.mark_verified(order.order_id, run_id=run.run_id)
    return {
        "run_id": run.run_id,
        "order_id": run.order_id,
        "status": run.status.value,
        "reasons": run.reasons,
        "evidence_hash": run.evidence_hash,
        "intent_hash": run.intent_hash,
        "settle_allowed": run.status.value == "PASS",
    }


@router.post("/settlement/finalize")
def settlement_finalize(body: SettleBody, authorization: str | None = Header(default=None)):
    """Finalize only if Verification PASS. Bilateral settle → FeeBridge.collectAndRecord."""
    _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    try:
        run = assert_pass_for_settle(body.order_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc

    # Self-deal: still settle on-chain possible, but Mirror won't credit developer GMV (karma8)
    self_deal = bool(order.buyer_wallet and order.seller_wallet and order.buyer_wallet == order.seller_wallet)
    developer = order.builder_address or order.seller_wallet
    try:
        order = orders.mark_settled(body.order_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    return {
        **_order_json(order),
        "verification_run_id": run.run_id,
        "fee_bridge": {
            "collectAndRecord": {
                "orderId": "bytes32(bindingId)" if order.binding_id is not None else None,
                "binding_id": order.binding_id,
                "buyer": order.buyer_wallet,
                "seller": order.seller_wallet,
                "developer": developer,
                "amountUsdc": order.amount_usdc,
                "note": "Cold start fee=0 still records GMV; buyer==seller skips developer GMV credit in Mirror",
                "self_deal": self_deal,
            }
        },
    }


@router.get("/economy/surface")
def economy_surface(address: str | None = None, authorization: str | None = Header(default=None)):
    # Session optional for public config; preferred with auth
    if authorization:
        _require_session(authorization)
    return surface_payload(address)


def _order_json(order) -> dict:
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "buyer_identity_id": order.buyer_identity_id,
        "seller_identity_id": order.seller_identity_id,
        "builder_address": order.builder_address,
        "amount_usdc": order.amount_usdc,
        "buyer_wallet": order.buyer_wallet,
        "seller_wallet": order.seller_wallet,
        "binding_id": order.binding_id,
        "intent": order.intent,
        "offer": order.offer,
        "evidence": order.evidence,
        "verification_run_id": order.verification_run_id,
        "policy_result": order.policy_result,
        "signatures": order.signatures,
        "history": order.history,
    }
