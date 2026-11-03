"""End-to-end: first key -> owner approval -> grant-gated upgrade -> spend scope.

Walks the exact chain a real new agent performs against the running app, proving
the restricted "first key" can never spend, and that it only gains full scope
after the owner wallet-signs an active spending grant.
"""
from __future__ import annotations

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from db.models.orm import Base, IdentityProfileModel
from db.session import get_db
from services import agent_bootstrap_credentials as bc
from services import agent_first_key as fk
from services import grant_approval

OWNER_KEY = "0x3333333333333333333333333333333333333333333333333333333333333333"
OWNER = Account.from_key(OWNER_KEY)
DEVICE = "device-e2e-000000000000"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(fk, "_STORE_PATH", tmp_path / "agent_first_key.json")
    monkeypatch.setattr(bc, "_STORE_PATH", tmp_path / "agent_api_keys.json")
    monkeypatch.setattr(grant_approval, "_STORE_PATH", tmp_path / "grant_approval.json")
    fk.reset_first_keys()
    bc.reset_bootstrap_keys()
    grant_approval.reset_grant_approvals()
    yield
    fk.reset_first_keys()
    bc.reset_bootstrap_keys()
    grant_approval.reset_grant_approvals()


def _sign(message: str) -> str:
    return "0x" + Account.sign_message(
        encode_defunct(text=message), private_key=OWNER.key
    ).signature.hex()


@pytest.mark.asyncio
async def test_full_first_key_to_upgrade_chain(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/e2e.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        # owner wallet is bound to an identity so approve resolves the owner
        session.add(
            IdentityProfileModel(
                identity_id="owner-e2e",
                display_id="KID-OWNER-E2E",
                legal_identity_status="bound",
                status="active",
                bound_wallet_address=OWNER.address.lower(),
            )
        )
        await session.commit()

        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        try:
            # 1. challenge -> claim
            r = await client.post(
                "/v1/agents/first-key/challenge",
                json={"device_id": DEVICE, "agent_name": "E2E 新 agent"},
            )
            assert r.status_code == 201, r.text
            challenge_id = r.json()["challenge_id"]
            challenge = r.json()["challenge"]

            r = await client.post(
                "/v1/agents/first-key/claim",
                json={"challenge_id": challenge_id, "challenge": challenge, "device_id": DEVICE},
            )
            assert r.status_code == 200, r.text
            restricted = r.json()
            agent_id = restricted["agent_id"]
            restricted_key = restricted["api_key"]
            assert restricted["scope"] == ["grant:apply"]
            headers = {"X-Karma-Api-Key": restricted_key}

            # 2. restricted key cannot reach a protected non-allowlist route
            r = await client.get("/v1/console/capabilities", headers=headers)
            assert r.status_code in (401, 403), r.text

            # 3. restricted key opens the owner approval handshake
            r = await client.post(
                "/v1/spending-grants/approval-request",
                json={
                    "agent_name": "E2E 新 agent",
                    "currency": "USDC",
                    "total_limit": 50,
                    "per_tx_limit": 10,
                    "purpose_scope": ["escrow"],
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            approval_challenge = r.json()

            # 4. owner signs and approves the grant
            sign = await client.get(
                f"/v1/spending-grants/approval/{approval_challenge['challenge_id']}/sign-message",
                params={"wallet_address": OWNER.address},
            )
            assert sign.status_code == 200, sign.text
            message = sign.json()["message"]
            r = await client.post(
                f"/v1/spending-grants/approval/{approval_challenge['challenge_id']}/approve",
                json={
                    "confirmation_code": approval_challenge["confirmation_code"],
                    "wallet_address": OWNER.address,
                    "wallet_signature": _sign(message),
                },
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "active"

            # 5. upgrade now succeeds with an active grant
            r = await client.post("/v1/agents/first-key/upgrade", headers=headers)
            assert r.status_code == 200, r.text
            full = r.json()
            assert full["scope"] == ["*"]
            full_key = full["api_key"]

            # 6. old restricted key is consumed; full key reaches protected routes
            r = await client.post(
                "/v1/spending-grants/approval-request",
                json={"agent_name": "E2E 新 agent", "currency": "USDC", "total_limit": 1, "per_tx_limit": 1},
                headers=headers,
            )
            assert r.status_code in (401, 403), r.text

            r = await client.get(
                "/v1/console/capabilities",
                headers={"X-Karma-Api-Key": full_key},
            )
            assert r.status_code == 200, r.text
            assert r.json().get("actor_id") == agent_id
        finally:
            await client.aclose()
            app.dependency_overrides.pop(get_db, None)
    await engine.dispose()
