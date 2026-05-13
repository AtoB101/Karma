"""Contract creation — escrow bounds and optional capacity headroom."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_contract_rejected_below_min_escrow(client: AsyncClient):
    r = await client.post(
        "/v1/contracts",
        json={
            "client_agent_id": "c-min",
            "title": "t",
            "description": "d",
            "expected_output_schema": {},
            "expected_step_count": 1,
            "escrow_amount": 0.001,
            "deadline_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 400
    assert ">=" in r.json()["detail"] or "minimum" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_contract_rejected_above_max_escrow(client: AsyncClient):
    r = await client.post(
        "/v1/contracts",
        json={
            "client_agent_id": "c-max",
            "title": "t",
            "description": "d",
            "expected_output_schema": {},
            "expected_step_count": 1,
            "escrow_amount": 200_000.0,
            "deadline_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_contract_rejected_when_exceeds_available_credits(client: AsyncClient):
    buyer = "buyer-cap-contract-1"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 40.0})
    r = await client.post(
        "/v1/contracts",
        json={
            "client_agent_id": buyer,
            "title": "t",
            "description": "d",
            "expected_output_schema": {},
            "expected_step_count": 1,
            "escrow_amount": 500.0,
            "deadline_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 409
    assert "available_credits" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_contract_ok_when_no_capacity_row(client: AsyncClient):
    r = await client.post(
        "/v1/contracts",
        json={
            "client_agent_id": "buyer-no-ledger-row-xyz",
            "title": "t",
            "description": "d",
            "expected_output_schema": {},
            "expected_step_count": 1,
            "escrow_amount": 500.0,
            "deadline_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 201
