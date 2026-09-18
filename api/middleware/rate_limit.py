"""
Karma — Rate Limiting Middleware (Redis-backed)
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import secrets
import time
from typing import Optional

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status

from config.settings import settings

# Rate limit windows
RATE_LIMITS = {
    "default":      (100, 60),    # 100 req / 60s
    "submit":       (20,  60),    # 20 submissions / 60s
    "verify":       (10,  60),    # 10 verifications / 60s
    "register":     (5,   60),    # 5 auth token exchanges / 60s
    "register_agent": (5, 60),    # 5 agent registrations / 60s (stress-test MEDIUM)
    # Pairing is unauthenticated by design (the agent has no key yet), so the
    # bucket is the only thing standing between a script and the pairing store.
    "agent_pairing": (10, 60),   # 10 pairing requests/claims / 60s
    "write_sensitive": (100, 60),  # 100 sensitive writes / 60s
    "state_transition": (20, 60), # 20 state transitions / 60s
    # P2-11: 读接口此前**完全没限流**（只有 auth/verify 和敏感写有限流）。
    # 额度给得很宽（正常页面/轮询用不满），只用来兜住脚本化爬取与放大攻击。
    "read":         (600, 60),   # 600 reads / 60s per API key or client IP
}

_redis: Optional[aioredis.Redis] = None
_memory_windows: dict[str, list[float]] = {}
_memory_lock = asyncio.Lock()


def clear_memory_rate_limits() -> None:
    """Clear all in-memory rate limit windows. Call between tests to prevent cross-test pollution."""
    _memory_windows.clear()


def _memory_sliding_count(key: str, window_seconds: int) -> int:
    now = time.time()
    window_start = now - window_seconds
    hits = [t for t in _memory_windows.get(key, []) if t >= window_start]
    _memory_windows[key] = hits
    return len(hits)


async def _memory_rate_limit(client_id: str, limit_key: str, max_requests: int, window_seconds: int) -> None:
    """Process-local fallback when Redis is down (dev); not shared across workers."""
    mem_key = f"{limit_key}:{client_id}"
    async with _memory_lock:
        count = _memory_sliding_count(mem_key, window_seconds)
        if count >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {max_requests} requests per {window_seconds}s",
                headers={"Retry-After": str(window_seconds)},
            )
        _memory_windows.setdefault(mem_key, []).append(time.time())


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        # socket timeouts ensure a down/unreachable Redis fails fast instead of
        # hanging the request forever; callers fall back to memory rate limiting.
        _redis = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
    return _redis


async def rate_limit(request: Request, limit_key: str = "default") -> None:
    """
    Sliding window rate limiter using Redis.
    Raises 429 if limit exceeded.
    """
    max_requests, window_seconds = RATE_LIMITS.get(limit_key, RATE_LIMITS["default"])

    # Identify the client on a dimension the caller cannot forge (see
    # ``rate_limit_bucket``). A *configured* credential is hashed so Redis keys
    # and MONITOR logs never store raw secrets.
    client_id = rate_limit_bucket(request)

    redis_key = f"ratelimit:{limit_key}:{client_id}"
    now = time.time()
    window_start = now - window_seconds

    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        # Unique member per request: two requests landing in the same clock tick
        # must not overwrite each other (an undercount would loosen the limit
        # exactly when the traffic is heaviest).
        pipe.zadd(redis_key, {f"{now}:{secrets.token_hex(4)}": now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()
        count = results[2]
    except Exception:
        if settings.rate_limit_redis_fail_closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiting service unavailable",
            ) from None
        # Redis unavailable — fall back to per-process memory rate limiting.
        # Less accurate (not shared across workers) but prevents silent fail-open.
        # _memory_rate_limit raises HTTPException if limit exceeded; if it returns,
        # the request is within limits.
        await _memory_rate_limit(client_id, limit_key, max_requests, window_seconds)
        return

    if count > max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {max_requests} requests per {window_seconds}s",
            headers={"Retry-After": str(window_seconds)},
        )


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------

def make_rate_limit_dep(limit_key: str = "default"):
    async def dep(request: Request):
        await rate_limit(request, limit_key)
    return dep


default_rate_limit  = make_rate_limit_dep("default")
submit_rate_limit   = make_rate_limit_dep("submit")
verify_rate_limit   = make_rate_limit_dep("verify")
register_rate_limit = make_rate_limit_dep("register")
register_agent_rate_limit = make_rate_limit_dep("register_agent")
agent_pairing_rate_limit = make_rate_limit_dep("agent_pairing")
write_sensitive_rate_limit = make_rate_limit_dep("write_sensitive")
state_transition_rate_limit = make_rate_limit_dep("state_transition")


# ---------------------------------------------------------------------------
# Client identity for rate limiting — the trust anchor is the *socket peer*.
#
# ``X-Forwarded-For`` is assembled by nginx with ``$proxy_add_x_forwarded_for``,
# which *appends* to whatever the caller sent: a caller can prepend any value it
# likes, so the header as a whole is caller chosen and must never be the bucket
# key on its own — rotating it used to mint a fresh bucket per request, which
# silently disabled every limit below. ``X-Real-IP`` is set by nginx from
# ``$remote_addr``.
#
# Headers are therefore only believed when the connection itself came from a
# trusted proxy (loopback / private range by default). Anything else — a direct
# connection to the app port, or a proxy that does not rewrite the header — is
# keyed on the peer address, which the caller cannot choose.
# ---------------------------------------------------------------------------

DEFAULT_TRUSTED_PROXY_CIDRS = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


def _trusted_proxy_nets() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw = (getattr(settings, "rate_limit_trusted_proxy_cidrs", "") or "").strip() or DEFAULT_TRUSTED_PROXY_CIDRS
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue  # a typo must not loosen the control
    if not nets:
        # Misconfiguration must not collapse every caller into one bucket.
        nets = [ipaddress.ip_network(x) for x in DEFAULT_TRUSTED_PROXY_CIDRS.split(",")]
    return tuple(nets)


def _is_trusted_proxy(host: str) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False  # e.g. the test client's "testclient" host
    return any(addr in net for net in _trusted_proxy_nets())


def real_client_ip(request: Request) -> str:
    """The client address limits are enforced against — never caller chosen."""
    peer = (request.client.host if request.client and request.client.host else "") or ""
    if not _is_trusted_proxy(peer):
        return peer or "unknown"
    real = (request.headers.get("X-Real-IP") or "").strip()
    if real:
        return real
    chain = [part.strip() for part in (request.headers.get("X-Forwarded-For") or "").split(",") if part.strip()]
    if chain:
        # The *last* entry is the one our own proxy appended; the ones before it
        # are whatever the caller sent.
        return chain[-1]
    return peer or "unknown"


def _configured_key_digests() -> set[str]:
    """SHA-256 digests of the configured API keys (never the raw secrets)."""
    return {
        hashlib.sha256(key.encode("utf-8")).hexdigest()
        for key in settings.auth_api_keys_map().values()
        if key
    }


def rate_limit_bucket(request: Request) -> str:
    """Redis bucket id for the general limiter.

    A *configured* API key gets its own bucket, so several agents sharing one
    egress IP keep their own budget. Everything else — including an invented
    ``X-Karma-Api-Key`` or a spoofed ``X-Forwarded-For`` — falls back to the
    unforgeable client IP, which is what makes rotating either header useless.
    """
    raw_key = (request.headers.get("X-Karma-Api-Key") or "").strip()
    if raw_key:
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        if digest in _configured_key_digests():
            return f"ak:{digest[:40]}"
    return f"ip:{real_client_ip(request)}"


async def _count_and_bump(redis_key: str, window_seconds: int) -> int:
    """Sliding-window counter shared by the sybil buckets.

    Mirrors the general limiter's failure policy: 503 when Redis is down and
    ``RATE_LIMIT_REDIS_FAIL_CLOSED`` is on, otherwise degrade to a process-local
    counter rather than failing open.
    """
    now = time.time()
    window_start = now - window_seconds
    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        # Unique member: two requests landing in the same clock tick must not
        # overwrite each other (an undercount would loosen the control).
        pipe.zadd(redis_key, {f"{now}:{secrets.token_hex(4)}": now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()
        return int(results[2])
    except Exception:
        if settings.rate_limit_redis_fail_closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiting service unavailable",
            ) from None
        async with _memory_lock:
            count = _memory_sliding_count(redis_key, window_seconds) + 1
            _memory_windows.setdefault(redis_key, []).append(time.time())
            return count


async def enforce_zero_funding_registration_limit(request: Request) -> None:
    """Throttle identity creation from wallets that hold no funds.

    Called only when a *new* identity is about to be created for an unfunded
    wallet (see ``services/wallet_funding.py``). A funded wallet never reaches
    this code, so real users are never blocked by other people's spam.
    """
    window = max(1, int(settings.registration_zero_funding_window_seconds))
    per_ip_max = max(0, int(settings.registration_zero_funding_max_per_ip))
    global_max = max(0, int(settings.registration_zero_funding_max_global))

    ip_count = await _count_and_bump(f"regzero:ip:{real_client_ip(request)}", window)
    global_count = await _count_and_bump("regzero:global", window)

    if (per_ip_max and ip_count > per_ip_max) or (global_max and global_count > global_max):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "This wallet holds no funds yet; unfunded registrations are rate limited "
                f"({per_ip_max} per {window}s per IP, {global_max} platform-wide). "
                "Fund the wallet (gas or settlement token) and retry."
            ),
            headers={"Retry-After": str(window)},
        )
