"""数据 API 商业化：主体认证 → 技能上架 → 按次调用 → 到阈值出账（全程走真实 HTTP）。

这是给运营看的"整条业务能不能跑通"的用例：每一步都通过路由，不直接调服务层，
所以路由挂载、鉴权、序列化、以及账本恒等式都在同一遍里过。
"""
from __future__ import annotations

import uuid

import pytest
from eth_account import Account
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import (
    AllowanceCommitModel,
    EntityVerificationModel,
    IdentityProfileModel,
    SkillDeveloperModel,
)
from services.chain import allowance_escrow as escrow
from services.developer_registry import AGREEMENT_VERSION, agreement_digest

ACCOUNT = Account.create()
KEY = ACCOUNT.key.hex()
WALLET = ACCOUNT.address.lower()

SELLER = "seller-data-1"
BUYER = "buyer-data-1"
STRANGER = "stranger-1"
DOMAIN = "data-example.test"
H = {
    SELLER: {"X-Karma-Identity-Id": SELLER},
    BUYER: {"X-Karma-Identity-Id": BUYER},
    STRANGER: {"X-Karma-Identity-Id": STRANGER},
}


async def _certified_seller(db: AsyncSession) -> None:
    db.add(
        EntityVerificationModel(
            identity_id=SELLER,
            status="verified",
            subject_type="business",
            legal_name="示例数据科技有限公司",
            official_domain=DOMAIN,
            service_category="data_api",
        )
    )
    db.add(
        IdentityProfileModel(
            identity_id=SELLER,
            display_id="Karma-ID-SELLER1",
            legal_identity_status="unbound",
            status="active",
            bound_wallet_address=WALLET,
        )
    )
    # 上架还要过「开发者实名」这一关（SKILL_REQUIRE_DEVELOPER_VERIFICATION 默认开启），
    # 所以这个已认证主体下也要有一个复核通过、且用同一个钱包签过协议的人。
    db.add(
        SkillDeveloperModel(
            identity_id=SELLER,
            legal_name="示例数据科技有限公司",
            real_name="张三",
            role_title="数据平台负责人",
            contact_email="zhangsan@example.com",
            developer_role="api_owner",
            agreement_version=AGREEMENT_VERSION,
            agreement_digest=agreement_digest(),
            signer_wallet=WALLET,
            status="verified",
        )
    )
    await db.flush()


async def _commit(db: AsyncSession, identity_id: str, amount: float, tag: str) -> None:
    db.add(
        AllowanceCommitModel(
            bill_id=f"bill-{tag}-{uuid.uuid4().hex[:6]}",
            identity_id=identity_id,
            wallet_address="0x" + "ab" * 20,
            amount_usdc=amount,
            commit_tx_hash="0x" + uuid.uuid4().hex + uuid.uuid4().hex,
            state=escrow.IDLE,
        )
    )
    await db.flush()


def _skill_body(slug: str, **over) -> dict:
    body = {
        "slug": slug,
        "name": "行情快照 API",
        "category": "data_api",
        "summary": "按次计费的交易所行情快照，毫秒级返回",
        "description": "覆盖 20+ 交易所",
        "endpoint_url": f"https://api.{DOMAIN}/v1/ticker",
        "method": "POST",
        "unit": "call",
        "unit_price_usdc": 0.01,
        "settlement_threshold_usdc": 0.02,
        "default_cap_usdc": 10.0,
    }
    body.update(over)
    return body


def _sign(message: str) -> str:
    from eth_account.messages import encode_defunct

    return Account.sign_message(encode_defunct(text=message), private_key=KEY).signature.hex()


