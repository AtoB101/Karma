"""Bilateral on-chain dispute resolve: role-gated exit + ruling view."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock, patch

from api.app import app
from config.settings import settings
from db.models.orm import AgentModel, TaskContractModel
from db.session import get_db

OP = "op-admin"
OP_SECRET = "op-secret-1"
OP_API_KEY = f"karma_{OP}_{OP_SECRET}"
OUTSIDER = "outsider"
OUTSIDER_SECRET = "outsider-secret"
OUTSIDER_API_KEY = f"karma_{OUTSIDER}_{OUTSIDER_SECRET}"

TERMS_HASH = "ab" * 32


def _tx() -> MagicMock:
    tx = MagicMock()
    tx.tx_hash = "0x" + "cd" * 32
    tx.status = "confirmed"
    return tx


@pytest.fixture
def roles(monkeypatch):
    monkeypatch.setattr(settings, "admin_actor_ids", OP)
    monkeypatch.setattr(settings, "arbitrator_actor_ids", "")
    monkeypatch.setattr(
        settings,
        "auth_api_keys",
        f"{OP}:{OP_SECRET},{OUTSIDER}:{OUTSIDER_SECRET}",
    )


@pytest.fixture
def chain_mock():
    mock = MagicMock()
    mock.resolve_dispute.return_value = _tx()
    mock.auto_resolve_dispute.return_value = _tx()
    mock.binding_status.return_value = {
        "binding_id": 1,
        "state": 2,
        "scope_hash": "0x" + TERMS_HASH,
        "buyer_bill": {"bill_id": 10, "owner": "0x" + "bb" * 20, "amount": 5_000_000, "state": 2},
        "agent_bill": {"bill_id": 11, "owner": "0x" + "cc" * 20, "amount": 1_000_000, "state": 2},
        "usdc_locked": 6_000_000,
        "can_dispute": True,
        "can_finalize": False,
    }
    mock.arbitration_status.return_value = {
        "binding_id": 1,
        "buyer_evidence_hash": "0x" + "01" * 32,
        "agent_evidence_hash": "0x" + "00" * 32,
        "buyer_submitted_at": 1_700_000_000,
        "agent_submitted_at": 0,
        "started_at": 1_700_000_000,
        "resolved": False,
    }
    with patch("api.routes.bilateral._chain", return_value=mock):
        yield mock


async def _seed_contract(db) -> None:
    db.add(AgentModel(agent_id="buyer-1", name="buyer", role="buyer", public_key=""))
    db.add(AgentModel(agent_id="worker-1", name="worker", role="worker", public_key=""))
    await db.flush()
    db.add(
        TaskContractModel(
            task_id="task-dispute-1",
            client_agent_id="buyer-1",
            worker_agent_id="worker-1",
            title="order",
            description="order desc",
            expected_output_schema={},
            expected_step_count=3,
            escrow_amount=5.0,
            currency="USDC",
            deadline_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            terms_hash=TERMS_HASH,
            contract_status="signed",
            version=1,
            onchain_binding_id=1,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_resolve_is_role_gated(db_session, roles, chain_mock):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            bogus = await client.post(
                "/v1/bilateral/resolve",
                json={"binding_id": 1, "buyer_share_bps": 5000},
                headers={"x-karma-api-key": "karma_nobody_not-a-real-key"},
            )
            assert bogus.status_code == 401, bogus.text

            outsider = await client.post(
                "/v1/bilateral/resolve",
                json={"binding_id": 1, "buyer_share_bps": 5000},
                headers={"x-karma-api-key": OUTSIDER_API_KEY},
            )
            assert outsider.status_code == 403, outsider.text
            chain_mock.resolve_dispute.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_resolve_relays_to_chain_for_operator(db_session, roles, chain_mock):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/bilateral/resolve",
                json={"binding_id": 1, "buyer_share_bps": 5000},
                headers={"x-karma-api-key": OP_API_KEY},
            )
            assert r.status_code == 200, r.text
            assert r.json()["buyer_share_bps"] == 5000
            chain_mock.resolve_dispute.assert_called_once_with(1, 5000)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dispute_ruling_view_returns_contract_anchor(db_session, roles, chain_mock):
    await _seed_contract(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(
                "/v1/bilateral/dispute/1",
                headers={"x-karma-api-key": OP_API_KEY},
            )
            assert r.status_code == 200, r.text
            payload = r.json()
            assert payload["binding"]["state"] == 2
            assert payload["arbitration"]["resolved"] is False
            assert payload["contract"]["task_id"] == "task-dispute-1"
            assert payload["contract"]["anchored"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dispute_ruling_view_is_role_gated(db_session, roles, chain_mock):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(
                "/v1/bilateral/dispute/1",
                headers={"x-karma-api-key": OUTSIDER_API_KEY},
            )
            assert r.status_code == 403, r.text
    finally:
        app.dependency_overrides.clear()
