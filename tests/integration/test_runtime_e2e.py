"""
Runtime Gateway — 端到端集成验收（HTTP + 内存 SQLite）

覆盖验收标准中的主链路：Runtime Key 签发 → 权限/容量 → Runtime 请求 Voucher →
结算状态推进 → Runtime 提交 Execution Receipt → 任务状态查询 → Runtime 请求结算。

说明：与 ``tests/integration/test_api.py`` 相同，使用 ``client`` 夹具与 ASGI 传输；
不启动真实外网 ``runtime.karma.network``。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from core.schemas import ExecutionReceipt, ToolStatus
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from httptest import post_minimal_contract
from services.runtime_wallet import (
    build_create_key_message,
    build_list_keys_message,
    build_revoke_key_message,
)
from services.signing import signing_service


def _voucher_payload(
    *,
    buyer: str,
    seller: str,
    amount: float,
    nonce: str,
    buyer_signature: str = "0x" + "11" * 65,
) -> dict:
    h = "aa" * 32
    exp = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": amount,
        "bill_credit_amount": amount,
        "task_type": "e2e.runtime.flow",
        "task_description_hash": h,
        "progress_rule_hash": h,
        "evidence_requirement_hash": h,
        "expiry_time": exp,
        "nonce": nonce,
        "buyer_signature": buyer_signature,
        "currency": "USDC",
    }


async def _mint_runtime_key(
    client: AsyncClient,
    *,
    account: Account,
    karma_identity_id: str,
    permissions: list[str],
    single_limit: float = 500.0,
    daily_limit: float = 5000.0,
    days_valid: int = 30,
) -> str:
    """返回明文 ``KRM_RT_…``（仅用于测试断言）。"""
    expire = datetime.utcnow() + timedelta(days=days_valid)
    msg = build_create_key_message(
        karma_identity_id=karma_identity_id,
        wallet_address=account.address,
        permissions=permissions,
        single_limit=single_limit,
        daily_limit=daily_limit,
        expire_time=expire,
        agent_name=f"e2e-{karma_identity_id[:8]}",
        agent_binding=None,
    )
    signed = account.sign_message(encode_defunct(text=msg))
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": account.address,
            "karma_identity_id": karma_identity_id,
            "wallet_signature": signed.signature.hex(),
            "permissions": permissions,
            "single_limit": single_limit,
            "daily_limit": daily_limit,
            "expire_time": expire.isoformat(),
            "agent_name": f"e2e-{karma_identity_id[:8]}",
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["runtime_key"])


@pytest.mark.asyncio
async def test_runtime_e2e_list_keys_and_revoke(client: AsyncClient):
    acct = Account.create()
    identity = f"e2e-list-{uuid.uuid4().hex[:10]}"
    rt = await _mint_runtime_key(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=["sync_task_status", "request_voucher"],
    )

    list_nonce = f"ln-{uuid.uuid4().hex}"
    lmsg = build_list_keys_message(
        karma_identity_id=identity,
        wallet_address=acct.address,
        client_nonce=list_nonce,
    )
    lsig = acct.sign_message(encode_defunct(text=lmsg))
    lr = await client.post(
        "/runtime/list-keys",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": identity,
            "wallet_signature": lsig.signature.hex(),
            "client_nonce": list_nonce,
        },
    )
    assert lr.status_code == 200, lr.text
    keys = lr.json().get("keys") or []
    assert len(keys) >= 1
    key_id = keys[0]["key_id"]

    rmsg = build_revoke_key_message(key_id=key_id, karma_identity_id=identity, wallet_address=acct.address)
    rsig = acct.sign_message(encode_defunct(text=rmsg))
    rr = await client.post(
        "/runtime/revoke-key",
        json={
            "key_id": key_id,
            "wallet_address": acct.address,
            "karma_identity_id": identity,
            "wallet_signature": rsig.signature.hex(),
        },
    )
    assert rr.status_code == 200, rr.text
    assert rr.json().get("status") == "revoked"

    bad = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": rt})
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_runtime_e2e_voucher_receipt_settlement_flow(client: AsyncClient):
    """
    买方 Runtime Key：request_voucher + request_settlement(buyer_accept) + sync
    卖方 Runtime Key：submit_receipt + request_settlement(submit_delivery) + sync
    """
    buyer = f"e2e-rt-buy-{uuid.uuid4().hex[:8]}"
    seller = f"e2e-rt-sell-{uuid.uuid4().hex[:8]}"
    buyer_acct = Account.create()
    seller_acct = Account.create()

    buyer_rt = await _mint_runtime_key(
        client,
        account=buyer_acct,
        karma_identity_id=buyer,
        permissions=["request_voucher", "request_settlement", "sync_task_status"],
    )
    seller_rt = await _mint_runtime_key(
        client,
        account=seller_acct,
        karma_identity_id=seller,
        permissions=["submit_receipt", "request_settlement", "sync_task_status"],
    )

    cap = await client.get("/runtime/capacity", headers={"X-Karma-Runtime-Key": buyer_rt})
    assert cap.status_code == 200
    assert cap.json().get("identity_id") == buyer

    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 120.0})

    task_id = f"task-rt-e2e-{uuid.uuid4().hex[:12]}"

    await post_minimal_contract(
        client,
        task_id=task_id,
        client_agent_id=buyer,
        escrow_amount=35.0,
        expected_step_count=5,
    )

    v_nonce = f"vn-{uuid.uuid4().hex}"
    vclient = f"vc-{uuid.uuid4().hex}"
    voucher_body = _voucher_payload(buyer=buyer, seller=seller, amount=35.0, nonce=v_nonce)
    vr = await client.post(
        "/runtime/request-voucher",
        headers={"X-Karma-Runtime-Key": buyer_rt},
        json={"client_nonce": vclient, "voucher": voucher_body},
    )
    assert vr.status_code == 201, vr.text
    voucher_id = vr.json()["voucher_id"]

    acc = await client.post(f"/v1/vouchers/{voucher_id}/accept", json={"seller_identity_id": seller})
    assert acc.status_code == 200, acc.text

    cr = await client.post(
        "/v1/settlement/create",
        json={
            "task_id": task_id,
            "client_agent_id": buyer,
            "escrow_amount": 35.0,
            "currency": "USD",
            "voucher_id": voucher_id,
        },
    )
    assert cr.status_code == 201, cr.text

    assert (await client.post(f"/v1/settlement/{task_id}/pending", json={})).status_code == 200
    assert (
        await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    ).status_code == 200
    assert (await client.post(f"/v1/settlement/{task_id}/start", json={})).status_code == 200

    sd_nonce = f"sd-{uuid.uuid4().hex}"
    sdr = await client.post(
        "/runtime/request-settlement",
        headers={"X-Karma-Runtime-Key": seller_rt},
        json={"task_id": task_id, "kind": "submit_delivery", "client_nonce": sd_nonce},
    )
    assert sdr.status_code == 200, sdr.text
    assert sdr.json().get("status") == "delivered"

    now = datetime.utcnow().replace(microsecond=0)
    rec = ExecutionReceipt(
        task_id=task_id,
        agent_id=seller,
        step_index=1,
        tool_name="e2e.runtime.tool",
        input_hash="ab" * 32,
        output_hash="cd" * 32,
        started_at=now,
        ended_at=now + timedelta(milliseconds=120),
        duration_ms=120,
        status=ToolStatus.SUCCESS,
    )
    rec.signature = signing_service.sign_receipt(rec)
    # 网关会重新签名；此处提供合法字段即可
    sr = await client.post(
        "/runtime/submit-receipt",
        headers={"X-Karma-Runtime-Key": seller_rt},
        json=rec.model_dump(mode="json"),
    )
    assert sr.status_code == 201, sr.text

    ts = await client.get(f"/runtime/task-status/{task_id}", headers={"X-Karma-Runtime-Key": seller_rt})
    assert ts.status_code == 200, ts.text
    body = ts.json()
    assert body["task_id"] == task_id
    assert len(body.get("execution_receipts") or []) >= 1

    ba_nonce = f"ba-{uuid.uuid4().hex}"
    bar = await client.post(
        "/runtime/request-settlement",
        headers={"X-Karma-Runtime-Key": buyer_rt},
        json={"task_id": task_id, "kind": "buyer_accept", "client_nonce": ba_nonce},
    )
    assert bar.status_code == 200, bar.text
    assert bar.json().get("status") == "settled"


@pytest.mark.asyncio
async def test_runtime_e2e_permissions_chain_id(client: AsyncClient):
    acct = Account.create()
    identity = f"e2e-chain-{uuid.uuid4().hex[:8]}"
    rt = await _mint_runtime_key(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=["sync_task_status"],
    )
    pr = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": rt})
    assert pr.status_code == 200
    data = pr.json()
    assert "chain_id" in data
    assert isinstance(data["chain_id"], int)
