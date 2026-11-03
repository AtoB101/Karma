"""Permission-scoped "first key": grant-application only, denied everywhere else.

The first key a brand-new agent holds must not be able to spend, settle, mint or
mutate anything. It may only open the owner-approval handshake
(``POST /v1/spending-grants/approval-request``). These tests pin the scope
bookkeeping and the middleware enforcement that makes that guarantee real.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from api.middleware import auth
from db.models.orm import Base
from db.session import get_db
from services import agent_bootstrap_credentials as bc
from services import grant_approval


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "_STORE_PATH", tmp_path / "agent_api_keys.json")
    monkeypatch.setattr(grant_approval, "_STORE_PATH", tmp_path / "grant_approval.json")
    bc.reset_bootstrap_keys()
    grant_approval.reset_grant_approvals()
    yield
    bc.reset_bootstrap_keys()
    grant_approval.reset_grant_approvals()


def _secret(issued: dict) -> str:
    return issued["api_key"].split("_", 2)[2]


def test_restricted_key_carries_scope_and_is_verifiable():
    issued = bc.mint_restricted_api_key("agent-restricted", scope=["grant:apply"], ttl_seconds=3600)
    assert issued["scope"] == ["grant:apply"]
    assert issued["expires_at"] is not None
    assert bc.verify_minted_api_key("agent-restricted", _secret(issued)) is True
    assert bc.minted_key_scope("agent-restricted") == ["grant:apply"]


def test_restricted_key_rejects_wildcard_scope():
    with pytest.raises(ValueError):
        bc.mint_restricted_api_key("agent-x", scope=["*"])


def test_full_key_defaults_to_wildcard_scope():
    issued = bc.mint_agent_api_key("agent-full")
    assert bc.minted_key_scope("agent-full") == ["*"]
    assert bc.verify_minted_api_key("agent-full", _secret(issued)) is True


def test_expired_restricted_key_is_rejected():
    issued = bc.mint_restricted_api_key("agent-exp", ttl_seconds=3600)
    bc._ensure_loaded()
    with bc._LOCK:
        bc._KEYS["agent-exp"]["expires_at"] = "2000-01-01T00:00:00Z"
    assert bc.verify_minted_api_key("agent-exp", _secret(issued)) is False


def test_revoke_minted_key():
    issued = bc.mint_restricted_api_key("agent-revoke")
    assert bc.revoke_minted_api_key("agent-revoke") is True
    assert bc.verify_minted_api_key("agent-revoke", _secret(issued)) is False


def test_scope_lookup_returns_none_for_unknown_key():
    assert auth._minted_api_key_scope("karma_nope_notreal") is None


def test_scope_enforcement_denies_non_allowlist_paths():
    issued = bc.mint_restricted_api_key("agent-enforce", scope=["grant:apply"])
    key = issued["api_key"]
    assert auth._minted_api_key_scope(key) == ["grant:apply"]
    with pytest.raises(HTTPException) as exc:
        auth._enforce_minted_key_scope(key, "/v1/console/capabilities")
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        auth._enforce_minted_key_scope(key, "/v1/settlement/create")


def test_scope_enforcement_allows_approval_paths():
    issued = bc.mint_restricted_api_key("agent-allow", scope=["grant:apply"])
    key = issued["api_key"]
    auth._enforce_minted_key_scope(key, "/v1/spending-grants/approval-request")
    auth._enforce_minted_key_scope(key, "/v1/spending-grants/approval/abc123")


def test_full_key_is_never_restricted():
    issued = bc.mint_agent_api_key("agent-free")
    auth._enforce_minted_key_scope(issued["api_key"], "/v1/console/capabilities")


@pytest.mark.asyncio
async def test_restricted_key_can_open_approval_request(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fk.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        try:
            issued = bc.mint_restricted_api_key("agent-http", scope=["grant:apply"])
            headers = {"X-Karma-Api-Key": issued["api_key"]}
            r = await client.post(
                "/v1/spending-grants/approval-request",
                json={
                    "agent_name": "受限首把钥匙测试",
                    "currency": "USDC",
                    "total_limit": 100,
                    "per_tx_limit": 10,
                    "purpose_scope": ["escrow"],
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("challenge_id")
            assert body.get("confirmation_code")
        finally:
            await client.aclose()
            app.dependency_overrides.pop(get_db, None)
    await engine.dispose()
