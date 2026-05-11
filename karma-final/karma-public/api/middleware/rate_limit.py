"""
Karma — Rate Limiting Middleware (Redis-backed)
"""
from __future__ import annotations

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

    # Identify client: API key > IP
    client_id = (
        request.headers.get("X-Karma-Api-Key")
        or request.headers.get("X-Forwarded-For")
        or request.client.host
        or "anonymous"
    )

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
        # Redis unavailable — fail open (don't block legitimate traffic)
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
