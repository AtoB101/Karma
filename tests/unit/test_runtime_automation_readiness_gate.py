"""Runtime Gateway blocks task mutators when automation readiness is required."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from config.settings import settings
from core.schemas import TaskStatus, VoucherStatus
from db.models.orm import (
    AgentModel,
    ResponsibilityEdgeModel,
    SettlementModel,
    TaskContractModel,
    VoucherModel,
)
from services.agent_automation_policy import upsert_automation_policy
from services.runtime_wallet import build_create_key_message


async def _seed_ready_task(db_session, *, task_id: str, buyer: str, seller: str) -> str:
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
    edge_hash = ("e" * 60) + task_id[-4:].ljust(4, "0")
    db_session.add(
        ResponsibilityEdgeModel(
            edge_hash=edge_hash[:64],
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
        permissions=["submit_receipt", "verify_voucher", "sync_task_status"],
        high_risk_mode="always",
        responsibility_acknowledged=True,
    )
    await db_session.flush()
    return voucher_id


async def _mint_runtime(client: AsyncClient, *, seller: str, perms: list[str]) -> str:
    acct = Account.create()
    expire = datetime.utcnow() + timedelta(days=7)
    msg = build_create_key_message(
        karma_identity_id=seller,
        wallet_address=acct.address,
        permissions=sorted(perms),
        single_limit=10.0,
        daily_limit=100.0,
        expire_time=expire,
        agent_name="a",
        agent_binding=None,
    )
    signed = acct.sign_message(encode_defunct(text=msg))
    key_resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": seller,
            "wallet_signature": signed.signature.hex(),
            "permissions": sorted(perms),
            "single_limit": 10.0,
            "daily_limit": 100.0,
            "expire_time": expire.isoformat(),
            "agent_name": "a",
        },
    )
    assert key_resp.status_code == 201, key_resp.text
    return key_resp.json()["runtime_key"]


@pytest.mark.asyncio
async def test_submit_receipt_blocked_without_automation_policy(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_require_task_automation_readiness", True)
    buyer = "buyer-gate"
    seller = "seller-gate"
    task_id = "task-gate-blocked"
    await _seed_ready_task(db_session, task_id=task_id, buyer=buyer, seller=seller)
    # Remove policy so readiness fails
    from db.models.orm import AgentAutomationPolicyModel

    row = await db_session.get(AgentAutomationPolicyModel, seller)
    if row:
        await db_session.delete(row)
        await db_session.flush()

    rt = await _mint_runtime(client, seller=seller, perms=["submit_receipt"])

    now = datetime.utcnow()
    rec = {
        "task_id": task_id,
        "receipt_id": "r-gate-1",
        "agent_id": seller,
        "step_index": 1,
        "tool_name": "t",
        "input_hash": "a" * 64,
        "output_hash": "b" * 64,
        "started_at": now.isoformat(),
        "ended_at": (now + timedelta(seconds=1)).isoformat(),
        "duration_ms": 1000,
        "status": "success",
    }
    resp = await client.post(
        "/runtime/submit-receipt",
        headers={"X-Karma-Runtime-Key": rt},
        json=rec,
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail.get("error") == "automation_not_ready"
    assert detail.get("task_id") == task_id


@pytest.mark.asyncio
async def test_check_voucher_allowed_when_fully_ready(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_require_task_automation_readiness", True)
    buyer = "buyer-gate-ok"
    seller = "seller-gate-ok"
    task_id = "task-gate-ok"
    voucher_id = await _seed_ready_task(db_session, task_id=task_id, buyer=buyer, seller=seller)
    rt = await _mint_runtime(client, seller=seller, perms=["verify_voucher"])

    resp = await client.post(
        "/runtime/check-voucher",
        headers={"X-Karma-Runtime-Key": rt},
        json={"voucher_id": voucher_id, "client_nonce": "nonce-check-12345678"},
    )
    assert resp.status_code == 200, resp.text
