"""
Karma — Rate Limiting Middleware (Redis-backed)
"""
from __future__ import annotations

import hashlib
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
    "register":     (5,   60),    # 5 registrations / 60s
    "write_sensitive": (30, 60),  # 30 sensitive writes / 60s
    "state_transition": (20, 60), # 20 state transitions / 60s
}

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def rate_limit(request: Request, limit_key: str = "default") -> None:
    """
    Sliding window rate limiter using Redis.
    Raises 429 if limit exceeded.
    """
    max_requests, window_seconds = RATE_LIMITS.get(limit_key, RATE_LIMITS["default"])

    # Identify client: hash API keys / forwarded header so Redis keys and MONITOR logs never store raw secrets.
    raw_key = request.headers.get("X-Karma-Api-Key")
    raw_fwd = request.headers.get("X-Forwarded-For")
    if raw_key:
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:40]
        client_id = f"ak:{digest}"
    elif raw_fwd:
        digest = hashlib.sha256(raw_fwd.encode("utf-8")).hexdigest()[:40]
        client_id = f"xff:{digest}"
    else:
        client_id = request.client.host if request.client else "anonymous"

    redis_key = f"ratelimit:{limit_key}:{client_id}"
    now = time.time()
    window_start = now - window_seconds

    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zadd(redis_key, {str(now): now})
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
        # Redis unavailable — fail open when not configured for fail-closed (avoid hard outage in dev).
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
write_sensitive_rate_limit = make_rate_limit_dep("write_sensitive")
state_transition_rate_limit = make_rate_limit_dep("state_transition")
