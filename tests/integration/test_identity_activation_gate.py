"""未激活的主身份：接不了单、进不了撮合。

规则（用户拍板）：连钱包只拿到身份号（Kid1…）是**未激活**；主身份本人完成
「证件 + 刷脸」认证后才算激活。未激活期间可以锁仓、可以划额度，但不能接单、
不会被撮合、信誉分不对外显示。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from db.models.orm import AgentModel, IdentityVerificationModel


def _voucher_json(*, buyer: str, seller: str, amount: float, nonce: str) -> dict:
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": amount,
        "currency": "USDC",
        "bill_credit_amount": amount,
        "task_type": "p0.acceptance",
        "task_description_hash": "a" * 64,
        "progress_rule_hash": "b" * 64,
        "evidence_requirement_hash": "c" * 64,
        "expiry_time": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
        "nonce": nonce,
        "buyer_signature": "sig-" + nonce,
    }


@pytest.mark.asyncio
async def test_unactivated_identity_cannot_accept_a_voucher(client: AsyncClient, activate_identity):
    buyer, seller = "actgate-buyer", "actgate-seller"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100.0})

    v = await client.post(
        "/v1/vouchers",
        json=_voucher_json(buyer=buyer, seller=seller, amount=30.0, nonce="actgate-1"),
    )
    assert v.status_code == 201, v.text
    vid = v.json()["voucher_id"]

    blocked = await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    assert blocked.status_code == 403, blocked.text
    assert "not activated" in blocked.json()["detail"]

    # 激活之后，同一张凭证就能接了。
    await activate_identity(seller)
    ok = await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_discovery_drops_sellers_of_unactivated_identities(
    client: AsyncClient, db_session, activate_identity
):
    owner = "actgate-owner"
    agent_id = "actgate-agent"
    db_session.add(
        AgentModel(
            agent_id=agent_id,
            name="Activation gate probe",
            role="worker",
            public_key="actgate-probe",
            endpoint_url=None,
            capabilities=["karma_settle", "data_processing"],
            is_active=True,
            registered_at=datetime.utcnow(),
            identity_class="business",
            owner_identity_id=owner,
            p1_ready=False,
            onboarding_meta={"source": "activation_gate_test"},
        )
    )
    await db_session.commit()

    payload = {
        "requirement_text": "帮我做一批数据标注，预算 20 USDC",
        "include_local_agents": True,
        "include_demo_merchants": False,
        "include_did_projections": False,
        "apply_trust_ranking": False,
        "limit": 50,
    }

    async def _discover() -> dict:
        r = await client.post("/v1/discovery/intent", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    # 只看这一个 agent 在不在：别的用例留下的 agent 也会被摘掉，全局计数不可比。
    blocked = await _discover()
    assert blocked["ranking"]["dropped_unactivated_sellers"] >= 1, blocked["ranking"]
    assert agent_id not in [c.get("agent_id") for c in blocked.get("candidates", [])]

    await activate_identity(owner)

    allowed = await _discover()
    assert agent_id in [c.get("agent_id") for c in allowed.get("candidates", [])]
