"""In-memory session store for Telegram MiniApp (MVP).

Production should back this with Redis / DB; interface stays the same.
"""
from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass, field
from threading import Lock


class SessionError(ValueError):
    pass


@dataclass
class MiniAppSession:
    session_id: str
    telegram_user_id: int
    identity_id: str | None
    wallet: str | None
    issued_at: int
    expires_at: int
    nonce: str
    meta: dict = field(default_factory=dict)


_LOCK = Lock()
_SESSIONS: dict[str, MiniAppSession] = {}


def _ttl() -> int:
    return int(os.getenv("TELEGRAM_SESSION_TTL_SECONDS", "86400"))


def create_session(
    *,
    telegram_user_id: int,
    identity_id: str | None = None,
    wallet: str | None = None,
    meta: dict | None = None,
) -> MiniAppSession:
    now = int(time.time())
    sid = secrets.token_urlsafe(24)
    sess = MiniAppSession(
        session_id=sid,
        telegram_user_id=int(telegram_user_id),
        identity_id=identity_id,
        wallet=(wallet.lower() if wallet else None),
        issued_at=now,
        expires_at=now + _ttl(),
        nonce=secrets.token_hex(16),
        meta=dict(meta or {}),
    )
    with _LOCK:
        _SESSIONS[sid] = sess
    return sess


def get_session(session_id: str) -> MiniAppSession:
    with _LOCK:
        sess = _SESSIONS.get(session_id)
    if not sess:
        raise SessionError("session not found")
    if int(time.time()) > sess.expires_at:
        with _LOCK:
            _SESSIONS.pop(session_id, None)
        raise SessionError("session expired")
    return sess


def bind_identity(session_id: str, *, identity_id: str, wallet: str | None = None) -> MiniAppSession:
    sess = get_session(session_id)
    sess.identity_id = identity_id
    if wallet:
        sess.wallet = wallet.lower()
    with _LOCK:
        _SESSIONS[session_id] = sess
    return sess


def revoke_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)


def reset_for_tests() -> None:
    with _LOCK:
        _SESSIONS.clear()
