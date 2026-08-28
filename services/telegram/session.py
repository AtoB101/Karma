"""Session store for Telegram MiniApp.

Primary backend is Redis (survives restarts); falls back to the original
in-memory dict when Redis is unavailable so dev/test environments keep working.

Selection:
- ``TELEGRAM_SESSION_BACKEND=redis``  -> Redis only (raise on failure)
- ``TELEGRAM_SESSION_BACKEND=memory`` -> in-memory only
- default (``auto``)                  -> try Redis, fall back to memory

TODO(p2): for multi-instance production deployments the memory fallback is not
shared across workers; enforce the Redis backend via env config there.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)


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

_REDIS_PREFIX = "karma:tg_session:"
_BACKEND: str | None = None  # resolved lazily: "redis" | "memory"
_REDIS_CLIENT = None


def _ttl() -> int:
    return int(os.getenv("TELEGRAM_SESSION_TTL_SECONDS", "86400"))


def _redis_url() -> str:
    return (
        os.getenv("TELEGRAM_SESSION_REDIS_URL")
        or os.getenv("REDIS_URL")
        or "redis://localhost:6379/0"
    )


def _resolve_backend() -> str:
    global _BACKEND, _REDIS_CLIENT
    if _BACKEND is not None:
        return _BACKEND

    configured = (os.getenv("TELEGRAM_SESSION_BACKEND") or "auto").strip().lower()
    if configured == "memory":
        _BACKEND = "memory"
        return _BACKEND

    if configured in {"redis", "auto"}:
        try:
            import redis  # sync client; redis is already a project dependency

            client = redis.Redis.from_url(
                _redis_url(),
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                decode_responses=True,
            )
            client.ping()
            _REDIS_CLIENT = client
            _BACKEND = "redis"
            if configured == "auto":
                logger.info("telegram_session_backend=redis url=%s", _redis_url())
            return _BACKEND
        except Exception as exc:  # noqa: BLE001
            if configured == "redis":
                raise RuntimeError(f"TELEGRAM_SESSION_BACKEND=redis but Redis unavailable: {exc}") from exc
            logger.warning(
                "telegram_session_backend fallback to memory (redis unavailable: %s)", exc
            )
            _BACKEND = "memory"
            return _BACKEND

    _BACKEND = "memory"
    return _BACKEND


def _to_redis(sess: MiniAppSession, ttl_seconds: int | None = None) -> None:
    ttl = ttl_seconds if ttl_seconds is not None else max(sess.expires_at - int(time.time()), 1)
    _REDIS_CLIENT.set(
        f"{_REDIS_PREFIX}{sess.session_id}",
        json.dumps(asdict(sess)),
        ex=ttl,
    )


def _from_redis(session_id: str) -> MiniAppSession | None:
    raw = _REDIS_CLIENT.get(f"{_REDIS_PREFIX}{session_id}")
    if not raw:
        return None
    data = json.loads(raw)
    data["meta"] = data.get("meta") or {}
    return MiniAppSession(**data)


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
    if _resolve_backend() == "redis":
        _to_redis(sess)
    else:
        with _LOCK:
            _SESSIONS[sid] = sess
    return sess


def get_session(session_id: str) -> MiniAppSession:
    if _resolve_backend() == "redis":
        sess = _from_redis(session_id)
        if not sess:
            raise SessionError("session not found")
        if int(time.time()) > sess.expires_at:
            _REDIS_CLIENT.delete(f"{_REDIS_PREFIX}{session_id}")
            raise SessionError("session expired")
        return sess

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
    if _resolve_backend() == "redis":
        _to_redis(sess)
    else:
        with _LOCK:
            _SESSIONS[session_id] = sess
    return sess


def revoke_session(session_id: str) -> None:
    if _resolve_backend() == "redis":
        _REDIS_CLIENT.delete(f"{_REDIS_PREFIX}{session_id}")
    else:
        with _LOCK:
            _SESSIONS.pop(session_id, None)


def reset_for_tests() -> None:
    global _BACKEND, _REDIS_CLIENT
    # Force tests to the memory backend unless a test Redis is explicitly wired.
    if (os.getenv("TELEGRAM_SESSION_BACKEND") or "").strip().lower() == "redis":
        if _REDIS_CLIENT is not None:
            for key in _REDIS_CLIENT.scan_iter(f"{_REDIS_PREFIX}*"):
                _REDIS_CLIENT.delete(key)
    else:
        _BACKEND = "memory"
        _REDIS_CLIENT = None
    with _LOCK:
        _SESSIONS.clear()
