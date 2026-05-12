"""
Karma — Rate Limiting Middleware (Redis-backed)
"""
from __future__ import annotations

import hashlib
import re
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
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=settings.redis_max_connections,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        )
    return _redis


def _client_fingerprint(request: Request) -> str:
    api_key = request.headers.get("X-Karma-Api-Key")
    if api_key:
        parts = api_key.split("_", 2)
        if len(parts) == 3 and parts[0] == "karma":
            agent_id = parts[1].strip()
            if _CLIENT_ID_RE.match(agent_id):
                return f"agent:{agent_id}"
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:24]
        return f"api:{digest}"

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if _CLIENT_ID_RE.match(first_ip):
            return f"ip:{first_ip}"
        digest = hashlib.sha256(first_ip.encode("utf-8")).hexdigest()[:24]
        return f"ip:{digest}"

    remote_ip = request.client.host if request.client else "anonymous"
    if _CLIENT_ID_RE.match(remote_ip):
        return f"ip:{remote_ip}"
    digest = hashlib.sha256(remote_ip.encode("utf-8")).hexdigest()[:24]
    return f"ip:{digest}"


async def rate_limit(request: Request, limit_key: str = "default") -> None:
    """
    Sliding window rate limiter using Redis.
    Raises 429 if limit exceeded.
    """
    max_requests, window_seconds = RATE_LIMITS.get(limit_key, RATE_LIMITS["default"])

    # Identify client: API key > IP
    client_id = _client_fingerprint(request)
    if len(client_id) > settings.redis_key_max_length:
        client_id = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[: settings.redis_key_max_length]

    redis_key = f"ratelimit:{limit_key}:{client_id}"
    now = time.time()
    window_start = now - window_seconds

    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        member = f"{now:.6f}:{time.time_ns()}"
        pipe.zadd(redis_key, {member: now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()
        count = results[2]
    except Exception:
        # Redis unavailable — fail closed for sensitive keys.
        env = (settings.app_env or "").lower()
        fail_closed_enabled = env in {"production", "prod", "staging", "stage"}
        if fail_closed_enabled and limit_key in settings.rate_limit_fail_closed_key_set():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiter unavailable for sensitive operation",
            )
        # Non-sensitive paths remain fail-open.
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
