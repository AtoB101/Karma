"""Spending grant primitive + hard server-side gate."""
from __future__ import annotations

import pytest
from datetime import datetime
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException
from sqlalchemy import select

from db.models.orm import SpendingGrantEventModel
from services import spending_grant

PRIVATE_KEY = "0x1111111111111111111111111111111111111111111111111111111111111111"
WALLET = Account.from_key(PRIVATE_KEY).address
TOKEN = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def _sign(message: str) -> str:
    return Account.sign_message(encode_defunct(text=message), private_key=PRIVATE_KEY).signature.hex()


def _terms(**overrides) -> dict:
    t = dict(
        grant_id="grant-1",
        agent_id="agent-1",
        agent_public_key=None,
        currency="USDC",
        token_address=TOKEN,
        total_limit=100.0,
        per_tx_limit=10.0,
        purpose_scope=[],
        expires_at=None,
        nonce="nonce-123456",
    )
    t.update(overrides)
    return t


def _signature(terms: dict) -> str:
    return _sign(spending_grant.build_grant_message(wallet_address=WALLET, **terms))


async def _create(db, terms: dict):
    return await spending_grant.create_grant(
        db,
        owner_identity_id="owner-1",
        wallet_address=WALLET,
        wallet_signature=_signature(terms),
        **terms,
    )


@pytest.mark.asyncio
async def test_create_grant_stores_signed_terms(db_session):
    terms = _terms(agent_public_key="ed25519-pubkey-placeholder", purpose_scope=["escrow", "ecommerce"])
    grant = await _create(db_session, terms)
    await db_session.commit()
    assert grant.status == "active"
    assert grant.used_amount == 0.0
    assert grant.signature == _signature(terms)
    assert "Karma Spending Grant" in grant.signed_message
    assert grant.agent_public_key == "ed25519-pubkey-placeholder"


@pytest.mark.asyncio
async def test_create_grant_rejects_wrong_signer(db_session):
    terms = _terms()
    sig = _signature(terms)
    # Tamper with one term after signing: the stored terms no longer match the signature.
    terms["nonce"] = "different-nonce"
    with pytest.raises(HTTPException):
        await spending_grant.create_grant(
            db_session,
            owner_identity_id="owner-1",
            wallet_address=WALLET,
            wallet_signature=sig,
            **terms,
        )


