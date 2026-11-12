"""仲裁裁决必须落到链上（2026-09-20 测试网实测发现）。

问题：POST /v1/arbitration/cases/{case_id}/execute 只改数据库、从头到尾不碰链。
走 /dispute → /auto-arbitrate 那条路是有 _sync_escrow_settlement 这一步的，
仲裁庭改判这条路漏了 —— 结果 DB 说「已退款 / 已结算」，链上的 binding 还挂着 active，
钱一直锁在托管里，台账和链上对不上。

这个用例把「execute 会调用链上同步，并且目标状态就是裁决结果」钉住。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract

from config.settings import settings
from core.schemas import TaskStatus


async def _disputed_settlement(client: AsyncClient, activate_identity, *, task_id, buyer, seller, task_type, nonce):
    """合同 → 凭证 → 结算 → 指派 → 开工 → 交付 → 争议。"""
    await client.post("/v1/capacity/" + buyer + "/lock", json={"amount": 100.0})
    await post_minimal_contract(
        client, task_id=task_id, client_agent_id=buyer, escrow_amount=100.0, expected_step_count=5
    )
    v = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 100.0,
            "currency": "USDC",
            "bill_credit_amount": 100.0,
            "task_type": task_type,
            "task_description_hash": "a" * 64,
            "progress_rule_hash": "b" * 64,
            "evidence_requirement_hash": "c" * 64,
            "expiry_time": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
            "nonce": nonce,
            "buyer_signature": "sig-" + nonce,
        },
    )
    assert v.status_code == 201, v.text
    await activate_identity(seller)
    acc = await client.post(
        "/v1/vouchers/" + v.json()["voucher_id"] + "/accept", json={"seller_identity_id": seller}
    )
    assert acc.status_code == 200, acc.text
    created = await client.post(
        "/v1/settlement/create",
        json={
            "task_id": task_id,
            "client_agent_id": buyer,
            "escrow_amount": 100.0,
            "currency": "USD",
            "voucher_id": v.json()["voucher_id"],
        },
    )
    assert created.status_code == 201, created.text
    await client.post("/v1/settlement/" + task_id + "/lock", json={"worker_agent_id": seller})
    await client.post("/v1/settlement/" + task_id + "/start", json={})
    delivered = await client.post("/v1/settlement/" + task_id + "/submit", json={})
    assert delivered.status_code == 200, delivered.text
    disputed = await client.post("/v1/settlement/" + task_id + "/dispute", json={"reason": "mismatch"})
    assert disputed.status_code == 200, disputed.text


def _ops(monkeypatch, tag: str):
    operator = "arb-op-" + tag
    key = operator + "-secret-abcdef12"
    monkeypatch.setattr(settings, "auth_api_keys", operator + ":" + key)
    monkeypatch.setattr(settings, "admin_actor_ids", operator)
    monkeypatch.setattr(settings, "arbitrator_actor_ids", operator)
    monkeypatch.setattr(settings, "arbitration_pool_open_join", True)
    return {"X-Karma-Api-Key": "karma_" + operator + "_" + key}


@pytest.mark.asyncio
async def test_arbitration_execute_syncs_buyer_wins_to_chain(
    client: AsyncClient, activate_identity, monkeypatch
):
    ops_headers = _ops(monkeypatch, "c1")

    def as_identity(identity_id: str) -> dict:
        return {"X-Karma-Identity-Id": identity_id}

    task_id = "task-f7-arb-chain"
    buyer = "buyer-f7-arb-chain"
    seller = "seller-f7-arb-chain"
    await _disputed_settlement(
        client, activate_identity, task_id=task_id, buyer=buyer, seller=seller,
        task_type="agent.f7_arb", nonce="nonce-f7-arb-chain",
    )

    arbitrators = ["arb-chain-1", "arb-chain-2", "arb-chain-3"]
    for arbitrator in arbitrators:
        await client.post("/v1/capacity/" + arbitrator + "/lock", json={"amount": 500.0})
        joined = await client.post(
            "/v1/arbitration/pool/join",
            json={"arbitrator_identity_id": arbitrator, "stake_amount": 150.0},
            headers=as_identity(arbitrator),
        )
        assert joined.status_code == 200, joined.text

    created = await client.post(
        "/v1/arbitration/cases",
        json={"task_id": task_id, "opened_by": buyer, "required_arbitrators": 3},
        headers=as_identity(buyer),
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["case_id"]

    assigned = await client.post(
        "/v1/arbitration/cases/" + case_id + "/assign-auto",
        json={"count": 3},
        headers=ops_headers,
    )
    assert assigned.status_code == 200, assigned.text
    assert len(assigned.json()) == 3

    for arbitrator in arbitrators:
        vote = await client.post(
            "/v1/arbitration/cases/" + case_id + "/vote",
            json={"arbitrator_identity_id": arbitrator, "decision": "buyer_wins"},
            headers=as_identity(arbitrator),
        )
        assert vote.status_code == 200, vote.text

    decided = await client.get("/v1/arbitration/cases/" + case_id, headers=as_identity(buyer))
    assert decided.json()["status"] == "decided"
    assert decided.json()["decided_outcome"] == "buyer_wins"

    # 关键断言：execute 必须把裁决结果交给链上同步。
    seen: list = []

    async def _recorder(*, db, state, target_status):
        seen.append(target_status)

    import api.routes.settlement as settlement_routes

    monkeypatch.setattr(settlement_routes, "_sync_escrow_settlement", _recorder)

    executed = await client.post(
        "/v1/arbitration/cases/" + case_id + "/execute", json={}, headers=ops_headers
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == TaskStatus.REFUNDED.value
    assert seen == [TaskStatus.REFUNDED], seen


@pytest.mark.asyncio
async def test_arbitration_execute_syncs_seller_wins_to_chain(
    client: AsyncClient, activate_identity, monkeypatch
):
    ops_headers = _ops(monkeypatch, "c2")

    def as_identity(identity_id: str) -> dict:
        return {"X-Karma-Identity-Id": identity_id}

    task_id = "task-f7-arb-seller"
    buyer = "buyer-f7-arb-seller"
    seller = "seller-f7-arb-seller"
    await _disputed_settlement(
        client, activate_identity, task_id=task_id, buyer=buyer, seller=seller,
        task_type="agent.f7_arb2", nonce="nonce-f7-arb-seller",
    )

    arbitrators = ["arb-s-1", "arb-s-2", "arb-s-3"]
    for arbitrator in arbitrators:
        await client.post("/v1/capacity/" + arbitrator + "/lock", json={"amount": 500.0})
        joined = await client.post(
            "/v1/arbitration/pool/join",
            json={"arbitrator_identity_id": arbitrator, "stake_amount": 150.0},
            headers=as_identity(arbitrator),
        )
        assert joined.status_code == 200, joined.text

    created = await client.post(
        "/v1/arbitration/cases",
        json={"task_id": task_id, "opened_by": buyer, "required_arbitrators": 3},
        headers=as_identity(buyer),
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["case_id"]
    assigned = await client.post(
        "/v1/arbitration/cases/" + case_id + "/assign-auto",
        json={"count": 3},
        headers=ops_headers,
    )
    assert assigned.status_code == 200, assigned.text
    for arbitrator in arbitrators:
        vote = await client.post(
            "/v1/arbitration/cases/" + case_id + "/vote",
            json={"arbitrator_identity_id": arbitrator, "decision": "seller_wins"},
            headers=as_identity(arbitrator),
        )
        assert vote.status_code == 200, vote.text

    seen: list = []

    async def _recorder(*, db, state, target_status):
        seen.append(target_status)

    import api.routes.settlement as settlement_routes

    monkeypatch.setattr(settlement_routes, "_sync_escrow_settlement", _recorder)

    executed = await client.post(
        "/v1/arbitration/cases/" + case_id + "/execute", json={}, headers=ops_headers
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == TaskStatus.SETTLED.value
    assert seen == [TaskStatus.SETTLED], seen
