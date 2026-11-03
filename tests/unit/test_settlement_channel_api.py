"""Settlement-channel API endpoints (stateless crypto helpers)."""
from __future__ import annotations

import pytest
from eth_account import Account
from httpx import ASGITransport, AsyncClient

from api.app import app
from services import settlement_channel

KEY = "0x3333333333333333333333333333333333333333333333333333333333333333"
ADDR = Account.from_key(KEY).address


@pytest.mark.asyncio
async def test_sign_message_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/settlement-channel/sign-message",
            json={
                "channel_id": "ch-1",
                "seq": 3,
                "balances": {ADDR: "10.0"},
                "meta_hash": "0xabc",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["message"] == settlement_channel.canonical_state_message(
            channel_id="ch-1", seq=3, balances={ADDR: "10.0"}, meta_hash="0xabc"
        )


@pytest.mark.asyncio
async def test_verify_endpoint():
    state = {
        "channel_id": "ch-1",
        "seq": 3,
        "balances": {ADDR: "10.0"},
        "meta_hash": "0xabc",
    }
    sig = settlement_channel.sign_state(private_key=KEY, **state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/settlement-channel/verify",
            json={**state, "signature": sig, "signer_address": ADDR},
        )
        assert r.status_code == 200, r.text
        assert r.json()["valid"] is True


@pytest.mark.asyncio
async def test_batch_hash_endpoint():
    states = [
        {"channel_id": "ch-1", "seq": 1, "balances": {ADDR: "1.0"}, "meta_hash": "0x1"},
        {"channel_id": "ch-2", "seq": 2, "balances": {ADDR: "2.0"}, "meta_hash": "0x2"},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/v1/settlement-channel/batch-hash", json={"states": states})
        assert r.status_code == 200, r.text
        assert r.json()["batch_hash"] == settlement_channel.state_batch_hash(states)