@pytest.mark.asyncio
async def test_assert_spend_allowed_rejects_without_grant(db_session):
    with pytest.raises(HTTPException) as exc:
        await spending_grant.assert_spend_allowed(
            db_session, agent_id="no-grant-agent", token_address=TOKEN, amount=5.0
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_spend_within_limits_is_allowed_and_recorded(db_session):
    terms = _terms()
    await _create(db_session, terms)
    await db_session.commit()

    allowed = await spending_grant.assert_spend_allowed(
        db_session, agent_id="agent-1", token_address=TOKEN, amount=5.0
    )
    assert allowed.grant_id == "grant-1"

    await spending_grant.record_spend(db_session, grant_id=allowed.grant_id, amount=5.0)
    await db_session.commit()

    reloaded = await spending_grant.get_grant(db_session, "grant-1")
    assert reloaded.used_amount == pytest.approx(5.0)
    assert reloaded.total_limit - reloaded.used_amount == pytest.approx(95.0)


@pytest.mark.asyncio
async def test_per_tx_limit_is_enforced(db_session):
    await _create(db_session, _terms())
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await spending_grant.assert_spend_allowed(
            db_session, agent_id="agent-1", token_address=TOKEN, amount=10.01
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_total_limit_is_enforced(db_session):
    await _create(db_session, _terms(total_limit=20.0, per_tx_limit=20.0))
    await db_session.commit()
    await spending_grant.record_spend(db_session, grant_id="grant-1", amount=20.0)
    await db_session.commit()
    with pytest.raises(HTTPException):
        await spending_grant.assert_spend_allowed(
            db_session, agent_id="agent-1", token_address=TOKEN, amount=0.01
        )


@pytest.mark.asyncio
async def test_revoked_grant_is_denied(db_session):
    grant = await _create(db_session, _terms())
    await db_session.commit()
    await spending_grant.revoke_grant(db_session, grant=grant, reason="owner changed mind")
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await spending_grant.assert_spend_allowed(
            db_session, agent_id="agent-1", token_address=TOKEN, amount=5.0
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_token_mismatch_is_denied(db_session):
    await _create(db_session, _terms())
    await db_session.commit()
    with pytest.raises(HTTPException):
        await spending_grant.assert_spend_allowed(
            db_session, agent_id="agent-1", token_address="0x" + "0" * 40, amount=5.0
        )

@pytest.mark.asyncio
async def test_owner_scoped_enforcement(db_session):
    await _create(db_session, _terms())
    await db_session.commit()
    with pytest.raises(HTTPException):
        await spending_grant.assert_spend_allowed(
            db_session, agent_id="agent-1", owner_identity_id="owner-2", token_address=TOKEN, amount=5.0
        )


@pytest.mark.asyncio
async def test_deny_event_is_persisted(db_session):
    with pytest.raises(HTTPException):
        await spending_grant.assert_spend_allowed(
            db_session, agent_id="nobody", token_address=TOKEN, amount=5.0
        )
    res = await db_session.execute(
        select(SpendingGrantEventModel).where(SpendingGrantEventModel.event_type == "deny")
    )
    rows = list(res.scalars())
    assert len(rows) == 1
    assert rows[0].agent_id == "nobody"
    assert "grant" in (rows[0].reason or "")


@pytest.mark.asyncio
async def test_lifecycle_events_are_recorded(db_session):
    grant = await _create(db_session, _terms())
    await db_session.commit()
    await spending_grant.record_spend(
        db_session, grant_id="grant-1", amount=5.0, owner_identity_id="owner-1", agent_id="agent-1"
    )
    await db_session.commit()
    await spending_grant.revoke_grant(db_session, grant=grant, reason="done")
    await db_session.commit()
    res = await db_session.execute(select(SpendingGrantEventModel).order_by(SpendingGrantEventModel.id))
    types = [row.event_type for row in res.scalars()]
    assert types == ["created", "spend", "revoked"]

@pytest.mark.asyncio
async def test_create_grant_persists_agent_name(db_session):
    terms = _terms()
    grant = await spending_grant.create_grant(
        db_session,
        owner_identity_id="owner-1",
        wallet_address=WALLET,
        wallet_signature=_signature(terms),
        agent_name="  OpenClaw 采购助手  ",
        **terms,
    )
    await db_session.commit()
    assert grant.agent_name == "OpenClaw 采购助手"
    assert spending_grant._grant_to_dict(grant)["agent_name"] == "OpenClaw 采购助手"


@pytest.mark.asyncio
async def test_create_grant_without_agent_name_is_none(db_session):
    terms = _terms()
    grant = await _create(db_session, terms)
    await db_session.commit()
    assert grant.agent_name is None


@pytest.mark.asyncio
async def test_reduce_grant_lowers_limit_and_records_event(db_session):
    grant = await _create(db_session, _terms(total_limit=100.0, per_tx_limit=50.0))
    await db_session.commit()
    await spending_grant.reduce_grant(db_session, grant=grant, new_total_limit=60.0, reason="tighten budget")
    await db_session.commit()

    reloaded = await spending_grant.get_grant(db_session, "grant-1")
    assert reloaded.total_limit == pytest.approx(60.0)
    assert reloaded.status == "active"

    events = await spending_grant.list_grant_events(db_session, grant_id="grant-1")
    types = [e.event_type for e in events]
    assert types == ["limit_reduced", "created"]


@pytest.mark.asyncio
async def test_reduce_grant_rejects_increase(db_session):
    grant = await _create(db_session, _terms(total_limit=100.0))
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await spending_grant.reduce_grant(db_session, grant=grant, new_total_limit=120.0)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_reduce_grant_rejects_below_used(db_session):
    grant = await _create(db_session, _terms(total_limit=100.0, per_tx_limit=100.0))
    await db_session.commit()
    await spending_grant.record_spend(db_session, grant_id="grant-1", amount=30.0)
    await db_session.commit()
    reloaded = await spending_grant.get_grant(db_session, "grant-1")
    with pytest.raises(HTTPException) as exc:
        await spending_grant.reduce_grant(db_session, grant=reloaded, new_total_limit=20.0)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_reduce_grant_rejects_non_active(db_session):
    grant = await _create(db_session, _terms())
    await db_session.commit()
    await spending_grant.revoke_grant(db_session, grant=grant, reason="done")
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await spending_grant.reduce_grant(db_session, grant=grant, new_total_limit=10.0)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_list_grant_events_scopes_by_owner(db_session):
    await _create(db_session, _terms(grant_id="grant-a"))
    await db_session.commit()
    await _create(db_session, _terms(grant_id="grant-b", agent_id="agent-2", nonce="nonce-654321"))
    await db_session.commit()

    rows = await spending_grant.list_grant_events(db_session, owner_identity_id="owner-1")
    grant_ids = {e.grant_id for e in rows}
    assert grant_ids == {"grant-a", "grant-b"}
    assert all(e.owner_identity_id == "owner-1" for e in rows)


@pytest.mark.asyncio
async def test_assert_agent_authorized_requires_active_grant(db_session):
    with pytest.raises(HTTPException) as exc:
        await spending_grant.assert_agent_authorized(db_session, agent_id="no-grant-agent")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_agent_authorized_passes_with_active_grant(db_session):
    await _create(db_session, _terms())
    await db_session.commit()
    grant = await spending_grant.assert_agent_authorized(db_session, agent_id="agent-1")
    assert grant.grant_id == "grant-1"


@pytest.mark.asyncio
async def test_assert_agent_authorized_rejects_revoked_grant(db_session):
    grant = await _create(db_session, _terms())
    await db_session.commit()
    await spending_grant.revoke_grant(db_session, grant=grant, reason="revoked")
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await spending_grant.assert_agent_authorized(db_session, agent_id="agent-1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_agent_authorized_rejects_expired_grant(db_session):
    grant = await _create(db_session, _terms())
    grant.expires_at = datetime(2020, 1, 1)
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await spending_grant.assert_agent_authorized(db_session, agent_id="agent-1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_agent_authorized_ignores_allowance(db_session):
    await _create(db_session, _terms(total_limit=1.0, per_tx_limit=1.0))
    await db_session.commit()
    # 已经花光额度（used == total），放款/结算仍应只查「授权是否存活」，不查剩余额度。
    await spending_grant.record_spend(db_session, grant_id="grant-1", amount=1.0)
    await db_session.commit()
    grant = await spending_grant.assert_agent_authorized(db_session, agent_id="agent-1")
    assert grant.grant_id == "grant-1"

