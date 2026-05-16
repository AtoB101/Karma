"""Unit tests for OpenClaw handoff draft builder and API."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from core.schemas import TaskStatus, VoucherStatus
from db.models.orm import AgentModel, SettlementModel, TaskContractModel, VoucherModel
from db.session import get_db
from services.openclaw_handoff_draft import build_handoff_draft


@pytest.mark.asyncio
async def test_build_handoff_draft_infers_accepted_voucher(db_session):
    buyer = "buyer-oc-1"
    seller = "seller-oc-1"
    task_id = "task-handoff-1"
    voucher_id = "voucher-handoff-1"

    db_session.add(
        AgentModel(agent_id=buyer, name="B", role="client", public_key="pk-buyer", capabilities=[])
    )
    db_session.add(
        AgentModel(agent_id=seller, name="S", role="worker", public_key="pk-seller", capabilities=[])
    )
    db_session.add(
        TaskContractModel(
            task_id=task_id,
            client_agent_id=buyer,
            worker_agent_id=seller,
            title="t",
            description="d",
            expected_output_schema={},
            expected_step_count=1,
            escrow_amount=10.0,
            deadline_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.add(
        VoucherModel(
            voucher_id=voucher_id,
            buyer_identity_id=buyer,
            seller_identity_id=seller,
            amount=10.0,
            bill_credit_amount=10.0,
            task_type="generic",
            task_description_hash="a" * 64,
            progress_rule_hash="b" * 64,
            evidence_requirement_hash="c" * 64,
            expiry_time=datetime.utcnow() + timedelta(days=1),
            nonce="nonce-handoff-1",
            buyer_signature="0x" + "ab" * 32,
            status=VoucherStatus.ACCEPTED.value,
        )
    )
    db_session.add(
        SettlementModel(
            settlement_id="settle-handoff-1",
            task_id=task_id,
            escrow_amount=10.0,
            status=TaskStatus.ACCEPTED.value,
            client_agent_id=buyer,
            worker_agent_id=seller,
            voucher_id=voucher_id,
        )
    )
    await db_session.flush()

    out = await build_handoff_draft(db_session, task_id=task_id, trace_id="trace-x")
    assert out["handoff"]["task_id"] == task_id
    assert out["handoff"]["voucher_id"] == voucher_id
    assert "buyer_create_voucher" in out["inferred_steps"]
    assert "seller_accept_voucher" in out["inferred_steps"]
    assert "settlement_created" in out["inferred_steps"]
    assert out["validation_ok"] is True


@pytest.mark.asyncio
async def test_handoff_draft_api_route(client, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "auth_api_keys", "buyer-oc:buyer-secret-12345678")
    buyer = "buyer-api-oc"
    seller = "seller-api-oc"
    task_id = "task-handoff-api"

    db_session.add(
        AgentModel(agent_id=buyer, name="B", role="client", public_key="pk-buyer", capabilities=[])
    )
    db_session.add(
        AgentModel(agent_id=seller, name="S", role="worker", public_key="pk-seller", capabilities=[])
    )
    db_session.add(
        TaskContractModel(
            task_id=task_id,
            client_agent_id=buyer,
            worker_agent_id=seller,
            title="t",
            description="d",
            expected_output_schema={},
            expected_step_count=1,
            escrow_amount=5.0,
            deadline_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.add(
        SettlementModel(
            settlement_id="settle-api-oc",
            task_id=task_id,
            escrow_amount=5.0,
            status=TaskStatus.PENDING.value,
            client_agent_id=buyer,
            worker_agent_id=None,
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/v1/openclaw/handoff-draft?task_id={task_id}",
        headers={"X-Karma-Api-Key": "karma_buyer-oc_buyer-secret-12345678"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["handoff"]["buyer_identity_id"] == buyer
    assert "settlement_created" in body["inferred_steps"]
