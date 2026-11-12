"""窗口内授权：钱包签名即批准（不依赖操作台会话）。

钉住三件事：
1. approve-challenge 只回待签文字，不写任何凭据；
2. 钱包 personal_sign 验签通过 + 钱包已绑主身份 => 批准成立；
3. agent 用自己手里的 pairing_code 照常领到凭据。
"""
from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from db.models.orm import Base, IdentityProfileModel
from db.session import get_db
from services import agent_pairing as pairing
from services.agent_bootstrap_credentials import reset_bootstrap_keys
from services.agent_onboarding_template import load_onboarding_catalog
from services.agent_profile_store import clear_profile_cards

OWNER = "kid_signedowner0001"


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pair.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_AGENT_KEY_DIR", str(tmp_path / "agent_keys"))
    monkeypatch.setattr(pairing, "_STORE_PATH", tmp_path / "agent_pairing.json")
    reset_bootstrap_keys()
    pairing.reset_pairings()
    pairing.reset_approve_challenges()
    clear_profile_cards()
    load_onboarding_catalog.cache_clear()
    yield
    reset_bootstrap_keys()
    pairing.reset_pairings()
    pairing.reset_approve_challenges()
    clear_profile_cards()
    load_onboarding_catalog.cache_clear()


async def _client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _new_agent_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    return key, pub


def _sign_pairing_request(*, key, agent_name: str, public_key: str) -> dict[str, str]:
    from services.runtime_wallet import build_agent_pairing_request_message

    nonce = secrets.token_hex(16)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    message = build_agent_pairing_request_message(
        agent_name=agent_name, public_key=public_key, nonce=nonce, timestamp=timestamp
    )
    return {
        "signature": base64.b64encode(key.sign(message.encode("utf-8"))).decode(),
        "nonce": nonce,
        "timestamp": timestamp,
    }


async def _open_request(client, public_key, signed, **over):
    body = {
        "agent_name": "OpenClaw 采购助手",
        "platform": "openclaw",
        "public_key": public_key,
        **signed,
        **over,
    }
    resp = await client.post("/v1/agent-pairing/request", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_signed_approve_end_to_end(db_session):
    wallet = Account.create()
    db_session.add(
        IdentityProfileModel(
            identity_id=OWNER,
            display_id="KID-SIGNED-01",
            legal_identity_status="bound",
            status="active",
            bound_wallet_address=wallet.address.lower(),
        )
    )
    await db_session.commit()

    client = await _client(db_session)
    agent_key, pub = _new_agent_key()
    signed = _sign_pairing_request(key=agent_key, agent_name="OpenClaw 采购助手", public_key=pub)
    req = await _open_request(client, pub, signed, requested_side="buyer", requested_vertical="food")

    ch = await client.post(
        "/v1/agent-pairing/approve-challenge",
        json={"user_code": req["user_code"], "wallet_address": wallet.address, "side": "buyer", "vertical": "food"},
    )
    assert ch.status_code == 200, ch.text
    challenge = ch.json()
    assert challenge["challenge_id"]
    assert "Karma Agent Pairing Approve" in challenge["message"]
    assert "sign_url" in challenge

    signature = "0x" + Account.sign_message(
        encode_defunct(text=challenge["message"]), private_key=wallet.key
    ).signature.hex()
    ap = await client.post(
        "/v1/agent-pairing/approve-signed",
        json={"challenge_id": challenge["challenge_id"], "signature": signature},
    )
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] == "approved"

    cl = await client.post("/v1/agent-pairing/claim", json={"pairing_code": req["pairing_code"]})
    assert cl.status_code == 200, cl.text
    body = cl.json()
    assert body["credentials"].get("api_key")


async def test_signed_approve_rejects_wrong_wallet(db_session):
    wallet = Account.create()
    client = await _client(db_session)
    agent_key, pub = _new_agent_key()
    signed = _sign_pairing_request(key=agent_key, agent_name="OpenClaw 采购助手", public_key=pub)
    req = await _open_request(client, pub, signed, requested_side="buyer")

    ch = await client.post(
        "/v1/agent-pairing/approve-challenge",
        json={"user_code": req["user_code"], "wallet_address": wallet.address, "side": "buyer"},
    )
    assert ch.status_code == 200, ch.text
    challenge = ch.json()

    other = Account.create()
    signature = "0x" + Account.sign_message(
        encode_defunct(text=challenge["message"]), private_key=other.key
    ).signature.hex()
    ap = await client.post(
        "/v1/agent-pairing/approve-signed",
        json={"challenge_id": challenge["challenge_id"], "signature": signature},
    )
    assert ap.status_code in (400, 403), ap.text
