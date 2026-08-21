"""Telegram + MiniApp auth routes: initData session, SIWE, bind."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

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


def _session_or_401(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing session bearer token")
    sid = authorization.split(" ", 1)[1].strip()
    try:
        return get_session(sid)
    except SessionError as exc:
        raise HTTPException(401, str(exc)) from exc


@router.post("/telegram/session")
def telegram_session(body: SessionRequest):
    """initData → verified Telegram user → MiniApp session. Never trust client tg id alone."""
    try:
        verified = validate_init_data(body.init_data)
    except InitDataError as exc:
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
def siwe_verify(body: SiweVerifyRequest):
    try:
        ch = siwe.verify_challenge(nonce=body.nonce, signature=body.signature, address=body.address)
    except siwe.SiweError as exc:
        raise HTTPException(401, str(exc)) from exc
    ident = store.get_or_create_by_wallet(ch.address)
    return {
        "identity_id": ident.identity_id,
        "wallet": ident.wallet,
        "status": ident.status,
        "payment_policy": ident.payment_policy,
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

    return {
        "identity_id": ident.identity_id,
        "wallet": ident.wallet,
        "telegram_user_id": ident.telegram_user_id,
        "telegram_username": ident.telegram_username,
    }


@router.post("/identity/policy")
def update_policy(body: PolicyUpdateRequest):
    try:
        ident = store.update_policy(body.identity_id, body.policy)
    except KeyError as exc:
        raise HTTPException(404, "identity not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"identity_id": ident.identity_id, "payment_policy": ident.payment_policy}
