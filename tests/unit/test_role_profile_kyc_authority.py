# -*- coding: utf-8 -*-
"""角色档案认证状态的写入权：只能由认证流程写，本人建 / 改档案时不许自报。

2026-10-08 复核发现：``POST`` / ``PUT`` 请求体里的 ``kyc_status`` 会被原样入库，
本人一次调用就能把企业 / 个体户档案写成 ``verified``；KYC 载荷里的 ``verification``
（复核结论）键同样能由本人自写。认证状态是消费者判断「能不能跟你做生意」的依据，
这里把这几条写入路径钉死。
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

OWNER = {"X-Karma-Identity-Id": "kid-kyc-owner"}
VERIFIER = {"X-Karma-Identity-Id": "kid-kyc-verifier"}


@pytest.fixture(autouse=True)
def _allow_verifier(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "governance_verifier_ids", "kid-kyc-verifier")


async def _create(
    client: AsyncClient, klass: str = "merchant", *, owner: str = "kid-kyc-owner", **extra
):
    body = {"owner_identity_id": owner, "class": klass}
    body.update(extra)
    return await client.post(
        "/v1/identity/role-profiles",
        json=body,
        headers={"X-Karma-Identity-Id": owner},
    )


async def _create_ok(client: AsyncClient, klass: str = "merchant", **extra) -> dict:
    r = await _create(client, klass, **extra)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_create_cannot_self_declare_kyc_status(client: AsyncClient):
    """建档案时自报任何非 none 的 kyc_status 都要被拒（企业 / 个体户档案）。"""
    for klass in ("merchant", "enterprise"):
        r = await _create(client, klass, kyc_status="verified")
        assert r.status_code == 422, "建 %s 档案不许自报 verified：%s" % (klass, r.text)
    r = await _create(client, "merchant", kyc_status="pending")
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_update_cannot_self_declare_kyc_status(client: AsyncClient):
    pid = (await _create_ok(client))["profile_id"]
    r = await client.put(
        f"/v1/identity/role-profiles/{pid}", json={"kyc_status": "verified"}, headers=OWNER
    )
    assert r.status_code == 422, r.text
    row = await client.get(f"/v1/identity/role-profiles/{pid}", headers=OWNER)
    assert row.json()["kyc_status"] == "none"


@pytest.mark.asyncio
async def test_create_strips_self_written_verdict(client: AsyncClient):
    """载荷里的「复核结论」键只属于复核方，本人建档案时带了也要被摘掉。"""
    p = await _create_ok(
        client,
        kyc_payload={"kind": "sole_proprietor", "verification": {"decision": "verified"}},
    )
    assert "verification" not in p["kyc_payload"]


@pytest.mark.asyncio
async def test_submit_strips_self_written_verdict(client: AsyncClient):
    pid = (await _create_ok(client))["profile_id"]
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc",
        json={"kyc_payload": {"kind": "sole_proprietor", "verification": {"decision": "verified"}}},
        headers=OWNER,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kyc_status"] == "pending"
    assert "verification" not in body["kyc_payload"]


@pytest.mark.asyncio
async def test_create_rejects_plaintext_document_payload(client: AsyncClient):
    """建档案的 kyc_payload 和提交走同一条明文红线：证件原图 / 裸 base64 一律 400。"""
    r = await _create(client, "merchant", kyc_payload={"business_license_scan": "A" * 5000})
    assert r.status_code == 400 and "base64" in r.json()["detail"], r.text
    r = await _create(client, "merchant", kyc_payload={"photo": "data:image/png;base64,AAAA"})
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_verifier_decision_is_recorded_by_server(client: AsyncClient):
    """复核方（verifier 岗、非本人）下的结论由服务端写入并保留 —— 权威路径不许被上面的堵漏误伤。"""
    verifier_profile = await _create(client, "verifier", owner="kid-kyc-verifier")
    assert verifier_profile.status_code == 201, verifier_profile.text

    pid = (await _create_ok(client))["profile_id"]
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc",
        json={"kyc_payload": {"kind": "sole_proprietor", "business_name": "张三小吃店"}},
        headers=OWNER,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/verify",
        json={"decision": "verified", "reason": "证件与工商信息一致"},
        headers=VERIFIER,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kyc_status"] == "verified"
    assert body["kyc_payload"]["verification"]["decision"] == "verified"
    assert body["kyc_payload"]["verification"]["verified_by"] == "kid-kyc-verifier"
