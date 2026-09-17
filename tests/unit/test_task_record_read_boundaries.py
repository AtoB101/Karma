"""交易明细的读权限边界 + 流转审计补漏（P1-7 / P1-8）。

2026-09-17 复核实测：
* k2 读 k1 的合同 ``GET /v1/contracts/{task_id}`` → 200（对手方、金额、完整需求描述）；
* k2 读 k1 的结算流转 ``GET /v1/settlement/{task_id}/transitions`` → 200；
* ``PATCH /v1/contracts/{task_id}/assign`` 当时**连归属校验都没有**，谁都能改卖方；
* 进度回执改变结算状态（progress_submitted / progress_confirmed）时**不写流转审计**，
  于是「资金状态被改过但没有痕迹」。

这里把四条边界都钉住。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract

from config.settings import settings


async def _seed(client: AsyncClient, activate_identity, *, task_id: str, buyer: str, seller: str) -> str:
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100})
    await post_minimal_contract(
        client, task_id=task_id, client_agent_id=buyer, escrow_amount=100.0, expected_step_count=5
    )
    voucher = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 100,
            "currency": "USDC",
            "bill_credit_amount": 100,
            "task_type": "p1.read.boundary",
            "task_description_hash": "a" * 64,
            "progress_rule_hash": "b" * 64,
            "evidence_requirement_hash": "c" * 64,
            "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "nonce": f"nonce-{task_id}",
            "buyer_signature": f"sig-{task_id}",
        },
    )
    vid = voucher.json()["voucher_id"]
    await activate_identity(seller)
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    created = await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": 100.0, "currency": "USD"},
    )
    assert created.status_code in (200, 201), created.text
    locked = await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    assert locked.status_code == 200, locked.text
    started = await client.post(f"/v1/settlement/{task_id}/start", json={})
    assert started.status_code == 200, started.text
    return vid


# ---------------------------------------------------------------------------
# P1-7：合同 / 流转的读权限
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_third_party_cannot_read_a_contract(client: AsyncClient, activate_identity):
    task_id = "task-read-contract"
    buyer, seller = "buyer-read-contract", "seller-read-contract"
    await _seed(client, activate_identity, task_id=task_id, buyer=buyer, seller=seller)

    # 当事人（买方 / 被指派卖方）读得到。
    for who in (buyer, seller):
        ok = await client.get(f"/v1/contracts/{task_id}", headers={"X-Karma-Identity-Id": who})
        assert ok.status_code == 200, (who, ok.text)

    # 第三方读不到（这就是复核里 k2 读到 k1 合同的那个洞）。
    stranger = await client.get(
        f"/v1/contracts/{task_id}", headers={"X-Karma-Identity-Id": "k2-unrelated"}
    )
    assert stranger.status_code == 403, stranger.text


@pytest.mark.asyncio
async def test_unidentified_caller_is_left_to_the_auth_layer(client: AsyncClient, activate_identity):
    """本地/公开读不该被这条闸门顺手打成 401 —— 生产由鉴权中间件负责。"""
    task_id = "task-read-contract-anon"
    await _seed(
        client, activate_identity, task_id=task_id,
        buyer="buyer-read-anon", seller="seller-read-anon",
    )
    resp = await client.get(f"/v1/contracts/{task_id}")
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_platform_operations_can_read_any_contract(client: AsyncClient, activate_identity, monkeypatch):
    monkeypatch.setattr(settings, "admin_actor_ids", "ops-admin")
    task_id = "task-read-contract-admin"
    await _seed(
        client, activate_identity, task_id=task_id,
        buyer="buyer-read-admin", seller="seller-read-admin",
    )
    resp = await client.get(f"/v1/contracts/{task_id}", headers={"X-Karma-Identity-Id": "ops-admin"})
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_public_read_switch_restores_open_access(client: AsyncClient, activate_identity, monkeypatch):
    """产品决策开关：TASK_RECORDS_PUBLIC_READ=true 时恢复「人人可审计」。"""
    task_id = "task-read-contract-public"
    await _seed(
        client, activate_identity, task_id=task_id,
        buyer="buyer-read-public", seller="seller-read-public",
    )
    monkeypatch.setattr(settings, "task_records_public_read", True)
    resp = await client.get(f"/v1/contracts/{task_id}", headers={"X-Karma-Identity-Id": "anyone"})
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_third_party_cannot_read_settlement_transitions(client: AsyncClient, activate_identity):
    task_id = "task-read-transitions"
    buyer, seller = "buyer-read-tr", "seller-read-tr"
    await _seed(client, activate_identity, task_id=task_id, buyer=buyer, seller=seller)

    ok = await client.get(
        f"/v1/settlement/{task_id}/transitions", headers={"X-Karma-Identity-Id": buyer}
    )
    assert ok.status_code == 200, ok.text

    stranger = await client.get(
        f"/v1/settlement/{task_id}/transitions", headers={"X-Karma-Identity-Id": "k2-unrelated"}
    )
    assert stranger.status_code == 403, stranger.text


@pytest.mark.asyncio
async def test_third_party_cannot_read_settlement_state(client: AsyncClient, activate_identity):
    task_id = "task-read-settlement"
    buyer, seller = "buyer-read-st", "seller-read-st"
    await _seed(client, activate_identity, task_id=task_id, buyer=buyer, seller=seller)

    ok = await client.get(f"/v1/settlement/{task_id}", headers={"X-Karma-Identity-Id": seller})
    assert ok.status_code == 200, ok.text

    stranger = await client.get(
        f"/v1/settlement/{task_id}", headers={"X-Karma-Identity-Id": "k2-unrelated"}
    )
    assert stranger.status_code == 403, stranger.text


# ---------------------------------------------------------------------------
# P1-7：/assign 的归属校验
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_the_buyer_may_assign_the_worker(client: AsyncClient, activate_identity):
    task_id = "task-assign-guard"
    buyer = "buyer-assign-guard"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100})
    await post_minimal_contract(
        client, task_id=task_id, client_agent_id=buyer, escrow_amount=100.0, expected_step_count=3
    )

    # 陌生人不能替别人指派卖方。
    hijack = await client.patch(
        f"/v1/contracts/{task_id}/assign?worker_agent_id=seller-hijacked",
        headers={"X-Karma-Identity-Id": "k2-unrelated"},
    )
    assert hijack.status_code == 403, hijack.text

    # 买方可以指派。
    ok = await client.patch(
        f"/v1/contracts/{task_id}/assign?worker_agent_id=seller-real",
        headers={"X-Karma-Identity-Id": buyer},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["worker_agent_id"] == "seller-real"

    # 一旦指派，就不能被悄悄换人。
    overwrite = await client.patch(
        f"/v1/contracts/{task_id}/assign?worker_agent_id=seller-other",
        headers={"X-Karma-Identity-Id": buyer},
    )
    assert overwrite.status_code == 409, overwrite.text


# ---------------------------------------------------------------------------
# P1-8：进度回执改状态必须留痕
# ---------------------------------------------------------------------------

async def _submit_progress(client: AsyncClient, *, task_id: str, seller: str) -> str:
    resp = await client.post(
        "/v1/progress",
        json={
            "task_id": task_id,
            "seller_identity_id": seller,
            "progress_percent": 25,
            "claimed_value_percent": 25,
            "evidence_hash": "d" * 64,
            "runtime_log_hash": "e" * 64,
            "seller_signature": "sig-progress-audit",
            "validation_method": "buyer_confirm",
        },
        headers={"X-Karma-Identity-Id": seller},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["progress_receipt_id"]


@pytest.mark.asyncio
async def test_progress_state_changes_are_audited(client: AsyncClient, activate_identity):
    task_id = "task-progress-audit"
    buyer, seller = "buyer-progress-audit", "seller-progress-audit"
    await _seed(client, activate_identity, task_id=task_id, buyer=buyer, seller=seller)

    pid = await _submit_progress(client, task_id=task_id, seller=seller)
    confirmed = await client.post(
        f"/v1/progress/{pid}/confirm",
        json={},
        headers={"X-Karma-Identity-Id": buyer},
    )
    assert confirmed.status_code == 200, confirmed.text

    resp = await client.get(
        f"/v1/settlement/{task_id}/transitions", headers={"X-Karma-Identity-Id": buyer}
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    by_stage = {row["guard_stage"]: row for row in rows if row.get("guard_stage")}

    submit_row = by_stage.get("progress_submit")
    assert submit_row is not None, rows
    assert submit_row["to_status"] == "progress_submitted"
    assert submit_row["actor_id"] == seller

    confirm_row = by_stage.get("progress_confirm")
    assert confirm_row is not None, rows
    assert confirm_row["to_status"] == "progress_confirmed"
    assert confirm_row["actor_id"] == buyer
