"""Bilateral settle/finalize spend-grant gate (agent-side payout path)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock, patch

from api.app import app
from config.settings import settings
from db.models.orm import SpendingGrantModel
from db.session import get_db

AGENT = "agent-1"
SECRET = "secret-1"
API_KEY = f"karma_{AGENT}_{SECRET}"


async def _seed_grant(db) -> None:
    db.add(
        SpendingGrantModel(
            grant_id="g1",
            owner_identity_id="owner-1",
            owner_wallet_address="0x" + "ab" * 20,
            agent_id=AGENT,
            currency="USDC",
            token_address=None,
            total_limit=100.0,
            per_tx_limit=100.0,
            used_amount=0.0,
            purpose_scope=[],
            status="active",
            expires_at=None,
            nonce="n",
            signature="",
            signed_message="",
        )
    )
    await db.commit()


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setattr(settings, "spending_grant_enforced", True)
    monkeypatch.setattr(settings, "auth_api_keys", f"{AGENT}:{SECRET}")


@pytest.fixture
def chain_mock():
    mock = MagicMock()
    mock.settle_direct.return_value = MagicMock()
    mock.finalize_binding.return_value = MagicMock()
    mock.binding_status.return_value = {"binding_id": 1, "state": 2}
    with patch("api.routes.bilateral._chain", return_value=mock):
        yield mock


@pytest.mark.asyncio
async def test_settle_requires_agent_identity_when_enforced(db_session, enforce, chain_mock):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/bilateral/settle",
                json={"binding_id": 1, "proof_hash": "0x" + "ab" * 32},
            )
            assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settle_denies_agent_without_grant(db_session, enforce, chain_mock):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/bilateral/settle",
                json={"binding_id": 1, "proof_hash": "0x" + "ab" * 32},
                headers={"x-karma-api-key": API_KEY},
            )
            assert r.status_code == 403
            assert "spending grant denied" in r.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settle_allows_agent_with_active_grant(db_session, enforce, chain_mock):
    await _seed_grant(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/bilateral/settle",
                json={"binding_id": 1, "proof_hash": "0x" + "ab" * 32},
                headers={"x-karma-api-key": API_KEY},
            )
            assert r.status_code == 200, r.text
            chain_mock.settle_direct.assert_called_once()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_finalize_denies_agent_without_grant(db_session, enforce, chain_mock):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/bilateral/finalize/1",
                headers={"x-karma-api-key": API_KEY},
            )
            assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
