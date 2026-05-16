"""End-to-end authorization chain: policy → readiness → attestation → runtime gate."""

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
from tests.unit.test_runtime_automation_readiness_gate import _mint_runtime, _seed_ready_task


@pytest.mark.asyncio
async def test_full_chain_confirm_then_runtime_allowed(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_api_keys", "op:op-secret-123456789012")
    monkeypatch.setattr(settings, "runtime_require_handoff_attestation", True)
    monkeypatch.setattr(settings, "runtime_require_task_automation_readiness", True)

    buyer = "buyer-chain"
    seller = "seller-chain"
    task_id = "task-chain-1"
    headers = {"X-Karma-Api-Key": "karma_op_op-secret-123456789012"}

    await _seed_ready_task(db_session, task_id=task_id, buyer=buyer, seller=seller)
    rt = await _mint_runtime(client, seller=seller, perms=["verify_voucher"])

    ready = await client.get(
        f"/v1/openclaw/automation-readiness?task_id={task_id}&role=seller&karma_identity_id={seller}&for_handoff_confirm=true",
        headers=headers,
    )
    assert ready.status_code == 200
    body = ready.json()
    assert body["ready_for_handoff_confirm"] is True, body.get("blockers")

    confirm = await client.post(
        "/v1/openclaw/handoff-confirm",
        headers=headers,
        json={"task_id": task_id, "karma_identity_id": seller, "role": "seller"},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["attested"] is True

    vr = await client.post(
        "/runtime/check-voucher",
        headers={"X-Karma-Runtime-Key": rt},
        json={
            "voucher_id": f"v-{task_id}",
            "client_nonce": "nonce-chain-12345678",
        },
    )
    assert vr.status_code == 200, vr.text


@pytest.mark.asyncio
async def test_runtime_blocked_without_attestation(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "runtime_require_handoff_attestation", True)
    monkeypatch.setattr(settings, "runtime_require_task_automation_readiness", True)

    buyer = "buyer-no-att"
    seller = "seller-no-att"
    task_id = "task-no-att"
    await _seed_ready_task(db_session, task_id=task_id, buyer=buyer, seller=seller)
    rt = await _mint_runtime(client, seller=seller, perms=["verify_voucher"])

    resp = await client.post(
        "/runtime/check-voucher",
        headers={"X-Karma-Runtime-Key": rt},
        json={"voucher_id": f"v-{task_id}", "client_nonce": "nonce-no-att-123456"},
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail.get("error") in ("handoff_not_attested", "automation_not_ready")
