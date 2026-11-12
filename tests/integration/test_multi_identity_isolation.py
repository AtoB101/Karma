"""
多身份隔离验收：一个主身份 + 3 个档案（个人/商家/企业），各自锁额度、记账、
结算互不混淆，一键切换后每个档案的账单与声誉独立正确。

流程（完全走真实 API，offchain 模式）：
  认证(owner) → 领身份卡 → 锁总额度 → 分配 3 档案 → 每档案各走一单
  voucher→settlement→receipt→settle → 验证额度/声誉/账单互不串账。
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
        "task_type": "e2e.isolation",
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": exp,
        "nonce": nonce,
        "buyer_signature": "0x" + "11" * 65,
        "currency": "USDC",
    }


async def _create_profile(client: AsyncClient, owner: str, class_: str, name: str) -> dict:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": owner, "class": class_, "display_name": name},
        headers={"X-Karma-Identity-Id": owner},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _mint_key(client, *, account, karma_identity_id, profile_id, permissions) -> str:
    expire = datetime.utcnow() + timedelta(days=30)
    msg = build_create_key_message(
        karma_identity_id=karma_identity_id, wallet_address=account.address,
        permissions=permissions, single_limit=500.0, daily_limit=5000.0,
        expire_time=expire, agent_name=f"iso-{karma_identity_id[:8]}", agent_binding=None,
    )
    signed = account.sign_message(encode_defunct(text=msg))
    r = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": account.address, "karma_identity_id": karma_identity_id,
            "wallet_signature": signed.signature.hex(), "permissions": permissions,
            "single_limit": 500.0, "daily_limit": 5000.0, "expire_time": expire.isoformat(),
            "agent_name": f"iso-{karma_identity_id[:8]}", "profile_id": profile_id,
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["runtime_key"])


async def _run_one_trade(
    client: AsyncClient,
    *,
    buyer: str,
    buyer_rt: str,
    profile: dict,
    seller: str,
    seller_rt: str,
    amount: float,
    tag: str,
) -> str:
    """跑一单：voucher → accept → settlement → receipt → settle，返回 task_id."""
    task_id = f"task-{tag}-{uuid.uuid4().hex[:8]}"
    await post_minimal_contract(client, task_id=task_id, client_agent_id=buyer, escrow_amount=amount)

    vr = await client.post(
        "/runtime/request-voucher",
        headers={"X-Karma-Runtime-Key": buyer_rt},
        json={"client_nonce": f"vc-{tag}-{uuid.uuid4().hex}", "voucher": _voucher_payload(buyer, seller, amount, f"vn-{tag}-{uuid.uuid4().hex}")},
    )
    assert vr.status_code == 201, f"[{tag}] voucher: {vr.text}"
    voucher_id = vr.json()["voucher_id"]
    assert vr.json().get("profile_id") == profile["profile_id"], f"[{tag}] voucher 应带 profile_id"

    assert (await client.post(f"/v1/vouchers/{voucher_id}/accept", json={"seller_identity_id": seller})).status_code == 200

    cr = await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": amount, "currency": "USD", "voucher_id": voucher_id},
    )
    assert cr.status_code == 201, f"[{tag}] settlement create: {cr.text}"
    assert cr.json().get("profile_id") == profile["profile_id"], f"[{tag}] settlement 应带 profile_id"

    await client.post(f"/v1/settlement/{task_id}/pending", json={})
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    sdr = await client.post(
        "/runtime/request-settlement",
        headers={"X-Karma-Runtime-Key": seller_rt},
        json={"task_id": task_id, "kind": "submit_delivery", "client_nonce": f"sd-{tag}-{uuid.uuid4().hex}"},
    )
    assert sdr.status_code == 200, f"[{tag}] submit_delivery: {sdr.text}"

    now = datetime.utcnow().replace(microsecond=0)
    rec = ExecutionReceipt(
        task_id=task_id, agent_id=seller, step_index=1, tool_name="e2e.isolation.tool",
        input_hash="ab" * 32, output_hash="cd" * 32, started_at=now,
        ended_at=now + timedelta(milliseconds=100), duration_ms=100, status=ToolStatus.SUCCESS,
    )
    rec.signature = signing_service.sign_receipt(rec)
    sr = await client.post("/runtime/submit-receipt", headers={"X-Karma-Runtime-Key": seller_rt}, json=rec.model_dump(mode="json"))
    assert sr.status_code == 201, f"[{tag}] submit_receipt: {sr.text}"
    assert sr.json().get("profile_id") == profile["profile_id"], f"[{tag}] receipt 应带 profile_id"

    bar = await client.post(
        "/runtime/request-settlement",
        headers={"X-Karma-Runtime-Key": buyer_rt},
        json={"task_id": task_id, "kind": "buyer_accept", "client_nonce": f"ba-{tag}-{uuid.uuid4().hex}"},
    )
    assert bar.status_code == 200, f"[{tag}] buyer_accept: {bar.text}"
    assert bar.json().get("status") == "settled", f"[{tag}] 应为 settled"
    return task_id


@pytest.mark.asyncio
async def test_three_profiles_isolated_ledgers(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "settlement_mode", "offchain")

    owner = f"owner-{uuid.uuid4().hex[:8]}"
    owner_acct = Account.create()

    # ── 认证 + 领取身份卡 ──
    card = await client.get(f"/v1/identity/{owner}/card")
    # 身份卡需要身份存在；dev 下用 header 建档案即隐式认证。此处创建 3 档案。
    specs = [
        ("individual", "个人", 250.0),
        ("merchant", "商家", 350.0),
        ("enterprise", "企业", 400.0),
    ]
    profiles = {}
    for class_, name, _ in specs:
        p = await _create_profile(client, owner, class_, name)
        profiles[class_] = p

    # ── 锁总额度 = 1000，分配给 3 档案 25/35/40% ──
    await client.post(f"/v1/capacity/{owner}/lock", json={"amount": 1000.0}, headers={"X-Karma-Identity-Id": owner})
    alloc_body = {profiles[c]["profile_id"]: amt for c, _, amt in specs}
    ar = await client.put(
        f"/v1/capacity/{owner}/allocations",
        json={"allocations": alloc_body},
        headers={"X-Karma-Identity-Id": owner},
    )
    assert ar.status_code == 200, ar.text
    alloc_map = {a["profile_id"]: a for a in ar.json()["allocations"]}
    for class_, _, amt in specs:
        assert alloc_map[profiles[class_]["profile_id"]]["allocated_credits"] == amt, class_

    # ── 每档案一个 seller + runtime key ──
    sellers = {}
    for class_, name, _ in specs:
        acct = Account.create()
        pid = profiles[class_]["profile_id"]
        buyer_rt = await _mint_key(client, account=owner_acct, karma_identity_id=owner, profile_id=pid,
                                   permissions=["request_voucher", "request_settlement", "sync_task_status"])
        seller_rt = await _mint_key(client, account=acct, karma_identity_id=f"{owner}-{class_}", profile_id=pid,
                                    permissions=["submit_receipt", "request_settlement", "sync_task_status"])
        sellers[class_] = {"account": acct, "buyer_rt": buyer_rt, "seller_rt": seller_rt}

    # ── 每档案各下一单（金额各异） ──
    amounts = {"individual": 100.0, "merchant": 150.0, "enterprise": 200.0}
    for class_, name, _ in specs:
        s = sellers[class_]
        await _run_one_trade(
            client, buyer=owner, buyer_rt=s["buyer_rt"], profile=profiles[class_],
            seller=f"{owner}-{class_}", seller_rt=s["seller_rt"],
            amount=amounts[class_], tag=class_,
        )

    # ── 一键切换验证：每个档案额度/声誉互不串账 ──
    final = await client.get(f"/v1/capacity/{owner}/allocations", headers={"X-Karma-Identity-Id": owner})
    assert final.status_code == 200
    rows = {a["profile_id"]: a for a in final.json()["allocations"]}

    for class_, name, alloc_amt in specs:
        pid = profiles[class_]["profile_id"]
        row = rows[pid]
        traded = amounts[class_]
        # 结算后 in_progress 归零、released = 成交额、available = 分配额 - 成交额
        assert row["in_progress_credits"] == 0.0, f"[{name}] 结算后 in_progress 应为 0，实际 {row['in_progress_credits']}"
        assert abs(row["released_credits"] - traded) < 1e-6, f"[{name}] released 应={traded}，实际 {row['released_credits']}"
        assert abs(row["available_credits"] - (alloc_amt - traded)) < 1e-6, (
            f"[{name}] available 应={alloc_amt - traded}，实际 {row['available_credits']}"
        )

    # 声誉：每个档案独立 +1 成交，score 独立
    for class_, name, _ in specs:
        p = profiles[class_]
        r = await client.get(f"/v1/identity/role-profiles/{p['profile_id']}", headers={"X-Karma-Identity-Id": owner})
        assert r.status_code == 200, r.text
        rep = r.json()["reputation"]
        assert rep["profile_id"] == p["profile_id"], f"[{name}] 声誉应绑定该档案"
        assert rep["successful_tasks"] == 1, f"[{name}] 应记 1 次成交，实际 {rep['successful_tasks']}"
        assert rep["score"] > 100.0, f"[{name}] score 应上升"

    # 总额度对账：3 档案分配总额 = 1000 = 锁仓额
    total_alloc = sum(alloc_map[profiles[c]["profile_id"]]["allocated_credits"] for c, _, _ in specs)
    assert total_alloc == 1000.0
