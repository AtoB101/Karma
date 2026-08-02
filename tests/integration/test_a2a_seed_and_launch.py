"""Agent↔agent land: seed_phase1_dual_agents → trade launch execution_started."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from config.settings import settings
from scripts.seed_phase1_dual_agents import seed_dual_agents


@pytest.mark.asyncio
async def test_seed_dual_agents_then_launch(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ledger_require_party_actor", False)
    monkeypatch.setattr(settings, "trade_launch_require_eip712", False)

    buyer, seller = "a2a-test-buyer", "a2a-test-seller"
    env = await seed_dual_agents(
        buyer_id=buyer, seller_id=seller, capacity=200.0, db=db_session
    )
    assert env["KARMA_BUYER_API_KEY"].startswith(f"karma_{buyer}_")
    assert env["KARMA_SELLER_API_KEY"].startswith(f"karma_{seller}_")

    resp = await client.post(
        "/v1/trade/orders/launch",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "requirement_text": "caption A2A land 12 USDC precision 1.0",
            "buyer_signature": "0xa2a_land",
            "task_type": "api.caption",
        },
        headers={
            "Idempotency-Key": "a2a-land-integration-1",
            "X-Karma-Api-Key": env["KARMA_BUYER_API_KEY"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "execution_started"
    assert body.get("order_id")
    assert body.get("task_id")
    assert body["readiness"]["buyer"] is True
    assert body["readiness"]["seller"] is True

    replay = await client.post(
        "/v1/trade/orders/launch",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "requirement_text": "caption A2A land 12 USDC precision 1.0",
            "buyer_signature": "0xa2a_land",
            "task_type": "api.caption",
        },
        headers={
            "Idempotency-Key": "a2a-land-integration-1",
            "X-Karma-Api-Key": env["KARMA_BUYER_API_KEY"],
        },
    )
    assert replay.status_code == 201, replay.text
    assert replay.json().get("idempotent_replay") is True
    assert replay.json().get("order_id") == body["order_id"]
