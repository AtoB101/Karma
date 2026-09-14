"""The rate limiter must key on a dimension the caller cannot choose.

Regression guard for the ``X-Forwarded-For`` bypass: nginx builds that header
with ``$proxy_add_x_forwarded_for``, so a caller can prepend arbitrary values.
Keying the bucket on the raw header let one client rotate it and walk straight
past every limit in ``RATE_LIMITS``.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.middleware import rate_limit as rl
from config.settings import settings

PUBLIC_PEER = "203.0.113.9"
NGINX_PEER = "172.17.0.1"


def _request(headers: dict[str, str] | None = None, peer: str = PUBLIC_PEER) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/auth/token",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": (peer, 12345),
        }
    )


@pytest.fixture()
def no_redis(monkeypatch):
    """Force the process-local fallback so the counts are deterministic here."""

    async def _boom():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(rl, "get_redis", _boom)
    monkeypatch.setattr(settings, "rate_limit_redis_fail_closed", False)


# ---------------------------------------------------------------------------
# Which value becomes the bucket
# ---------------------------------------------------------------------------


def test_forwarded_headers_are_ignored_when_the_peer_is_not_a_trusted_proxy():
    req = _request({"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"})
    assert rl.real_client_ip(req) == PUBLIC_PEER
    assert rl.rate_limit_bucket(req) == f"ip:{PUBLIC_PEER}"


def test_rotating_forwarded_for_cannot_change_the_bucket():
    seen = {
        rl.rate_limit_bucket(_request({"X-Forwarded-For": ip}))
        for ip in ("1.2.3.4", "5.6.7.8", "9.9.9.9")
    }
    assert seen == {f"ip:{PUBLIC_PEER}"}


def test_trusted_proxy_uses_the_address_our_proxy_appended():
    # nginx appends $remote_addr, so the *last* entry is the real client.
    req = _request({"X-Forwarded-For": "1.2.3.4, 198.51.100.4"}, peer=NGINX_PEER)
    assert rl.real_client_ip(req) == "198.51.100.4"


def test_trusted_proxy_prefers_x_real_ip():
    req = _request({"X-Real-IP": "198.51.100.5", "X-Forwarded-For": "1.2.3.4"}, peer="127.0.0.1")
    assert rl.real_client_ip(req) == "198.51.100.5"


def test_bucket_falls_back_to_the_peer_without_any_headers():
    assert rl.real_client_ip(_request(peer="10.0.0.7")) == "10.0.0.7"


# ---------------------------------------------------------------------------
# Which credential earns its own bucket
# ---------------------------------------------------------------------------


def test_invented_api_key_does_not_earn_its_own_bucket(monkeypatch):
    monkeypatch.setattr(settings, "auth_api_keys", "agent-a:sk-real")
    seen = {rl.rate_limit_bucket(_request({"X-Karma-Api-Key": f"made-up-{i}"})) for i in range(3)}
    assert seen == {f"ip:{PUBLIC_PEER}"}


def test_configured_api_key_gets_its_own_bucket(monkeypatch):
    monkeypatch.setattr(settings, "auth_api_keys", "agent-a:sk-real")
    digest = hashlib.sha256(b"sk-real").hexdigest()[:40]
    req = _request({"X-Karma-Api-Key": "sk-real"})
    assert rl.rate_limit_bucket(req) == f"ak:{digest}"


# ---------------------------------------------------------------------------
# The limiter itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotating_forwarded_for_cannot_walk_past_the_limit(no_redis):
    max_requests, _ = rl.RATE_LIMITS["register"]
    for i in range(max_requests):
        await rl.rate_limit(_request({"X-Forwarded-For": f"10.9.9.{i}"}), "register")
    with pytest.raises(HTTPException) as exc:
        await rl.rate_limit(_request({"X-Forwarded-For": "10.9.9.99"}), "register")
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_rotating_api_key_cannot_walk_past_the_limit(no_redis):
    max_requests, _ = rl.RATE_LIMITS["register"]
    for i in range(max_requests):
        await rl.rate_limit(_request({"X-Karma-Api-Key": f"invented-{i}"}), "register")
    with pytest.raises(HTTPException) as exc:
        await rl.rate_limit(_request({"X-Karma-Api-Key": "invented-final"}), "register")
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_distinct_peers_keep_distinct_budgets(no_redis):
    max_requests, _ = rl.RATE_LIMITS["register"]
    for _ in range(max_requests):
        await rl.rate_limit(_request(peer="198.51.100.10"), "register")
    # a different client is unaffected
    await rl.rate_limit(_request(peer="198.51.100.11"), "register")


class _FakePipeline:
    def __init__(self, store):
        self._store = store
        self._ops = []

    def zremrangebyscore(self, key, low, high):
        hits = self._store.setdefault(key, {})
        for member in [m for m, score in hits.items() if low <= score <= high]:
            del hits[member]
        return self

    def zadd(self, key, mapping):
        self._store.setdefault(key, {}).update(mapping)
        return self

    def zcard(self, key):
        self._ops.append(len(self._store.get(key, {})))
        return self

    def expire(self, key, ttl):
        return self

    async def execute(self):
        return list(self._ops)


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return _FakePipeline(self.store)


@pytest.mark.asyncio
async def test_requests_in_the_same_tick_do_not_overwrite_each_other(monkeypatch):
    """Two requests inside one clock tick used to share a sorted-set member."""
    fake = _FakeRedis()

    async def _redis():
        return fake

    monkeypatch.setattr(rl, 'get_redis', _redis)
    frozen = 1000.0
    monkeypatch.setattr(rl.time, 'time', lambda: frozen)
    max_requests, _ = rl.RATE_LIMITS['register']

    for _ in range(max_requests):
        await rl.rate_limit(_request(), 'register')
    with pytest.raises(HTTPException) as exc:
        await rl.rate_limit(_request(), 'register')
    assert exc.value.status_code == 429
    recorded = fake.store[f'ratelimit:register:ip:{PUBLIC_PEER}']
    assert len(recorded) == max_requests + 1
