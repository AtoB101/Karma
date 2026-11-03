"""Self-serve first key: challenge → claim → grant-gated upgrade."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from db.models.orm import Base, SpendingGrantModel
from db.session import get_db
from services import agent_bootstrap_credentials as bc
from services import agent_first_key as fk

DEVICE = "device-0123456789abcdef"
IP = "203.0.113.7"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(fk, "_STORE_PATH", tmp_path / "agent_first_key.json")
    monkeypatch.setattr(bc, "_STORE_PATH", tmp_path / "agent_api_keys.json")
    fk.reset_first_keys()
    bc.reset_bootstrap_keys()
    yield
    fk.reset_first_keys()
    bc.reset_bootstrap_keys()


def _issue(device_id=DEVICE, ip=IP) -> dict:
    return fk.issue_challenge(device_id=device_id, ip=ip, agent_name="测试助手")


def _claim(ch: dict, *, device_id=DEVICE, ip=IP, challenge: str | None = None) -> dict:
    return fk.claim(
        challenge_id=ch["challenge_id"],
        challenge=challenge if challenge is not None else ch["challenge"],
        device_id=device_id,
        ip=ip,
    )


def test_challenge_issue_and_public_view_hide_challenge():
    ch = _issue()
    assert ch["challenge_id"] and ch["challenge"]
    view = fk.public_view(ch["challenge_id"])
    assert view["status"] == "pending"
    assert "challenge" not in view


def test_claim_mints_restricted_key_once():
    ch = _issue()
    issued = _claim(ch)
    assert issued["scope"] == ["grant:apply"]
    assert issued["expires_at"] is not None
    secret = issued["api_key"].split("_", 2)[2]
    assert bc.verify_minted_api_key(issued["agent_id"], secret) is True
    assert bc.minted_key_scope(issued["agent_id"]) == ["grant:apply"]
    # second claim is rejected
    with pytest.raises(HTTPException) as exc:
        _claim(ch)
    assert exc.value.status_code == 409


def test_claim_rejects_wrong_challenge():
    ch = _issue()
    with pytest.raises(HTTPException) as exc:
        _claim(ch, challenge="wrong-wrong-wrong")
    assert exc.value.status_code == 403
    assert fk.public_view(ch["challenge_id"])["attempts_left"] == fk.MAX_ATTEMPTS - 1


def test_claim_rejects_device_or_ip_mismatch():
    ch = _issue()
    with pytest.raises(HTTPException) as exc:
        _claim(ch, device_id="device-other-00000000")
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        _claim(ch, ip="198.51.100.9")
    assert exc.value.status_code == 403


def test_challenge_caps_pending_per_device_and_ip():
    for _ in range(fk.MAX_PENDING_PER_DEVICE):
        _issue(device_id="device-busy-00000000")
    with pytest.raises(HTTPException) as exc:
        _issue(device_id="device-busy-00000000")
    assert exc.value.status_code == 429


def test_expired_challenge_is_rejected(monkeypatch):
    monkeypatch.setattr(fk, "CHALLENGE_TTL_SECONDS", -1)
    ch = _issue()
    with pytest.raises(HTTPException) as exc:
        _claim(ch)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_upgrade_requires_active_grant(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fk.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        issued = bc.mint_restricted_api_key("agent-up")
        with pytest.raises(HTTPException) as exc:
            await fk.upgrade(session, agent_id="agent-up")
        assert exc.value.status_code == 403

        session.add(
            SpendingGrantModel(
                grant_id="grant-up-1",
                owner_identity_id="owner-1",
                owner_wallet_address="0x" + "1" * 40,
                agent_id="agent-up",
                currency="USDC",
                total_limit=100.0,
                per_tx_limit=10.0,
                status="active",
                nonce="nonce-up-1",
                signature="0x" + "2" * 130,
                signed_message="Karma Spending Grant",
            )
        )
        await session.commit()

        upgraded = await fk.upgrade(session, agent_id="agent-up")
        assert upgraded["scope"] == ["*"]
        new_secret = upgraded["api_key"].split("_", 2)[2]
        assert bc.verify_minted_api_key("agent-up", new_secret) is True
        # old restricted secret is consumed
        old_secret = issued["api_key"].split("_", 2)[2]
        assert bc.verify_minted_api_key("agent-up", old_secret) is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_first_key_http_flow(tmp_path):
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
            r = await client.post(
                "/v1/agents/first-key/challenge",
                json={"device_id": "device-http-000000", "agent_name": "HTTP 测试"},
            )
            assert r.status_code == 201, r.text
            challenge = r.json()["challenge"]
            challenge_id = r.json()["challenge_id"]

            r = await client.post(
                "/v1/agents/first-key/claim",
                json={"challenge_id": challenge_id, "challenge": challenge, "device_id": "device-http-000000"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["scope"] == ["grant:apply"]

            # restricted key is denied a protected spending-ish route, allowed upgrade path
            headers = {"X-Karma-Api-Key": body["api_key"]}
            r = await client.get("/v1/console/capabilities", headers=headers)
            assert r.status_code in (401, 403), r.text

            # upgrade without grant -> 403
            r = await client.post("/v1/agents/first-key/upgrade", headers=headers)
            assert r.status_code == 403, r.text
        finally:
            await client.aclose()
            app.dependency_overrides.pop(get_db, None)
    await engine.dispose()
