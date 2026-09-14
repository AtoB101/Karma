"""技能开发者实名：主体认证 → 开发者实名 → 复核 → 上架（全程走真实 HTTP）。

这一版加的是「谁在卖」的最后一环：主体认证回答公司是谁，开发者实名回答**操作这个身份
的是哪个人**，并且要求上架签名的钱包就是签开发者协议的那个钱包。所以下面这些用例
既覆盖顺利路径，也覆盖三道必须挡住的门：没有实名不能上架、不能自审自己、
换个钱包签名不算本人。

注意：这个文件里 db_session 是共用的，所以每个用例用**自己的身份 id**，
``_certified_seller`` 也做成幂等的。
"""
from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import EntityVerificationModel, IdentityProfileModel
from services.chain import wallet_lock

ACCOUNT = Account.create()
KEY = ACCOUNT.key.hex()
WALLET = ACCOUNT.address.lower()

OTHER_ACCOUNT = Account.create()
OTHER_KEY = OTHER_ACCOUNT.key.hex()
OTHER_WALLET = OTHER_ACCOUNT.address.lower()

SELLER_GATE = "seller-dev-gate"
SELLER_FULL = "seller-dev-full"
SELLER_WALLET = "seller-dev-wallet"
STRANGER = "stranger-dev-1"
VERIFIER = "ops-verifier-1"
DOMAIN = "dev-example.test"

H = {
    name: {"X-Karma-Identity-Id": name}
    for name in (SELLER_GATE, SELLER_FULL, SELLER_WALLET, STRANGER, VERIFIER)
}


def _sign(message: str, key: str = KEY) -> str:
    return Account.sign_message(encode_defunct(text=message), private_key=key).signature.hex()


async def _certified_seller(db: AsyncSession, identity_id: str, wallet: str = WALLET) -> None:
    """给一个身份配好「已认证主体 + 在册钱包」。幂等：用例之间共用同一个 session。"""
    if await db.get(EntityVerificationModel, identity_id) is None:
        db.add(
            EntityVerificationModel(
                identity_id=identity_id,
                status="verified",
                subject_type="business",
                legal_name="示例数据科技有限公司",
                official_domain=DOMAIN,
                service_category="data_api",
            )
        )
    bound = (
        await db.execute(
            select(IdentityProfileModel).where(IdentityProfileModel.identity_id == identity_id)
        )
    ).scalars().first()
    if bound is None:
        db.add(
            IdentityProfileModel(
                identity_id=identity_id,
                display_id="Karma-ID-DEV-" + identity_id,
                legal_identity_status="unbound",
                status="active",
                bound_wallet_address=wallet,
            )
        )
    await db.flush()


def _developer_body(**over) -> dict:
    body = {
        "real_name": "张三",
        "role_title": "数据平台负责人",
        "contact_email": "zhangsan@example.com",
        "role": "api_owner",
    }
    body.update(over)
    return body


def _skill_body(slug: str) -> dict:
    return {
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


async def _make_verifier(client: AsyncClient, monkeypatch, db: AsyncSession) -> None:
    """治理角色不能自助开通：先证明不给白名单会 403，再把它加进白名单放行。"""
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": VERIFIER, "class": "verifier"},
        headers=H[VERIFIER],
    )
    assert r.status_code == 403, r.text
    assert "治理角色" in r.json()["detail"]

    monkeypatch.setattr(settings, "governance_verifier_ids", VERIFIER)
    if await db.get(EntityVerificationModel, VERIFIER) is None:
        db.add(
            EntityVerificationModel(
                identity_id=VERIFIER,
                status="verified",
                subject_type="business",
                legal_name="复核方科技有限公司",
                official_domain="verifier-example.test",
                service_category="other",
            )
        )
        await db.flush()
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": VERIFIER, "class": "verifier"},
        headers=H[VERIFIER],
    )
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------- 公开可读


async def test_public_developer_endpoints_are_open(client: AsyncClient):
    r = await client.get(f"/v1/developers?identity_id={SELLER_GATE}")
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0

    r = await client.get("/v1/developers/dev-does-not-exist")
    assert r.status_code == 404

    # 「我的」必须登录：没有身份头 -> 403
    r = await client.get("/v1/developers/me")
    assert r.status_code == 403


async def test_governance_roles_cannot_be_self_served(client: AsyncClient):
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": STRANGER, "class": "arbitrator"},
        headers=H[STRANGER],
    )
    assert r.status_code == 403
    assert "治理角色" in r.json()["detail"]

    # 日常角色不受影响
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": STRANGER, "class": "individual"},
        headers=H[STRANGER],
    )
    assert r.status_code == 201, r.text


# ------------------------------------------------------------ 门：先有主体


async def test_developer_signup_requires_a_certified_entity(client: AsyncClient):
    r = await client.post("/v1/developers/prepare", json=_developer_body(), headers=H[STRANGER])
    assert r.status_code == 409
    assert "主体" in r.json()["detail"]

    r = await client.post(
        "/v1/developers/submit",
        json=_developer_body(signature="0xdead"),
        headers=H[STRANGER],
    )
    assert r.status_code == 409


