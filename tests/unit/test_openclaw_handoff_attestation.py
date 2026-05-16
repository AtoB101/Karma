"""Handoff attestation service."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from config.settings import settings
from core.schemas import TaskStatus, VoucherStatus
from db.models.orm import AgentModel, ResponsibilityEdgeModel, SettlementModel, TaskContractModel, VoucherModel
from services.agent_automation_policy import upsert_automation_policy
from services.openclaw_handoff_attestation import confirm_handoff_attestation, has_handoff_attestation
from services.runtime_key_service import create_runtime_key_record


async def _seed(db_session, task_id: str, buyer: str, seller: str) -> None:
    voucher_id = f"v-{task_id}"
    db_session.add(AgentModel(agent_id=buyer, name="B", role="client", public_key="pk-b", capabilities=[]))
    db_session.add(AgentModel(agent_id=seller, name="S", role="worker", public_key="pk-s", capabilities=[]))
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
            deadline_at=datetime.utcnow() + timedelta(hours=2),
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
            nonce=f"n-{task_id}",
            buyer_signature="0x" + "ab" * 32,
            status=VoucherStatus.ACCEPTED.value,
        )
    )
    db_session.add(
        SettlementModel(
            settlement_id=f"s-{task_id}",
            task_id=task_id,
            escrow_amount=10.0,
            status=TaskStatus.ACCEPTED.value,
            client_agent_id=buyer,
            worker_agent_id=seller,
            voucher_id=voucher_id,
        )
    )
    db_session.add(
        ResponsibilityEdgeModel(
            edge_hash=("f" * 60) + task_id[-4:],
            source_identity_id=buyer,
            target_identity_id=seller,
            edge_type="VOUCHER_ACCEPT",
            task_id=task_id,
            voucher_id=voucher_id,
        )
    )
    await upsert_automation_policy(
        db_session,
        karma_identity_id=seller,
        auto_enabled=True,
        single_limit=100.0,
        daily_limit=500.0,
        permissions=["verify_voucher"],
        high_risk_mode="always",
        responsibility_acknowledged=True,
    )
    await create_runtime_key_record(
        db=db_session,
        wallet_address="0x" + "11" * 20,
        karma_identity_id=seller,
        permissions=["verify_voucher"],
        single_limit=50.0,
        daily_limit=200.0,
        expire_at=datetime.utcnow() + timedelta(days=7),
        agent_name="t",
        agent_binding=None,
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_confirm_attestation_after_ready(db_session):
    await _seed(db_session, "task-att-1", "buyer-a", "seller-a")
    out = await confirm_handoff_attestation(
        db_session,
        task_id="task-att-1",
        karma_identity_id="seller-a",
        role="seller",
    )
    assert out["attested"] is True
    assert await has_handoff_attestation(db_session, task_id="task-att-1", karma_identity_id="seller-a")


@pytest.mark.asyncio
async def test_confirm_rejected_when_not_ready(db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_require_handoff_attestation", False)
    await _seed(db_session, "task-att-bad", "buyer-b", "seller-b")
    row = await db_session.get(
        __import__("db.models.orm", fromlist=["VoucherModel"]).VoucherModel,
        f"v-task-att-bad",
    )
    if row:
        row.status = VoucherStatus.CREATED.value
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await confirm_handoff_attestation(
            db_session,
            task_id="task-att-bad",
            karma_identity_id="seller-b",
            role="seller",
        )
    assert exc.value.status_code == 403
