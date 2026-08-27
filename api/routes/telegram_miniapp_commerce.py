"""MiniApp commerce + verification + settlement orchestration routes."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.economy_surface import surface_payload
from services.identity_gateway import store
from services.miniapp_commerce import intent_discovery, orders, pipeline
from services.miniapp_registry import store as registry
from services.miniapp_trust import reputation as rep_svc
from services.miniapp_trust import risk_dispute
from services.security_monitoring import SecurityMonitoringEventType, record_security_event
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


def _require_arbitrator(sess) -> None:
    """仲裁员鉴权：/disputes/resolve 只允许白名单内的仲裁员调用。

    SECURITY: 之前任何持有有效登录会话的用户都能裁决争议资金走向，
    等于把仲裁权开放给全部登录用户。白名单来自 ARBITRATOR_ACTOR_IDS
    （生产环境强制非空，见 config/settings.py 校验），开发环境回退到
    admin_actor_ids；两者都为空时：
    - 生产/非 dev 环境：拒绝（fail-closed）
    - 开发环境：放行但记录告警（保持本地 E2E 可跑）
    """
    from config.settings import settings

    allow = settings.arbitrator_actor_id_set()
    if not allow:
        env = (settings.app_env or "").lower()
        if env in ("development", "dev", "local", "test"):
            return  # dev convenience; production is blocked by settings validation
        raise HTTPException(403, "dispute resolution requires ARBITRATOR_ACTOR_IDS to be configured")
    candidates = [
        *( [sess.identity_id] if getattr(sess, "identity_id", None) else [] ),
        str(getattr(sess, "telegram_user_id", "") or ""),
    ]
    if not any(c and c in allow for c in candidates):
        raise HTTPException(403, "dispute resolution requires a whitelisted arbitrator")


def _offer_catalog() -> list[dict]:
    registry.seed_demo_if_empty()
    catalog = registry.offers_as_discovery_catalog()
    return catalog or intent_discovery.DEFAULT_OFFER_CATALOG


def _notify(order_id: str, text: str) -> None:
    """订单事件后台推送给买卖双方（Bot sendMessage）。

    Telegram API 在当前网络下响应慢（可达 10s/次），同步推送会阻塞商业主流程，
    因此改为 daemon 线程执行：API 立即返回，推送失败静默不影响交易。
    """
    def _worker() -> None:
        try:
            from services.telegram import concierge

            concierge.notify_order_event(order_id, text)
        except Exception:  # noqa: BLE001
            pass

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except Exception:  # noqa: BLE001
        pass


def _resolve_offer(offer_id: str | None, offer: dict | None) -> dict | None:
    if offer:
        return offer
    if not offer_id:
        return None
    reg = registry.get_offer(offer_id)
    if reg:
        return {
            "offer_id": reg.offer_id,
            "title": reg.title,
            "seller_identity_id": reg.owner_identity_id,
            "seller_wallet": reg.seller_wallet,
            "builder_address": reg.builder_address,
            "agent_id": reg.agent_id,
            "capability_id": reg.capability_id,
            "amount_usdc": reg.price_usdc,
            "category": reg.category,
        }
    return next((o for o in _offer_catalog() if o.get("offer_id") == offer_id), None)


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


class QuoteBody(BaseModel):
    offer_id: str
    amount_usdc: str | None = None
    terms: dict = Field(default_factory=dict)


class NegotiateBody(BaseModel):
    quote_id: str


class ProposeBody(BaseModel):
    negotiation_id: str
    role: str = Field(pattern="^(buyer|seller)$")
    amount_usdc: str
    note: str = ""


class AgreeBody(BaseModel):
    negotiation_id: str
    amount_usdc: str


class IntentPackageBody(BaseModel):
    order_id: str


class SignIntentBody(BaseModel):
    intent_id: str
    role: str = Field(pattern="^(buyer|seller)$")
    signature: str


class DisputeBody(BaseModel):
    order_id: str
    reason: str


class ResolveDisputeBody(BaseModel):
    dispute_id: str
    resolution: dict


class FulfillmentBody(BaseModel):
    order_id: str


class DeliverBody(BaseModel):
    order_id: str
    evidence: dict


def _require_seller(sess, order) -> None:
    """商家侧履约操作鉴权：仅订单卖方可操作（无卖方身份的订单放行，MVP 兼容）。"""
    seller = order.seller_identity_id
    if seller and seller != "kid_unknown_seller" and sess.identity_id and sess.identity_id != seller:
        raise HTTPException(403, "only the seller may operate this order")


@router.post("/chat/intent")
def chat_intent(body: IntentBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        intent = intent_discovery.parse_chat_intent(body.text, default_amount=body.amount_usdc)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    offers = intent_discovery.rank_offers(intent, _offer_catalog())
    return {"intent": intent, "offers": offers}


@router.get("/discovery/offers")
def discovery_offers(scene_id: str | None = None, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    intent = {"scene_id": scene_id or "digital", "amount_usdc": "100"}
    return {"offers": intent_discovery.rank_offers(intent, _offer_catalog())}


@router.post("/commerce/quotes")
def create_quote(body: QuoteBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not sess.identity_id:
        raise HTTPException(400, "bind identity before quoting")
    offer = _resolve_offer(body.offer_id, None)
    if not offer:
        raise HTTPException(404, "offer not found")
    q = pipeline.create_quote(
        offer_id=body.offer_id,
        buyer_identity_id=sess.identity_id,
        seller_identity_id=str(offer.get("seller_identity_id") or "kid_unknown_seller"),
        amount_usdc=body.amount_usdc or str(offer.get("amount_usdc") or "0"),
        terms=body.terms,
    )
    return {
        "quote_id": q.quote_id,
        "offer_id": q.offer_id,
        "amount_usdc": q.amount_usdc,
        "status": q.status,
        "expires_at": q.expires_at,
        "terms": q.terms,
    }


@router.post("/commerce/negotiations")
def start_negotiation(body: NegotiateBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        n = pipeline.start_negotiation(body.quote_id)
    except KeyError as exc:
        raise HTTPException(404, "quote not found") from exc
    return {"negotiation_id": n.negotiation_id, "quote_id": n.quote_id, "status": n.status}


@router.post("/commerce/negotiations/propose")
def propose_negotiation(body: ProposeBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        n = pipeline.propose(
            body.negotiation_id, role=body.role, amount_usdc=body.amount_usdc, note=body.note
        )
    except KeyError as exc:
        raise HTTPException(404, "negotiation not found") from exc
    return {
        "negotiation_id": n.negotiation_id,
        "status": n.status,
        "messages": n.messages,
    }


@router.post("/commerce/negotiations/agree")
def agree_negotiation(body: AgreeBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        n = pipeline.agree(body.negotiation_id, amount_usdc=body.amount_usdc)
    except KeyError as exc:
        raise HTTPException(404, "negotiation not found") from exc
    return {
        "negotiation_id": n.negotiation_id,
        "status": n.status,
        "agreed_amount_usdc": n.agreed_amount_usdc,
        "quote_id": n.quote_id,
    }


@router.post("/commerce/orders")
def create_order(body: CreateOrderBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not sess.identity_id:
        raise HTTPException(400, "bind identity before creating orders")
    offer = _resolve_offer(body.offer_id, body.offer)
    if body.offer_id and not offer:
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
        pipeline.create_bill(
            order_id=order.order_id,
            buyer_wallet=order.buyer_wallet,
            seller_wallet=order.seller_wallet,
            amount_usdc=order.amount_usdc,
        )
    return _order_json(order)


@router.get("/commerce/orders/{order_id}")
def get_order(order_id: str, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    order = orders.get_order(order_id)
    if not order:
        raise HTTPException(404, "order not found")
    return _order_json(order)


@router.get("/commerce/orders")
def list_my_orders(authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not sess.identity_id:
        return {"orders": []}
    items = orders.list_orders_for_identity(sess.identity_id)
    return {"orders": [_order_json(o) for o in items]}


@router.post("/commerce/orders/sign")
def sign_order(body: SignBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        order = orders.sign_order(body.order_id, role=body.role, signature=body.signature)
    except KeyError as exc:
        raise HTTPException(404, "order not found") from exc
    if order.status.value == "SIGNED":
        _notify(body.order_id, f"订单 {body.order_id} 双方签名完成，下一步锁定资金进入托管。")
    return _order_json(order)


@router.post("/commerce/orders/accept")
def accept_order(body: FulfillmentBody, authorization: str | None = Header(default=None)):
    """商家接单：等待接单 -> 已接单。"""
    sess = _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    _require_seller(sess, order)
    try:
        order = orders.accept_order(body.order_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _notify(body.order_id, f"订单 {body.order_id} 商家已接单，等待签名与资金锁定后开始处理。")
    return _order_json(order)


@router.post("/commerce/orders/start")
def start_order(body: FulfillmentBody, authorization: str | None = Header(default=None)):
    """商家开始处理：已接单 -> 处理中（要求资金已锁定）。"""
    sess = _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    _require_seller(sess, order)
    try:
        order = orders.start_processing(body.order_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _notify(body.order_id, f"订单 {body.order_id} 商家开始处理中，完成后将提交交付结果。")
    return _order_json(order)


@router.post("/commerce/orders/deliver")
def deliver_order(body: DeliverBody, authorization: str | None = Header(default=None)):
    """商家交付：处理中 -> 等待交付验收。同时提交 evidence bundle 进入验证。"""
    sess = _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    _require_seller(sess, order)
    try:
        order = orders.deliver_order(body.order_id, body.evidence)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _notify(body.order_id, f"订单 {body.order_id} 商家已提交交付结果，等待验证验收（证据已存证）。")
    return _order_json(order)


@router.post("/commerce/intent-packages")
def create_intent_package(body: IntentPackageBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    if not order.buyer_wallet or not order.seller_wallet:
        raise HTTPException(400, "buyer and seller wallets required")
    pkg = pipeline.build_intent_package(
        order_id=order.order_id,
        buyer_wallet=order.buyer_wallet,
        seller_wallet=order.seller_wallet,
        amount_usdc=order.amount_usdc,
        scope={"intent": order.intent, "offer": order.offer},
    )
    return {
        "intent_id": pkg.intent_id,
        "order_id": pkg.order_id,
        "typed_data": pkg.typed_data,
        "digest": pkg.digest,
        "status": pkg.status,
    }


@router.post("/commerce/intent-packages/sign")
def sign_intent_package(body: SignIntentBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        pkg = pipeline.sign_intent(body.intent_id, role=body.role, signature=body.signature)
    except KeyError as exc:
        raise HTTPException(404, "intent not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "intent_id": pkg.intent_id,
        "status": pkg.status,
        "buyer_signature": pkg.buyer_signature,
        "seller_signature": pkg.seller_signature,
        "digest": pkg.digest,
    }


@router.get("/commerce/bills/{order_id}")
def get_bill(order_id: str, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    b = pipeline.get_bill_by_order(order_id)
    if not b:
        raise HTTPException(404, "bill not found")
    return {
        "bill_id": b.bill_id,
        "order_id": b.order_id,
        "amount_usdc": b.amount_usdc,
        "status": b.status,
        "binding_id": b.binding_id,
        "buyer_wallet": b.buyer_wallet,
        "seller_wallet": b.seller_wallet,
    }


@router.post("/commerce/orders/policy-check")
def policy_check(body: LockBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    ident = store.get_by_id(sess.identity_id) if sess.identity_id else None
    policy = ident.payment_policy if ident else {"single_limit_usdc": "500", "daily_limit_usdc": "2000"}
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
        ident = store.get_by_id(order.buyer_identity_id)
        policy = ident.payment_policy if ident else {"single_limit_usdc": "500", "daily_limit_usdc": "2000"}
        try:
            orders.apply_policy(body.order_id, policy)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    try:
        order = orders.mark_locked(body.order_id, binding_id=body.binding_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        pipeline.update_bill(body.order_id, status="locked", binding_id=body.binding_id)
    except KeyError:
        pass
    _notify(
        body.order_id,
        f"订单 {body.order_id} 资金已锁定进入托管（binding {body.binding_id}），等待商家交付。",
    )
    return {
        **_order_json(order),
        "bilateral": {
            "action": "lock",
            "note": "Client/relayer submits Bilateral.lock; binding_id optional until confirmed",
            "builder_address": order.builder_address,
            "fee_bridge_order_id": "bytes32(bindingId) when settled",
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


@router.post("/risk/assess")
def risk_assess(body: LockBody, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    self_deal = bool(order.buyer_wallet and order.seller_wallet and order.buyer_wallet == order.seller_wallet)
    a = risk_dispute.assess_risk(
        order_id=order.order_id,
        intent={**order.intent, "amount_usdc": order.amount_usdc},
        evidence=order.evidence,
        self_deal=self_deal,
    )
    return {
        "assessment_id": a.assessment_id,
        "order_id": a.order_id,
        "score": a.score,
        "flags": a.flags,
        "hold": a.hold,
    }


@router.post("/verification/runs")
def verification_runs(body: VerifyBody, authorization: str | None = Header(default=None)):
    """★ Core VerificationEngine — must PASS before settle. Risk hold blocks settle path."""
    _require_session(authorization)
    order = orders.get_order(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    if not order.evidence:
        raise HTTPException(409, "evidence required")

    self_deal = bool(order.buyer_wallet and order.seller_wallet and order.buyer_wallet == order.seller_wallet)
    risk = risk_dispute.latest_risk(order.order_id) or risk_dispute.assess_risk(
        order_id=order.order_id,
        intent={**order.intent, "amount_usdc": order.amount_usdc},
        evidence=order.evidence,
        self_deal=self_deal,
    )
    # Only forward risk flags into VerificationEngine when hold — informational flags must not block settle.
    flags = list(body.risk_flags or [])
    if risk.hold:
        flags = flags + list(risk.flags) + ["risk_hold"]

    run = run_verification(
        order_id=order.order_id,
        intent=order.intent,
        evidence=order.evidence,
        risk_flags=flags or None,
    )
    if run.status.value == "PASS":
        orders.mark_verified(order.order_id, run_id=run.run_id)
        _notify(order.order_id, f"订单 {order.order_id} 交付验收通过（run {run.run_id[:12]}…），资金即将结算放款。")
    return {
        "run_id": run.run_id,
        "order_id": run.order_id,
        "status": run.status.value,
        "reasons": run.reasons,
        "evidence_hash": run.evidence_hash,
        "intent_hash": run.intent_hash,
        "settle_allowed": run.status.value == "PASS" and not risk.hold,
        "risk": {"score": risk.score, "flags": risk.flags, "hold": risk.hold},
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

    risk = risk_dispute.latest_risk(body.order_id)
    if risk and risk.hold:
        raise HTTPException(403, "risk hold — cannot settle")

    # 开争议必须阻止结算：存在未决争议（status=open）时拒绝放款
    open_disputes = [d for d in risk_dispute.list_disputes(body.order_id) if d.status == "open"]
    if open_disputes:
        raise HTTPException(403, f"open dispute ({open_disputes[0].dispute_id}) — cannot settle until resolved")

    self_deal = bool(order.buyer_wallet and order.seller_wallet and order.buyer_wallet == order.seller_wallet)
    developer = order.builder_address or order.seller_wallet
    try:
        order = orders.mark_settled(body.order_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    _notify(
        body.order_id,
        f"订单 {body.order_id} 已结算，{order.amount_usdc} USDC 已释放给商家（含公开证明 run {run.run_id[:12]}…）。",
    )

    try:
        pipeline.update_bill(body.order_id, status="settled", binding_id=order.binding_id)
    except KeyError:
        pass

    agent_id = (order.offer or {}).get("agent_id")
    rec = rep_svc.record_settlement(
        order_id=order.order_id,
        buyer_identity_id=order.buyer_identity_id,
        seller_identity_id=order.seller_identity_id,
        agent_id=agent_id,
        amount_usdc=order.amount_usdc,
        verification_run_id=run.run_id,
        public_proof={
            "binding_id": order.binding_id,
            "verification_run_id": run.run_id,
            "self_deal": self_deal,
        },
    )

    return {
        **_order_json(order),
        "verification_run_id": run.run_id,
        "execution_record_id": rec.record_id,
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


@router.post("/disputes")
def open_dispute(body: DisputeBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not orders.get_order(body.order_id):
        raise HTTPException(404, "order not found")
    if orders.get_order(body.order_id).status.value == "SETTLED":
        raise HTTPException(409, "order already settled — open dispute rejected")
    d = risk_dispute.open_dispute(
        order_id=body.order_id,
        opened_by=sess.identity_id or str(sess.telegram_user_id),
        reason=body.reason,
    )
    try:
        orders.mark_disputed(body.order_id)
    except (KeyError, ValueError):
        pass
    try:
        pipeline.update_bill(body.order_id, status="disputed")
    except KeyError:
        pass
    _notify(body.order_id, f"订单 {body.order_id} 已开启争议：{body.reason}。等待仲裁处理。")
    return {
        "dispute_id": d.dispute_id,
        "order_id": d.order_id,
        "status": d.status,
        "reason": d.reason,
    }


@router.post("/disputes/resolve")
def resolve_dispute(body: ResolveDisputeBody, authorization: str | None = Header(default=None)):
    """仲裁解决争议：按结局回写订单与账单。

    - refund -> 订单 REFUNDED + 账单 refunded
    - 其他（release/reject 等）-> 账单恢复 locked，履约状态恢复，可继续正常结算
    """
    sess = _require_session(authorization)
    _require_arbitrator(sess)
    actor_id = str(getattr(sess, "identity_id", "") or getattr(sess, "telegram_user_id", "") or "unknown")
    try:
        d = risk_dispute.resolve_dispute(body.dispute_id, resolution=body.resolution)
    except KeyError as exc:
        raise HTTPException(404, "dispute not found") from exc

    outcome = str((body.resolution or {}).get("action") or (body.resolution or {}).get("outcome") or "").lower()
    # 高敏感操作审计（红队报告 KARMA-RT-2026-08-27-001 §5）：
    # 仲裁员裁决能直接决定争议资金归属，每次调用必须可追溯、可告警。
    record_security_event(
        SecurityMonitoringEventType.ARBITRATOR_ACTION,
        metadata={
            "path": "/v1/disputes/resolve",
            "actor_id": actor_id,
            "route_group": "arbitration",
            "dispute_id": body.dispute_id,
            "outcome": outcome or "unknown",
        },
    )
    if "refund" in outcome:
        try:
            orders.mark_refunded(d.order_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        try:
            pipeline.update_bill(d.order_id, status="refunded")
        except KeyError:
            pass
        _notify(d.order_id, f"订单 {d.order_id} 争议已解决：仲裁退款，资金退回买方。")
    else:
        try:
            orders.restore_fulfillment(d.order_id)
        except (KeyError, ValueError):
            pass
        try:
            pipeline.update_bill(d.order_id, status="locked")
        except KeyError:
            pass
        _notify(d.order_id, f"订单 {d.order_id} 争议已解决：资金继续托管，订单恢复进行。")
    return {
        "dispute_id": d.dispute_id,
        "status": d.status,
        "resolution": d.resolution,
    }


@router.get("/disputes")
def list_disputes(order_id: str | None = None, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    items = risk_dispute.list_disputes(order_id)
    return {
        "disputes": [
            {
                "dispute_id": d.dispute_id,
                "order_id": d.order_id,
                "status": d.status,
                "reason": d.reason,
                "opened_by": d.opened_by,
            }
            for d in items
        ]
    }


@router.get("/miniapp/reputation/{identity_id}")
def get_reputation(identity_id: str, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    return rep_svc.reputation_of(identity_id)


@router.get("/activity/history")
def activity_history(authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    items = rep_svc.list_history(identity_id=sess.identity_id)
    return {
        "history": [
            {
                "record_id": h.record_id,
                "order_id": h.order_id,
                "amount_usdc": h.amount_usdc,
                "status": h.status,
                "at": h.created_at,
                "public_proof": h.public_proof,
            }
            for h in items
        ]
    }


@router.get("/economy/surface")
def economy_surface(address: str | None = None, authorization: str | None = Header(default=None)):
    if authorization:
        _require_session(authorization)
    return surface_payload(address)


def _order_json(order) -> dict:
    bill = pipeline.get_bill_by_order(order.order_id)
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "fulfillment_status": order.fulfillment_status.value,
        "fulfillment_label": orders.fulfillment_label(order),
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
        "bill_id": bill.bill_id if bill else None,
        "bill_status": bill.status if bill else None,
    }
