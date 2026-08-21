"""Karma Identity store for MiniApp MVP (in-memory)."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class KarmaIdentity:
    identity_id: str
    wallet: str
    status: str = "active"
    created_at: int = 0
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    business_id: str | None = None
    agent_ids: list[str] = field(default_factory=list)
    payment_policy: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


_LOCK = Lock()
_BY_ID: dict[str, KarmaIdentity] = {}
_BY_WALLET: dict[str, str] = {}
_BY_TG: dict[int, str] = {}


def _new_id() -> str:
    return "kid_" + secrets.token_hex(12)


def get_or_create_by_wallet(wallet: str, **meta) -> KarmaIdentity:
    w = wallet.lower()
    with _LOCK:
        existing = _BY_WALLET.get(w)
        if existing and existing in _BY_ID:
            return _BY_ID[existing]
        identity_id = _new_id()
        ident = KarmaIdentity(
            identity_id=identity_id,
            wallet=w,
            created_at=int(time.time()),
            metadata=dict(meta),
            payment_policy={
                "mode": "manual_confirm",
                "single_limit_usdc": "500",
                "daily_limit_usdc": "2000",
                "allowed_categories": [],
                "allowed_agents": [],
                "emergency_revoke": False,
            },
        )
        _BY_ID[identity_id] = ident
        _BY_WALLET[w] = identity_id
        return ident


def get_by_id(identity_id: str) -> KarmaIdentity | None:
    with _LOCK:
        return _BY_ID.get(identity_id)


def get_by_wallet(wallet: str) -> KarmaIdentity | None:
    with _LOCK:
        iid = _BY_WALLET.get(wallet.lower())
        return _BY_ID.get(iid) if iid else None


def get_by_telegram(telegram_user_id: int) -> KarmaIdentity | None:
    with _LOCK:
        iid = _BY_TG.get(int(telegram_user_id))
        return _BY_ID.get(iid) if iid else None


def bind_telegram(identity_id: str, *, telegram_user_id: int, username: str | None = None) -> KarmaIdentity:
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            raise KeyError("identity not found")
        # one TG → one identity
        prev = _BY_TG.get(int(telegram_user_id))
        if prev and prev != identity_id:
            raise ValueError("telegram already bound to another identity")
        ident.telegram_user_id = int(telegram_user_id)
        ident.telegram_username = username
        _BY_TG[int(telegram_user_id)] = identity_id
        return ident


def update_policy(identity_id: str, policy: dict) -> KarmaIdentity:
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            raise KeyError("identity not found")
        # Never allow infinite approve semantics
        if policy.get("infinite_approve") is True:
            raise ValueError("infinite USDC approve is forbidden")
        merged = {**ident.payment_policy, **policy}
        merged["infinite_approve"] = False
        ident.payment_policy = merged
        return ident


def reset_for_tests() -> None:
    with _LOCK:
        _BY_ID.clear()
        _BY_WALLET.clear()
        _BY_TG.clear()
