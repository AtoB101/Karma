"""复核台（``/v1/reviews``）端到端：谁能进、能看到什么、以及几条不能破的线。

这块是运营侧的入口：把三类待办（主体认证 / 开发者实名 / 子身份 KYC）汇到一个队列里，
每条都带上**自动核验结论**，人工只看机器判不了的那部分。

必须守住的线：
- 不是 verifier 类档案 → 403（治理角色不能自助开通，这里只管「有了才能进」）；
- **自己的提交永远不出现在自己的队列里** —— 复核岗不能给自己放行；
- 自动核验只给结论，不替人做决定：DNS 查不动只能是"不可用"，不能判人不通过。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import EntityVerificationModel, IdentityRoleProfile, SkillDeveloperModel
from services import auto_verification

VERIFIER = "reviews-verifier"
STRANGER = "reviews-stranger"

H = {name: {"X-Karma-Identity-Id": name} for name in (VERIFIER, STRANGER)}

#: GB 32100-2015 校验位算得对的统一社会信用代码。
VALID_USCC = "91330100MA2ABCDE1R"
SCOPE = "提供行情快照与历史数据的按次调用接口服务"


@pytest.fixture(autouse=True)
def _allow_governance_roles(monkeypatch):
    """verifier / arbitrator 默认不许自助开通；这里把用到的身份放进运维白名单。

    「不给白名单就必须 403」这件事由 tests/integration/test_developer_api.py 覆盖。
    """
    monkeypatch.setattr(settings, "governance_verifier_ids", VERIFIER + ",reviews-suspended")


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch):
    """复核队列会给每条待办跑自检，自检里要查 MX。

    单测/集成测试不许碰真实 DNS：断网、域名过期、公司网络改 DNS 都会让测试红成假红。
    """
    monkeypatch.setattr(
        auto_verification,
        "lookup_mx",
        lambda domain, **kw: {
            "status": auto_verification.STATUS_PASS,
            "records": ["mx.example.com"],
            "note": "stub",
        },
    )


async def _make_verifier(client: AsyncClient, identity_id: str = VERIFIER) -> None:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": identity_id, "class": "verifier", "display_name": "运营复核岗"},
        headers={"X-Karma-Identity-Id": identity_id},
    )
    assert r.status_code == 201, r.text


async def _pending_entity(
    db: AsyncSession,
    identity_id: str,
    *,
    registration_no: str = VALID_USCC,
    submitted_at: datetime | None = None,
) -> None:
    if await db.get(EntityVerificationModel, identity_id) is not None:
        return
    db.add(
        EntityVerificationModel(
            identity_id=identity_id,
            status="pending",
            subject_type="business",
            legal_name="示例数据科技有限公司",
            registration_no=registration_no,
            official_domain="entity-example.test",
            contact_email="ops@entity-example.test",
            service_category="data_api",
            service_scope=SCOPE,
            certifications=[{"kind": "business_license", "name": "营业执照"}],
            submitted_at=submitted_at or datetime.utcnow(),
        )
    )
    await db.flush()


async def _pending_developer(db: AsyncSession, identity_id: str) -> str:
    developer_id = "rev-dev-" + identity_id
    if await db.get(SkillDeveloperModel, developer_id) is None:
        db.add(
            SkillDeveloperModel(
                developer_id=developer_id,
                identity_id=identity_id,
                legal_name="示例数据科技有限公司",
                real_name="张三",
                role_title="数据平台负责人",
                contact_email="zhangsan@entity-example.test",
                status="pending",
                submitted_at=datetime.utcnow(),
            )
        )
        await db.flush()
    return developer_id


async def _pending_kyc(client: AsyncClient, owner: str) -> str:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": owner, "class": "merchant", "display_name": "老王面馆"},
        headers={"X-Karma-Identity-Id": owner},
    )
    assert r.status_code == 201, r.text
    profile_id = r.json()["profile_id"]

    r = await client.post(
        f"/v1/identity/role-profiles/{profile_id}/kyc",
        json={
            "kyc_payload": {
                "kind": "sole_proprietor",
                "business_name": "老王面馆",
                "operator_name": "王大明",
                "registration_no": VALID_USCC,
                "business_scope": "餐饮服务",
                "business_address": "浙江省杭州市西湖区某路 1 号",
                "contact_email": "wang@entity-example.test",
            }
        },
        headers={"X-Karma-Identity-Id": owner},
    )
    assert r.status_code == 200, r.text
    return profile_id


# ------------------------------------------------------------------ 谁能进


async def test_queue_is_closed_to_anonymous_and_to_non_verifiers(client: AsyncClient):
    r = await client.get("/v1/reviews/pending")
    assert r.status_code == 403

    r = await client.get("/v1/reviews/pending", headers=H[STRANGER])
    assert r.status_code == 403
    assert "verifier" in r.json()["detail"]


async def test_verifier_with_a_revoked_profile_cannot_open_the_queue(
    client: AsyncClient, db_session: AsyncSession
):
    """档案被停用（status != active）＝ 权限收回，不是"建过一次就永久有效"。"""
    await _make_verifier(client, "reviews-suspended")
    row = (
        await db_session.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == "reviews-suspended"
            )
        )
    ).scalars().first()
    assert row is not None
    row.status = "suspended"
    await db_session.flush()

    r = await client.get(
        "/v1/reviews/pending", headers={"X-Karma-Identity-Id": "reviews-suspended"}
    )
    assert r.status_code == 403


# ------------------------------------------------------------------ 队列内容


async def test_queue_carries_all_three_kinds_with_auto_checks(
    client: AsyncClient, db_session: AsyncSession
):
    await _make_verifier(client)
    entity_id = "rev-owner-entity"
    developer_owner = "rev-owner-developer"
    kyc_owner = "rev-owner-kyc"

    await _pending_entity(db_session, entity_id)
    developer_id = await _pending_developer(db_session, developer_owner)
    profile_id = await _pending_kyc(client, kyc_owner)

    # 已经通过的主体不该出现在待办里
    await _pending_entity(db_session, "rev-owner-already-verified")
    verified = await db_session.get(EntityVerificationModel, "rev-owner-already-verified")
    verified.status = "verified"
    await db_session.flush()

    r = await client.get("/v1/reviews/pending", headers=H[VERIFIER])
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["verifier_identity_id"] == VERIFIER
    by_id = {item["item_id"]: item for item in body["items"]}
    assert entity_id in by_id
    assert developer_id in by_id
    assert profile_id in by_id
    assert "rev-owner-already-verified" not in by_id

    kinds = {by_id[i]["kind"] for i in (entity_id, developer_id, profile_id)}
    assert kinds == {"entity_verification", "developer", "role_profile_kyc"}

    for item_id in (entity_id, developer_id, profile_id):
        item = by_id[item_id]
        assert item["auto_checks"]["checks"], item_id
        assert "ok" in item["auto_checks"]
        assert item["decide"]["body_key"] == "decision"
        assert item["owner_identity_id"]
        assert isinstance(item["materials"], list)

    assert by_id[entity_id]["decide"]["approve_path"].endswith(
        f"/v1/identity/{entity_id}/entity-verification/verify"
    )
    assert by_id[developer_id]["decide"]["approve_path"].endswith(
        f"/v1/developers/{developer_id}/review"
    )
    assert by_id[profile_id]["decide"]["approve_path"].endswith(
        f"/v1/identity/role-profiles/{profile_id}/kyc/verify"
    )

    assert body["counts"]["entity_verification"] >= 1
    assert body["counts"]["developer"] >= 1
    assert body["counts"]["role_profile_kyc"] >= 1


async def test_own_submissions_never_land_in_my_own_queue(
    client: AsyncClient, db_session: AsyncSession
):
    """复核岗不能给自己放行：自己提交的待办要消失，并且被计数出来。"""
    await _make_verifier(client)
    await _pending_entity(db_session, VERIFIER)
    await _pending_developer(db_session, VERIFIER)

    r = await client.get("/v1/reviews/pending", headers=H[VERIFIER])
    assert r.status_code == 200, r.text
    body = r.json()

    assert all(item["owner_identity_id"] != VERIFIER for item in body["items"])
    assert body["counts"]["skipped_own"] >= 2


async def test_items_the_machine_rejected_sort_to_the_front(
    client: AsyncClient, db_session: AsyncSession
):
    """机器已经判定不通过的排前面 —— 人工先把最可能有问题的那批处理掉。"""
    await _make_verifier(client)
    now = datetime.utcnow()
    await _pending_entity(
        db_session,
        "rev-owner-clean",
        registration_no=VALID_USCC,
        submitted_at=now - timedelta(days=3),
    )
    await _pending_entity(
        db_session,
        "rev-owner-broken",
        registration_no=VALID_USCC[:-1] + "X",
        submitted_at=now,
    )

    r = await client.get("/v1/reviews/pending", headers=H[VERIFIER])
    assert r.status_code == 200, r.text
    order = [item["item_id"] for item in r.json()["items"]]

    assert order.index("rev-owner-broken") < order.index("rev-owner-clean")
    broken = next(i for i in r.json()["items"] if i["item_id"] == "rev-owner-broken")
    assert broken["auto_checks"]["ok"] is False
    assert "registration_no" in broken["auto_checks"]["blocking_failures"]


# ------------------------------------------------------------------ 提交前自检


async def test_precheck_is_closed_to_anonymous(client: AsyncClient):
    r = await client.post("/v1/reviews/precheck", json={"kind": "entity", "subject": {}})
    assert r.status_code == 403


async def test_precheck_only_accepts_the_three_known_kinds(client: AsyncClient):
    r = await client.post(
        "/v1/reviews/precheck", json={"kind": "whatever", "subject": {}}, headers=H[STRANGER]
    )
    assert r.status_code == 422


async def test_precheck_entity_catches_a_typo_in_the_credit_code(client: AsyncClient):
    """抄错一位要在**提交之前**就告诉用户，而不是等他提交完再被驳回。"""
    r = await client.post(
        "/v1/reviews/precheck",
        json={
            "kind": "entity",
            "subject": {
                "legal_name": "示例数据科技有限公司",
                "registration_no": VALID_USCC[:-1] + "X",
                "official_domain": "entity-example.test",
                "contact_email": "ops@entity-example.test",
                "service_scope": SCOPE,
            },
            "website_verified": True,
        },
        headers=H[STRANGER],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "entity"
    assert body["ok"] is False
    assert body["blocking_failures"] == ["registration_no"]


async def test_precheck_needs_no_verifier_profile(client: AsyncClient):
    """自检是给**提交人**用的，登录即可，不需要治理角色。"""
    r = await client.post(
        "/v1/reviews/precheck",
        json={
            "kind": "entity",
            "subject": {
                "legal_name": "示例数据科技有限公司",
                "registration_no": VALID_USCC,
                "official_domain": "entity-example.test",
                "contact_email": "ops@entity-example.test",
                "service_scope": SCOPE,
            },
            "website_verified": True,
        },
        headers=H[STRANGER],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["blocking_failures"] == []
    # 工商核验没接数据源，只能进人工清单
    assert body["needs_human"] == ["registry"]


async def test_precheck_merchant_and_personal(client: AsyncClient):
    r = await client.post(
        "/v1/reviews/precheck",
        json={
            "kind": "merchant",
            "subject": {
                "business_name": "老王面馆",
                "operator_name": "王大明",
                "registration_no": VALID_USCC,
                "business_scope": "餐饮服务",
                "business_address": "浙江省杭州市西湖区某路 1 号",
                "contact_email": "wang@entity-example.test",
            },
        },
        headers=H[STRANGER],
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    r = await client.post(
        "/v1/reviews/precheck",
        json={"kind": "personal", "subject": {"full_name": "张三", "contact_email": "z@entity-example.test"}},
        headers=H[STRANGER],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # 刷脸永远留给人看密文包，机器不替人下结论
    assert "face" in body["needs_human"]
