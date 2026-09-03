"""Telegram + MiniApp auth routes: initData session, SIWE, bind."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import create_access_token
from services.identity_gateway import siwe, store
from services.telegram import (
    InitDataError,
    SessionError,
    bind_identity,
    create_session,
    get_session,
    validate_init_data,
)

router = APIRouter()
_log = logging.getLogger("karma.api")


class SessionRequest(BaseModel):
    init_data: str = Field(..., description="Telegram WebApp initData string")


class SiweChallengeRequest(BaseModel):
    address: str


class SiweVerifyRequest(BaseModel):
    nonce: str
    signature: str
    address: str | None = None


class BindTelegramRequest(BaseModel):
    init_data: str
    identity_id: str


class PolicyUpdateRequest(BaseModel):
    identity_id: str
    policy: dict


class CreateSubIdentityRequest(BaseModel):
    parent_identity_id: str
    wallet: str


def _session_or_401(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing session bearer token")
    sid = authorization.split(" ", 1)[1].strip()
    try:
        return get_session(sid)
    except SessionError as exc:
        raise HTTPException(401, str(exc)) from exc


async def _open_reputation_ledger_best_effort(identity_id: str, identity_class: str | None) -> None:
    """Open the reputation book without failing SIWE if the API DB is unavailable."""
    try:
        from db.session import AsyncSessionLocal
        from services.identity_reputation import open_identity_ledger

        async with AsyncSessionLocal() as session:
            await open_identity_ledger(session, identity_id, identity_class=identity_class)
            await session.commit()
    except Exception:
        _log.debug("reputation ledger not opened at SIWE for %s", identity_id, exc_info=True)


@router.post("/telegram/session")
def telegram_session(body: SessionRequest):
    """initData → verified Telegram user → MiniApp session. Never trust client tg id alone."""
    try:
        verified = validate_init_data(body.init_data)
    except InitDataError as exc:
        import logging

        logging.getLogger("karma.api").warning(
            "telegram_session_rejected reason=%s init_data_len=%d", exc, len(body.init_data or "")
        )
        raise HTTPException(401, f"initData invalid: {exc}") from exc

    ident = store.get_by_telegram(verified.user.id)
    sess = create_session(
        telegram_user_id=verified.user.id,
        identity_id=ident.identity_id if ident else None,
        wallet=ident.wallet if ident else None,
        meta={"username": verified.user.username},
    )
    return {
        "session_id": sess.session_id,
        "expires_at": sess.expires_at,
        "telegram_user_id": sess.telegram_user_id,
        "identity_id": sess.identity_id,
        "wallet": sess.wallet,
        "bound": bool(sess.identity_id),
    }


@router.get("/telegram/me")
def telegram_me(authorization: str | None = Header(default=None)):
    sess = _session_or_401(authorization)
    ident = store.get_by_id(sess.identity_id) if sess.identity_id else None
    return {
        "session_id": sess.session_id,
        "telegram_user_id": sess.telegram_user_id,
        "identity": None
        if not ident
        else {
            "identity_id": ident.identity_id,
            "wallet": ident.wallet,
            "telegram_user_id": ident.telegram_user_id,
            "payment_policy": ident.payment_policy,
        },
    }


@router.post("/auth/siwe/challenge")
def siwe_challenge(body: SiweChallengeRequest):
    try:
        ch = siwe.create_challenge(body.address)
    except siwe.SiweError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "nonce": ch.nonce,
        "address": ch.address,
        "message": ch.message,
        "expiration_time": ch.expiration_time,
        "chain_id": ch.chain_id,
        "domain": ch.domain,
    }


@router.post("/auth/siwe/verify")
async def siwe_verify(body: SiweVerifyRequest):
    try:
        ch = siwe.verify_challenge(nonce=body.nonce, signature=body.signature, address=body.address)
    except siwe.SiweError as exc:
        raise HTTPException(401, str(exc)) from exc
    ident = store.get_or_create_by_wallet(ch.address)
    await _open_reputation_ledger_best_effort(ident.identity_id, ident.identity_class)
    # Console wallet login: issue a short-lived JWT bound to this identity so the
    # frontend can call protected routes (capacity/settlement/payment-codes) without
    # a plaintext API key. Reuses create_access_token (15m expiry, sub=identity_id).
    access_token = create_access_token(subject=ident.identity_id)
    return {
        "identity_id": ident.identity_id,
        "wallet": ident.wallet,
        "status": ident.status,
        "payment_policy": ident.payment_policy,
        "reputation_opened": True,
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.post("/telegram/bind")
def telegram_bind(body: BindTelegramRequest, authorization: str | None = Header(default=None)):
    """Bind verified Telegram user to SIWE identity. Requires valid initData."""
    try:
        verified = validate_init_data(body.init_data)
    except InitDataError as exc:
        raise HTTPException(401, f"initData invalid: {exc}") from exc

    # If session present, tg id must match
    if authorization:
        sess = _session_or_401(authorization)
        if sess.telegram_user_id != verified.user.id:
            raise HTTPException(403, "session telegram user mismatch")

    ident = store.get_by_id(body.identity_id)
    if not ident:
        raise HTTPException(404, "identity not found")
    try:
        ident = store.bind_telegram(
            body.identity_id,
            telegram_user_id=verified.user.id,
            username=verified.user.username,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    if authorization:
        bind_identity(sess.session_id, identity_id=ident.identity_id, wallet=ident.wallet)

    # 操作台绑定成功 → 清除 Bot 聊天侧的等待绑定状态（后续消息按正常需求处理）
    from services.telegram import concierge
    concierge.clear_bind_pending(verified.user.id)

    return {
        "identity_id": ident.identity_id,
        "wallet": ident.wallet,
        "telegram_user_id": ident.telegram_user_id,
        "telegram_username": ident.telegram_username,
    }


@router.post("/identity/policy")
def update_policy(body: PolicyUpdateRequest, authorization: str | None = Header(default=None)):
    """
    Update payment policy for the authenticated identity.

    Requires a valid MiniApp session (Bearer token). The session must be bound
    to an identity, and the caller may only modify their own policy.
    """
    sess = _session_or_401(authorization)
    if not sess.identity_id:
        raise HTTPException(403, "session has no bound identity; bind a wallet first")
    if body.identity_id != sess.identity_id:
        raise HTTPException(403, "cannot modify policy of another identity")
    try:
        ident = store.update_policy(body.identity_id, body.policy)
    except KeyError as exc:
        raise HTTPException(404, "identity not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"identity_id": ident.identity_id, "payment_policy": ident.payment_policy}


@router.post("/identities/sub")
def create_sub_identity(body: CreateSubIdentityRequest, authorization: str | None = Header(default=None)):
    """主身份创建子身份，绑定独立钱包地址；消费由主身份承担。"""
    sess = _session_or_401(authorization)
    if not sess.identity_id:
        raise HTTPException(403, "session has no bound identity")
    if body.parent_identity_id != sess.identity_id:
        raise HTTPException(403, "cannot create sub-identity for another identity")
    try:
        ident = store.create_sub_identity(body.parent_identity_id, body.wallet)
    except KeyError as exc:
        raise HTTPException(404, "parent identity not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "identity_id": ident.identity_id,
        "wallet": ident.wallet,
        "parent_identity_id": ident.parent_identity_id,
        "invite_code": ident.invite_code,
        "payment_policy": ident.payment_policy,
    }


class TestSeedRequest(BaseModel):
    identity_id: str
    twofa_code: str
    as_seller: bool = False
    offer_title: str = "数据抓取服务（按次）"
    offer_price_usdc: str = "15"


@router.post("/telegram/test/seed")
def test_seed(body: TestSeedRequest):
    """dev/test only：种子测试身份（含 2FA 码），供 Bot 端「ID+2FA」快速绑定实测。"""
    import os

    if (os.getenv("KARMA_ENV") or "dev").lower() not in {"dev", "test", "local"}:
        raise HTTPException(403, "dev only")

    from eth_account import Account

    from services.miniapp_registry import store as registry

    wallet = Account.create().address
    ident = store.seed_identity(body.identity_id, wallet, twofa_code=body.twofa_code)

    offer = None
    if body.as_seller and not any(
        o.owner_identity_id == body.identity_id for o in registry.list_offers()
    ):
        biz = registry.register_business(
            owner_identity_id=body.identity_id,
            legal_name=f"Karma 商家 {body.identity_id[-4:]}",
            country="SG",
        )
        registry.verify_business(biz.business_id, level="verified")
        cap = registry.register_capability(
            owner_identity_id=body.identity_id,
            name="数据抓取",
            category="digital",
            description="定制化数据抓取与交付",
            evidence_requirements=["proof_hash"],
        )
        agt = registry.register_agent(
            owner_identity_id=body.identity_id,
            endpoint="https://agent.karma.test/api",
            capabilities=["digital"],
            business_id=biz.business_id,
            wallet=wallet,
        )
        offer = registry.publish_offer(
            owner_identity_id=body.identity_id,
            agent_id=agt.agent_id,
            capability_id=cap.capability_id,
            title=body.offer_title,
            price_usdc=body.offer_price_usdc,
            category="digital",
            seller_wallet=wallet,
        )

    return {
        "identity_id": ident.identity_id,
        "twofa_code": ident.twofa_code,
        "wallet": ident.wallet,
        "offer_id": offer.offer_id if offer else None,
    }
