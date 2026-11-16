"""Onboarding authorization as a hard precondition for spend."""
from __future__ import annotations

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException

from config.settings import settings
from services import spending_grant
from services.onboarding_authorization import (
    current_prompt,
    reset_onboarding_flows,
    respond_onboarding,
    start_onboarding,
)

_PRIVATE_KEY = "0x1111111111111111111111111111111111111111111111111111111111111111"
_WALLET = Account.from_key(_PRIVATE_KEY).address
_TOKEN = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def _sign(message: str) -> str:
    return "0x" + Account.sign_message(
        encode_defunct(text=message), private_key=_PRIVATE_KEY
    ).signature.hex()


def _complete(identity_id: str) -> None:
    r = start_onboarding(identity_id=identity_id, profile_id="merchant", started_by="agent-1")
    flow_id = r["flow"]["flow_id"]
    for _ in range(7):
        p = current_prompt(flow_id)["prompt"]
        if p is None:
            break
        if p["prompt_type"] == "wallet_sign":
            sig = _sign(p["payload"]["sign_message"])
            r = respond_onboarding(flow_id=flow_id, action="sign", value={"address": _WALLET, "signature": sig})
        elif p["prompt_type"] == "matching_code":
            r = respond_onboarding(flow_id=flow_id, action="confirm", value={"code": p["payload"]["match_code"]})
        elif p["prompt_type"] in ("yes_no", "ack"):
            r = respond_onboarding(flow_id=flow_id, action="confirm", value={"profile_id": "merchant"})
        else:
            r = respond_onboarding(flow_id=flow_id, action="continue")
    assert r["status"] == "complete"


async def _create_grant(db, owner_identity_id: str):
    terms = dict(
        grant_id="grant-gated",
        agent_id="agent-gated",
        agent_public_key=None,
        currency="USDC",
        token_address=_TOKEN,
        total_limit=100.0,
        per_tx_limit=10.0,
        purpose_scope=[],
        expires_at=None,
        nonce="nonce-gated",
    )
    message = spending_grant.build_grant_message(wallet_address=_WALLET, **terms)
    await spending_grant.create_grant(
        db,
        owner_identity_id=owner_identity_id,
        wallet_address=_WALLET,
        wallet_signature=_sign(message),
        **terms,
    )
    await db.commit()


@pytest.fixture(autouse=True)
def _fresh_store():
    reset_onboarding_flows()
    yield
    reset_onboarding_flows()


@pytest.mark.asyncio
async def test_spend_rejected_until_onboarding_complete(db_session, monkeypatch):
    monkeypatch.setattr(settings, "onboarding_authorization_enforced", True)
    await _create_grant(db_session, owner_identity_id="owner-gated")

    with pytest.raises(HTTPException) as exc:
        await spending_grant.assert_spend_allowed(
            db_session,
            agent_id="agent-gated",
            owner_identity_id="owner-gated",
            token_address=_TOKEN,
            amount=5.0,
        )
    assert exc.value.status_code == 403
    assert "onboarding" in str(exc.value.detail)

    _complete("owner-gated")

    allowed = await spending_grant.assert_spend_allowed(
        db_session,
        agent_id="agent-gated",
        owner_identity_id="owner-gated",
        token_address=_TOKEN,
        amount=5.0,
    )
    assert allowed.grant_id == "grant-gated"


@pytest.mark.asyncio
async def test_spend_gate_off_when_flag_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "onboarding_authorization_enforced", False)
    await _create_grant(db_session, owner_identity_id="owner-off")

    allowed = await spending_grant.assert_spend_allowed(
        db_session,
        agent_id="agent-gated",
        owner_identity_id="owner-off",
        token_address=_TOKEN,
        amount=5.0,
    )
    assert allowed.grant_id == "grant-gated"