@pytest.mark.asyncio
async def test_public_catalog_is_open_to_everyone(client: AsyncClient):
    r = await client.get("/v1/skills")
    assert r.status_code == 200, r.text
    assert "skills" in r.json()

    r = await client.get("/v1/entities/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_publish_requires_a_certified_entity(client: AsyncClient, db_session: AsyncSession):
    r = await client.post(
        "/v1/skills/prepare", json=_skill_body("ticker-nobody"), headers=H[STRANGER]
    )
    assert r.status_code == 409
    assert "主体认证" in r.json()["detail"]

    r = await client.post("/v1/skills/mine", json={}, headers=H[STRANGER])
    assert r.status_code in (404, 405)  # 只读接口，不该接受 POST

    # 目录与主体公开信息是公开可读的（尽调方不该先注册才能看）
    r = await client.get("/v1/skills")
    assert r.status_code == 200
    r = await client.get("/v1/skills/mine")
    assert r.status_code == 403  # 「我的」必须登录

    # 写接口一律要身份：没有身份头 -> 403
    r = await client.post("/v1/skills/prepare", json=_skill_body("ticker-anon"))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_full_billing_loop_over_http(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    await _certified_seller(db_session)
    slug = f"ticker-{uuid.uuid4().hex[:6]}"

    # 1) 服务端给待签声明（前端不自己拼串）
    r = await client.post("/v1/skills/prepare", json=_skill_body(slug), headers=H[SELLER])
    assert r.status_code == 200, r.text
    prep = r.json()
    assert prep["version"] == 1
    assert prep["verified_domain"] == DOMAIN

    # 2) 本人钱包签名后上架
    r = await client.post(
        "/v1/skills",
        json={**_skill_body(slug), "publisher_signature": _sign(prep["message"])},
        headers=H[SELLER],
    )
    assert r.status_code == 200, r.text
    published = r.json()
    assert published["status"] == "published"
    assert published["publisher_wallet"] == WALLET

    # 3) 目录里能看到
    r = await client.get("/v1/skills?q=" + slug)
    assert r.status_code == 200
    assert [s["slug"] for s in r.json()["skills"]] == [slug]

    # 4) 同一个 slug 被别的主体抢 -> 409（且不是 500）
    r = await client.post("/v1/skills/prepare", json=_skill_body(slug), headers=H[STRANGER])
    assert r.status_code == 409

    # 5) 没锁仓就调用 -> 409（提供方不该白干）
    r = await client.post(
        f"/v1/skills/{slug}/use", json={"request_id": "req-1"}, headers=H[BUYER]
    )
    assert r.status_code == 409
    assert "锁仓" in r.json()["detail"]

    # 6) 锁仓后可以调用，且重放不重复计费
    await _commit(db_session, BUYER, 100.0, "buyer")
    r = await client.post(
        f"/v1/skills/{slug}/use", json={"request_id": "req-1"}, headers=H[BUYER]
    )
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["duplicate"] is False and first["amount_usdc"] == 0.01

    r = await client.post(
        f"/v1/skills/{slug}/use", json={"request_id": "req-1"}, headers=H[BUYER]
    )
    assert r.status_code == 200
    assert r.json()["duplicate"] is True

    # 7) 到阈值 -> 出账并提交链上（这里把链上换成假的，只验证流程与账本）
    await _commit(db_session, SELLER, 100.0, "seller")
    monkeypatch.setattr(escrow, "can_server_settle", lambda: True)

    # 每次用全新的哈希：测试库是 session 级的，写死的 0x22… 会和别的用例撞唯一键。
    def _fake_open(**kw):
        return {
            "binding_id": int(uuid.uuid4().int % 900000) + 1000,
            "scope_hash": "0x" + uuid.uuid4().hex + uuid.uuid4().hex,
            "bind_tx_hash": "0x" + uuid.uuid4().hex + uuid.uuid4().hex,
            "submit_tx_hash": "0x" + uuid.uuid4().hex + uuid.uuid4().hex,
            "proof_hash": "0x" + uuid.uuid4().hex + uuid.uuid4().hex,
            "pull_after": 1,
        }

    monkeypatch.setattr(escrow, "open_and_submit_order", _fake_open)
    r = await client.post(
        f"/v1/skills/{slug}/use", json={"request_id": "req-2"}, headers=H[BUYER]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settlement"] is not None
    assert body["settlement"]["charged"] is True
    assert body["settlement"]["settlement"]["amount_usdc"] == 0.02
    assert body["settlement"]["settlement"]["status"] == "submitted"
    assert body["meter"]["settled_usdc"] == 0.0   # 链上还没执行完，不许提前喊结算

    # 8) 计费详情对提供方与付款方都可见
    r = await client.get(f"/v1/skills/{slug}/usage", headers=H[BUYER])
    assert r.status_code == 200, r.text
    assert r.json()["meter"]["billed_usdc"] == 0.02

    r = await client.get(f"/v1/skills/{slug}/usage", headers=H[SELLER])
    assert r.status_code == 200
    assert r.json()["counting_for"] == "provider"

    # 9) 第三者看不到别人的计费明细
    r = await client.get(
        f"/v1/skills/{slug}/usage?payer_identity_id={BUYER}", headers=H[STRANGER]
    )
    assert r.status_code == 403

    # 10) 下架后不再接受调用
    r = await client.post(f"/v1/skills/{slug}/pause", json={}, headers=H[SELLER])
    assert r.status_code == 200 and r.json()["status"] == "paused"
    r = await client.post(
        f"/v1/skills/{slug}/use", json={"request_id": "req-3"}, headers=H[BUYER]
    )
    assert r.status_code == 409