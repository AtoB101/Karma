"""
Profile-bound M2M 端到端验收：Runtime Key 绑定身份档案后，profile_id 贯穿
voucher → settlement → receipt。

offchain 模式（monkeypatch settlement_mode）避免触发链上 Celery/Redis，
专注验证「agent 绑了身份卡 → 交易的每一层都带 profile_id」。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from config.settings import settings
from core.schemas import ExecutionReceipt, ToolStatus
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from httptest import post_minimal_contract
from services.runtime_wallet import build_create_key_message
from services.signing import signing_service


def _voucher_payload(buyer: str, seller: str, amount: float, nonce: str) -> dict:
    h = "aa" * 32
    exp = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": amount,
        "bill_credit_amount": amount,
        "task_type": "e2e.profile.m2m",
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": exp,
        "nonce": nonce,
        "buyer_signature": "0x" + "11" * 65,
        "currency": "USDC",
    }


async def _create_profile(client: AsyncClient, owner: str, class_: str) -> dict:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": owner, "class": class_, "display_name": "p-" + class_},
        headers={"X-Karma-Identity-Id": owner},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _mint_key_with_profile(
    client: AsyncClient,
    *,
    account: Account,
    karma_identity_id: str,
    profile_id: str,
    permissions: list[str],
) -> str:
    expire = datetime.utcnow() + timedelta(days=30)
    msg = build_create_key_message(
        karma_identity_id=karma_identity_id,
        wallet_address=account.address,
        permissions=permissions,
        single_limit=500.0,
        daily_limit=5000.0,
        expire_time=expire,
        agent_name=f"e2e-{karma_identity_id[:8]}",
        agent_binding=None,
    )
    signed = account.sign_message(encode_defunct(text=msg))
    r = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": account.address,
            "karma_identity_id": karma_identity_id,
            "wallet_signature": signed.signature.hex(),
            "permissions": permissions,
            "single_limit": 500.0,
            "daily_limit": 5000.0,
            "expire_time": expire.isoformat(),
            "agent_name": f"e2e-{karma_identity_id[:8]}",
            "profile_id": profile_id,
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["runtime_key"])


@pytest.mark.asyncio
async def test_profile_id_flows_through_m2m_flow(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "settlement_mode", "offchain")

    buyer = f"pf-buy-{uuid.uuid4().hex[:8]}"
    seller = f"pf-sell-{uuid.uuid4().hex[:8]}"
    buyer_acct = Account.create()
    seller_acct = Account.create()

    # 1. 身份档案（enterprise，默认 private）
    profile = await _create_profile(client, owner=buyer, class_="enterprise")
    pid = profile["profile_id"]

    # 2. agent key 绑定档案
    buyer_rt = await _mint_key_with_profile(
        client, account=buyer_acct, karma_identity_id=buyer, profile_id=pid,
        permissions=["request_voucher", "request_settlement", "sync_task_status"],
    )
    seller_rt = await _mint_key_with_profile(
        client, account=seller_acct, karma_identity_id=seller, profile_id=pid,
        permissions=["submit_receipt", "request_settlement", "sync_task_status"],
    )

    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 120.0})

    task_id = f"task-pf-{uuid.uuid4().hex[:12]}"
    await post_minimal_contract(client, task_id=task_id, client_agent_id=buyer, escrow_amount=35.0)

    # 3. 买方 agent 用绑了档案的 key 请求 voucher → voucher 应带 profile_id
    vr = await client.post(
        "/runtime/request-voucher",
        headers={"X-Karma-Runtime-Key": buyer_rt},
        json={"client_nonce": f"vc-{uuid.uuid4().hex}", "voucher": _voucher_payload(buyer, seller, 35.0, f"vn-{uuid.uuid4().hex}")},
    )
    assert vr.status_code == 201, vr.text
    voucher_id = vr.json()["voucher_id"]

    vr_get = await client.get(f"/v1/vouchers/{voucher_id}")
    assert vr_get.status_code == 200
    assert vr_get.json().get("profile_id") == pid, "voucher should inherit the runtime key profile_id"

    # 4. 接受 + 建 settlement（带 voucher_id）→ settlement 应继承 profile_id
    assert (await client.post(f"/v1/vouchers/{voucher_id}/accept", json={"seller_identity_id": seller})).status_code == 200
    cr = await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": 35.0, "currency": "USD", "voucher_id": voucher_id},
    )
    assert cr.status_code == 201, cr.text
    assert cr.json().get("profile_id") == pid, "settlement should inherit voucher profile_id"

    # 5. 卖方 agent 提交回执 → receipt 应带 profile_id
    await client.post(f"/v1/settlement/{task_id}/pending", json={})
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    # 卖方 agent 提交交付 → delivered
    sdr = await client.post(
        "/runtime/request-settlement",
        headers={"X-Karma-Runtime-Key": seller_rt},
        json={"task_id": task_id, "kind": "submit_delivery", "client_nonce": f"sd-{uuid.uuid4().hex}"},
    )
    assert sdr.status_code == 200, sdr.text
    assert sdr.json().get("status") == "delivered"

    now = datetime.utcnow().replace(microsecond=0)
    rec = ExecutionReceipt(
        task_id=task_id, agent_id=seller, step_index=1, tool_name="e2e.profile.tool",
        input_hash="ab" * 32, output_hash="cd" * 32, started_at=now,
        ended_at=now + timedelta(milliseconds=100), duration_ms=100, status=ToolStatus.SUCCESS,
    )
    rec.signature = signing_service.sign_receipt(rec)
    sr = await client.post(
        "/runtime/submit-receipt",
        headers={"X-Karma-Runtime-Key": seller_rt},
        json=rec.model_dump(mode="json"),
    )
    assert sr.status_code == 201, sr.text
    assert sr.json().get("profile_id") == pid, "receipt should inherit the runtime key profile_id"

    # 6. 买方 agent 批准结算 → settled
    bar = await client.post(
        "/runtime/request-settlement",
        headers={"X-Karma-Runtime-Key": buyer_rt},
        json={"task_id": task_id, "kind": "buyer_accept", "client_nonce": f"ba-{uuid.uuid4().hex}"},
    )
    assert bar.status_code == 200, bar.text
    assert bar.json().get("status") == "settled"
