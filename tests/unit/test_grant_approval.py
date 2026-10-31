"""Owner-facing spending grant approval handshake (device-flow style)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from httpx import ASGITransport, AsyncClient

from api.app import app
from db.models.orm import Base, IdentityProfileModel, SpendingGrantModel
from db.session import get_db
from services import grant_approval

PRIVATE_KEY = "0x2222222222222222222222222222222222222222222222222222222222222222"
WALLET = Account.from_key(PRIVATE_KEY)
TOKEN = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def _sign(message: str, account: Account = WALLET) -> str:
    return "0x" + Account.sign_message(
        encode_defunct(text=message), private_key=account.key
    ).signature.hex()


def _issue(**overrides) -> dict:
    args = dict(
        agent_id="agent-1",
        agent_name="OpenClaw 采购助手",
        agent_public_key=None,
        currency="USDC",
        token_address=TOKEN,
        total_limit=100.0,
        per_tx_limit=10.0,
        purpose_scope=["escrow", "ecommerce"],
        expires_at=None,
    )
    args.update(overrides)
    return grant_approval.issue_grant_approval(**args)


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/grant.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(grant_approval, "_STORE_PATH", tmp_path / "grant_approval.json")
    grant_approval.reset_grant_approvals()
    yield
    grant_approval.reset_grant_approvals()


async def _bind_wallet(db, wallet_address: str, identity_id: str = "owner-1"):
    db.add(
        IdentityProfileModel(
            identity_id=identity_id,
            display_id="KID-" + identity_id.upper()[:8],
            legal_identity_status="bound",
            status="active",
            bound_wallet_address=wallet_address.lower(),
        )
    )
    await db.commit()


async def _approve(db, challenge: dict, *, account: Account = WALLET, code: str | None = None, wallet_address: str | None = None):
    wallet_address = wallet_address or account.address
    message = grant_approval.sign_message_for(challenge["challenge_id"], wallet_address)
    signature = _sign(message, account)
    return await grant_approval.approve_grant_approval(
        db,
        challenge_id=challenge["challenge_id"],
        confirmation_code=code if code is not None else challenge["confirmation_code"],
        wallet_address=wallet_address,
        wallet_signature=signature,
    )


def test_issue_returns_code_and_approval_uri():
    ch = _issue()
    assert ch["challenge_id"]
    assert len(ch["confirmation_code"]) == 9  # XXXX-XXXX
    assert "/console/pages/grant-approval/" in ch["approval_uri"]
    assert ch["expires_in_seconds"] == grant_approval.DEFAULT_TTL_SECONDS


def test_public_view_hides_confirmation_code():
    ch = _issue(agent_public_key="not-a-real-ed25519-key")
    view = grant_approval.public_view(ch["challenge_id"])
    assert "confirmation_code" not in view
    assert view["agent_name"] == "OpenClaw 采购助手"
    assert view["total_limit"] == 100.0
    assert view["per_tx_limit"] == 10.0
    assert view["attempts_left"] == grant_approval.MAX_ATTEMPTS
    assert view["status"] == "pending"


def test_sign_message_reconstructs_canonical_terms():
    ch = _issue()
    message = grant_approval.sign_message_for(ch["challenge_id"], WALLET.address)
    assert "Karma Spending Grant" in message
    assert f"wallet_address:{WALLET.address}" in message
    assert "agent_id:agent-1" in message


@pytest.mark.asyncio
async def test_approve_creates_grant(db_session):
    await _bind_wallet(db_session, WALLET.address)
    ch = _issue()
    grant = await _approve(db_session, ch)
    await db_session.commit()
    assert grant["status"] == "active"
    assert grant["total_limit"] == 100.0
    assert grant["owner_identity_id"] == "owner-1"
    assert grant["agent_id"] == "agent-1"

    rows = list((await db_session.execute(
        __import__("sqlalchemy").select(SpendingGrantModel).where(SpendingGrantModel.grant_id == grant["grant_id"])
    )).scalars())
    assert len(rows) == 1

    view = grant_approval.public_view(ch["challenge_id"])
    assert view["status"] == "approved"


@pytest.mark.asyncio
async def test_approve_rejects_wrong_confirmation_code(db_session):
    await _bind_wallet(db_session, WALLET.address)
    ch = _issue()
    with pytest.raises(HTTPException) as exc:
        await _approve(db_session, ch, code="AAAA-AAAA")
    assert exc.value.status_code == 403
    view = grant_approval.public_view(ch["challenge_id"])
    assert view["attempts_left"] == grant_approval.MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_approve_locks_after_too_many_attempts(db_session):
    await _bind_wallet(db_session, WALLET.address)
    ch = _issue()
    for _ in range(grant_approval.MAX_ATTEMPTS):
        with pytest.raises(HTTPException) as exc:
            await _approve(db_session, ch, code="ZZZZ-ZZZZ")
        assert exc.value.status_code == 403
    view = grant_approval.public_view(ch["challenge_id"])
    assert view["status"] == "expired"
    assert view["attempts_left"] == 0


@pytest.mark.asyncio
async def test_approve_rejects_wrong_wallet_signature(db_session):
    await _bind_wallet(db_session, WALLET.address)
    other = Account.create()
    ch = _issue()
    with pytest.raises(HTTPException) as exc:
        await _approve(db_session, ch, account=other)
    assert exc.value.status_code in (400, 403)

    rows = list((await db_session.execute(
        __import__("sqlalchemy").select(SpendingGrantModel)
    )).scalars())
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_approve_requires_bound_wallet(db_session):
    ch = _issue()
    with pytest.raises(HTTPException) as exc:
        await _approve(db_session, ch)
    assert exc.value.status_code == 403
    assert "bound" in str(exc.value.detail).lower() or "identity" in str(exc.value.detail).lower()


def test_expired_challenge_is_rejected(db_session, monkeypatch):
    monkeypatch.setattr(grant_approval, "DEFAULT_TTL_SECONDS", -1)
    ch = _issue()
    with pytest.raises(HTTPException) as exc:
        grant_approval.sign_message_for(ch["challenge_id"], WALLET.address)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_approval_routes_end_to_end(db_session):
    await _bind_wallet(db_session, WALLET.address)
    ch = _issue()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        view = await client.get(f"/v1/spending-grants/approval/{ch['challenge_id']}")
        assert view.status_code == 200, view.text
        assert view.json()["agent_name"] == "OpenClaw 采购助手"

        sign = await client.get(
            f"/v1/spending-grants/approval/{ch['challenge_id']}/sign-message",
            params={"wallet_address": WALLET.address},
        )
        assert sign.status_code == 200, sign.text
        message = sign.json()["message"]
        signature = _sign(message)

        approve = await client.post(
            f"/v1/spending-grants/approval/{ch['challenge_id']}/approve",
            json={
                "confirmation_code": ch["confirmation_code"],
                "wallet_address": WALLET.address,
                "wallet_signature": signature,
            },
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["status"] == "active"
    finally:
        await client.aclose()
        app.dependency_overrides.pop(get_db, None)
