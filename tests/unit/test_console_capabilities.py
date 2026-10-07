"""操作台能力位（``/v1/console/capabilities``）的边界。

这个接口存在的唯一理由是：让前端**提前**知道要不要画「仲裁台 / 验证者网络」
这两个入口，而不是「打真接口、看到 403 再藏」—— 那样每个普通用户每开一次
操作台都会往安全告警里塞一串 403，把 ``privileged_action`` 那条基线淹掉。

所以这里钉死三件事：
1. 名单里的人拿到 true，名单外的人拿到 false；
2. 它的口径必须与 ``services/actor_guards`` 那三道 ``require_*`` 逐字一致 ——
   前端可以按照它画按钮，但**判定权威仍然在后端**（这里给错 = 画错按钮，不是放行）；
3. 没有会话就 401，绝不匿名回一份「都是 false」的结果（那会让前端以为「你没权限」
   而不是「你还没登录」）。
"""
from __future__ import annotations

import pytest

from config.settings import settings


def _keys(actor: str, secret: str = "supersecret123456") -> dict[str, str]:
    return {"X-Karma-Api-Key": "karma_%s_%s" % (actor, secret)}


@pytest.fixture
def restore_allowlists():
    """这三个白名单是进程级 settings，用完必须还原，否则污染别的用例。"""
    saved = (
        settings.auth_api_keys,
        settings.admin_actor_ids,
        settings.arbitrator_actor_ids,
        settings.governance_verifier_ids,
    )
    try:
        yield
    finally:
        (
            settings.auth_api_keys,
            settings.admin_actor_ids,
            settings.arbitrator_actor_ids,
            settings.governance_verifier_ids,
        ) = saved


@pytest.mark.asyncio
async def test_capabilities_requires_a_session(client, restore_allowlists):
    resp = await client.get("/v1/console/capabilities")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_capabilities_admin_sees_arbitration_and_verifier_network(
    client, restore_allowlists
):
    settings.auth_api_keys = "caps-admin:supersecret123456"
    settings.admin_actor_ids = "caps-admin"
    settings.arbitrator_actor_ids = ""
    settings.governance_verifier_ids = ""

    resp = await client.get("/v1/console/capabilities", headers=_keys("caps-admin"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["actor_id"] == "caps-admin"
    assert body["is_admin"] is True
    # 管理员按 require_arbitration_operator 的口径也能派庭/执行裁决。
    assert body["can_operate_arbitration"] is True
    assert body["can_view_verifier_network"] is True
    # 但「治理发放方」是另一个岗，管理员不隐含它。
    assert body["is_governance_verifier"] is False
    # 复核台跟的是 verifier 类档案，不跟管理员白名单：没档案就是 False。
    assert body["can_open_review_queue"] is False


@pytest.mark.asyncio
async def test_capabilities_arbitrator_does_not_get_admin_or_verifier_network(
    client, restore_allowlists
):
    """仲裁员能裁案，但开不了刹车、也看不到验证者网络入口 —— 岗与岗互不隐含。"""
    settings.auth_api_keys = "caps-arb:supersecret123456"
    settings.admin_actor_ids = ""
    settings.arbitrator_actor_ids = "caps-arb"
    settings.governance_verifier_ids = ""

    resp = await client.get("/v1/console/capabilities", headers=_keys("caps-arb"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_arbitrator"] is True
    assert body["can_operate_arbitration"] is True
    assert body["is_admin"] is False
    assert body["can_view_verifier_network"] is False
    assert body["can_open_review_queue"] is False


@pytest.mark.asyncio
async def test_capabilities_governance_verifier_sees_verifier_network(
    client, restore_allowlists
):
    settings.auth_api_keys = "caps-gov:supersecret123456"
    settings.admin_actor_ids = ""
    settings.arbitrator_actor_ids = ""
    settings.governance_verifier_ids = "caps-gov"

    resp = await client.get("/v1/console/capabilities", headers=_keys("caps-gov"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_governance_verifier"] is True
    assert body["can_view_verifier_network"] is True
    assert body["can_operate_arbitration"] is False
    # 治理发放方也不等于复核档案：复核台看的是 verifier 类档案。
    assert body["can_open_review_queue"] is False


@pytest.mark.asyncio
async def test_capabilities_plain_identity_gets_nothing_but_is_still_200(
    client, restore_allowlists
):
    """普通身份拿到的是「都是 false」的 200，不是 403。

    403 会被安全告警当成「有人摸特权接口」；这里必须是安静的 false。
    """
    settings.auth_api_keys = "caps-plain:supersecret123456"
    settings.admin_actor_ids = ""
    settings.arbitrator_actor_ids = ""
    settings.governance_verifier_ids = ""

    resp = await client.get("/v1/console/capabilities", headers=_keys("caps-plain"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["actor_id"] == "caps-plain"
    for flag in (
        "is_admin",
        "is_arbitrator",
        "can_operate_arbitration",
        "is_governance_verifier",
        "can_view_verifier_network",
        "can_open_review_queue",
    ):
        assert body[flag] is False, flag


@pytest.mark.asyncio
async def test_capabilities_flags_match_actor_guards_allowlists(client, restore_allowlists):
    """口径一致性：能力位 true 的 actor，过 require_* 必须不 403。

    这条是防漂移的 —— 以后谁改了白名单口径却忘了改这里，这条会先红。
    """
    settings.auth_api_keys = "caps-drift:supersecret123456"
    settings.admin_actor_ids = "caps-drift"
    settings.arbitrator_actor_ids = ""
    settings.governance_verifier_ids = "caps-drift"

    caps = (await client.get("/v1/console/capabilities", headers=_keys("caps-drift"))).json()
    assert caps["can_operate_arbitration"] is True

    # 真接口：管理员能读仲裁运维报表（require_admin_actor）。
    report = await client.get("/v1/arbitration/cases/ops/report", headers=_keys("caps-drift"))
    assert report.status_code == 200, report.text



@pytest.mark.asyncio
async def test_capabilities_review_queue_follows_the_verifier_profile(
    client, db_session, restore_allowlists
):
    """复核台入口跟的是 verifier 类档案，不是白名单 —— 口径与 _require_verifier 一致。

    白名单里的人也得先有档案；反之只要档案在任，入口就得画。
    这里连真接口一起钉：画了按钮就必须真的能进去。
    """
    from db.models.orm import IdentityRoleProfile

    settings.auth_api_keys = "caps-rev:supersecret123456"
    settings.admin_actor_ids = ""
    settings.arbitrator_actor_ids = ""
    settings.governance_verifier_ids = ""

    caps = (await client.get("/v1/console/capabilities", headers=_keys("caps-rev"))).json()
    assert caps["can_open_review_queue"] is False

    db_session.add(
        IdentityRoleProfile(
            profile_id="irp_caps_rev",
            owner_identity_id="caps-rev",
            class_="verifier",
            status="active",
            stake_amount=0.0,
        )
    )
    await db_session.commit()

    caps = (await client.get("/v1/console/capabilities", headers=_keys("caps-rev"))).json()
    assert caps["can_open_review_queue"] is True

    resp = await client.get("/v1/reviews/pending", headers=_keys("caps-rev"))
    assert resp.status_code == 200, resp.text
