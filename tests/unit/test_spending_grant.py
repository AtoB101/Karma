"""Spending grant primitive + hard server-side gate."""
from __future__ import annotations

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException

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