async def test_publishing_needs_a_verified_developer_not_just_an_entity(
    client: AsyncClient, db_session: AsyncSession
):
    await _certified_seller(db_session, SELLER_GATE)
    r = await client.post("/v1/skills/prepare", json=_skill_body("ticker-no-dev"), headers=H[SELLER_GATE])
    assert r.status_code == 409
    assert "开发者实名" in r.json()["detail"]


# ---------------------------------------------------------------- 完整链路


async def test_full_developer_onboarding_then_publish(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    await _certified_seller(db_session, SELLER_FULL)

    # 1) 生成待签协议：协议原文与 message 都由服务端给，前端只签名
    r = await client.post("/v1/developers/prepare", json=_developer_body(), headers=H[SELLER_FULL])
    assert r.status_code == 200, r.text
    prepared = r.json()
    assert prepared["legal_name"] == "示例数据科技有限公司"
    assert prepared["message"].startswith("Karma developer signup")
    assert "developer: 张三" in prepared["message"]
    assert prepared["agreement_digest"] in prepared["message"]
    assert "Karma 开发者协议" in prepared["agreement_text"]

    # 2) 提交（材料选传，这里不传）
    r = await client.post(
        "/v1/developers/submit",
        json=_developer_body(signature=_sign(prepared["message"])),
        headers=H[SELLER_FULL],
    )
    assert r.status_code == 200, r.text
    submitted = r.json()
    dev_id = submitted["developer_id"]
    assert submitted["status"] == "pending"
    assert submitted["signer_wallet"] == WALLET
    assert submitted["agreement_version"] == prepared["agreement_version"]

    # 3) 复核前仍然不能上架
    r = await client.post("/v1/skills/prepare", json=_skill_body("ticker-pending"), headers=H[SELLER_FULL])
    assert r.status_code == 409
    assert "开发者实名" in r.json()["detail"]

    # 4) 自己不能审自己
    await _make_verifier(client, monkeypatch, db_session)
    r = await client.post(
        f"/v1/developers/{dev_id}/review",
        json={"decision": "verified"},
        headers=H[SELLER_FULL],
    )
    assert r.status_code == 403
    assert "own" in r.json()["detail"]

    # 5) 复核方通过
    r = await client.post(
        f"/v1/developers/{dev_id}/review",
        json={"decision": "verified", "reason": "资质与主体一致"},
        headers=H[VERIFIER],
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"
    assert r.json()["reviewer_identity_id"] == VERIFIER

    # 6) 公开档案：实名可见，邮箱与密文一概不出
    r = await client.get(f"/v1/developers?identity_id={SELLER_FULL}")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert r.json()["developers"][0]["real_name"] == "张三"
    assert "contact_email" not in r.json()["developers"][0]

    r = await client.get(f"/v1/developers/{dev_id}")
    assert r.status_code == 200
    assert r.json()["signer_wallet"] == WALLET

    # 7) 现在才签得上架声明，并且技能行记住是哪个开发者上架的
    r = await client.post("/v1/skills/prepare", json=_skill_body("ticker-ok"), headers=H[SELLER_FULL])
    assert r.status_code == 200, r.text
    message = r.json()["message"]

    r = await client.post(
        "/v1/skills",
        json={**_skill_body("ticker-ok"), "publisher_signature": _sign(message)},
        headers=H[SELLER_FULL],
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"
    assert r.json()["developer_id"] == dev_id

    r = await client.get("/v1/skills/ticker-ok")
    assert r.status_code == 200
    assert r.json()["developer_id"] == dev_id


async def test_publish_signed_by_a_different_wallet_is_refused(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """身份在册钱包有两个时：只有**签了协议的那个钱包**能上架。"""
    await _certified_seller(db_session, SELLER_WALLET)

    r = await client.post("/v1/developers/prepare", json=_developer_body(), headers=H[SELLER_WALLET])
    assert r.status_code == 200, r.text
    message = r.json()["message"]
    r = await client.post(
        "/v1/developers/submit",
        json=_developer_body(signature=_sign(message)),
        headers=H[SELLER_WALLET],
    )
    assert r.status_code == 200, r.text
    dev_id = r.json()["developer_id"]

    await _make_verifier(client, monkeypatch, db_session)
    r = await client.post(
        f"/v1/developers/{dev_id}/review",
        json={"decision": "verified"},
        headers=H[VERIFIER],
    )
    assert r.status_code == 200, r.text

    async def _two_wallets(db, identity_id):
        return {WALLET, OTHER_WALLET}

    monkeypatch.setattr(wallet_lock, "allowed_wallets", _two_wallets)

    r = await client.post(
        "/v1/skills/prepare", json=_skill_body("ticker-other-wallet"), headers=H[SELLER_WALLET]
    )
    assert r.status_code == 200, r.text
    other_message = r.json()["message"]

    r = await client.post(
        "/v1/skills",
        json={
            **_skill_body("ticker-other-wallet"),
            "publisher_signature": _sign(other_message, OTHER_KEY),
        },
        headers=H[SELLER_WALLET],
    )
    assert r.status_code == 403, r.text
    assert "签过开发者协议" in r.json()["detail"]