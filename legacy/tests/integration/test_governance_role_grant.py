# -*- coding: utf-8 -*-
"""治理岗的「发放给他人 / 收回」（2026-10-08 审计 G5）。

历史缺口：``services/actor_guards.require_governance_verifier`` 定义了「治理身份发放方」
这道闸门，但**全仓零调用**；``create_role_profile`` 又强制 ``actor == owner_identity_id``，
于是白名单里的人也只能给自己开岗 —— 「把 verifier / arbitrator 岗发给某个人」这条路
在代码里根本没有入口，只能运维直接改 ``.env``，收回同样没有管理动作。

这里钉住：
  1. 发放方（``GOVERNANCE_VERIFIER_IDS`` ∪ 管理员）能替他人开 verifier / arbitrator 岗；
     指令出来的岗记 0 质押（跟名单、不跟押金），被指派方收到站内回执 + 安全事件留痕；
  2. 普通人不能替他人开，也不能给自己开治理岗；发放方也不能拿这条路开非治理类别；
  3. 收回：发放方 / 管理员把档案置 ``disabled``（入口当场失效），仲裁员同时从仲裁池下架；
     普通人收回一律 403。
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import ArbitrationPoolMemberModel, ConsoleNoticeModel, IdentityRoleProfile
from services import security_monitoring as sm

ISSUER = {"X-Karma-Identity-Id": "gov-issuer"}
TARGET = {"X-Karma-Identity-Id": "gov-target"}
TARGET_ARB = {"X-Karma-Identity-Id": "gov-target-arb"}
PLAIN = {"X-Karma-Identity-Id": "gov-plain"}


@pytest.fixture(autouse=True)
def _issuer_whitelisted(monkeypatch):
    monkeypatch.setattr(settings, "governance_verifier_ids", "gov-issuer")
    monkeypatch.setattr(settings, "admin_actor_ids", "")
    monkeypatch.setattr(settings, "governance_open_join", False)


async def _grant(client: AsyncClient, *, who: str, class_: str, as_: dict):
    return await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": who, "class": class_},
        headers=as_,
    )


async def _notices(db: AsyncSession, identity: str, kind: str):
    return (
        await db.execute(
            select(ConsoleNoticeModel).where(
                ConsoleNoticeModel.karma_identity_id == identity,
                ConsoleNoticeModel.kind == kind,
            )
        )
    ).scalars().all()


def _events(profile_id: str, event_type):
    return [
        e
        for e in sm._list_recent_events(120)
        if e.event_type == event_type and e.metadata.get("profile_id") == profile_id
    ]


@pytest.mark.asyncio
async def test_issuer_can_grant_a_verifier_role_to_someone_else(client, db_session):
    r = await _grant(client, who="gov-target", class_="verifier", as_=ISSUER)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner_identity_id"] == "gov-target"
    assert body["class"] == "verifier"
    assert body["status"] == "active"
    assert body["stake_amount"] == 0.0, "指派的治理岗不占被指派人的押金"

    notices = await _notices(db_session, "gov-target", "governance_role_granted")
    assert notices, "被指派人必须收到站内回执"
    assert notices[-1].payload.get("granted_by") == "gov-issuer"

    events = _events(body["profile_id"], sm.SecurityMonitoringEventType.GOVERNANCE_ROLE_GRANTED)
    assert events, "发放治理岗必须落安全事件"
    assert events[-1].metadata["granted_by"] == "gov-issuer"


@pytest.mark.asyncio
async def test_plain_identity_cannot_grant_a_role_to_someone_else(client):
    r = await _grant(client, who="gov-target", class_="verifier", as_=PLAIN)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_plain_identity_still_cannot_open_a_governance_role_for_itself(client):
    r = await _grant(client, who="gov-plain", class_="verifier", as_=PLAIN)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_issuer_cannot_use_the_grant_path_for_ordinary_classes(client):
    """替他人开「个体户」这种普通档案仍然要本人 —— 发放方这条路只对治理岗开放。"""
    r = await _grant(client, who="gov-target", class_="individual", as_=ISSUER)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_revoke_disables_the_role_and_notifies_the_owner(client, db_session):
    created = await _grant(client, who="gov-target", class_="verifier", as_=ISSUER)
    assert created.status_code == 201, created.text
    profile_id = created.json()["profile_id"]

    denied = await client.post(
        "/v1/identity/role-profiles/%s/governance-revoke" % profile_id, headers=PLAIN
    )
    assert denied.status_code == 403, denied.text

    ok = await client.post(
        "/v1/identity/role-profiles/%s/governance-revoke" % profile_id, headers=ISSUER
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "disabled"

    row = await db_session.get(IdentityRoleProfile, profile_id)
    assert row.status == "disabled", "收回后复核台入口（按 active 判）必须立刻失效"

    assert await _notices(db_session, "gov-target", "governance_role_revoked")
    events = _events(profile_id, sm.SecurityMonitoringEventType.GOVERNANCE_ROLE_REVOKED)
    assert events, "收回治理岗必须落安全事件"
    assert events[-1].metadata["revoked_by"] == "gov-issuer"


@pytest.mark.asyncio
async def test_revoking_an_arbitrator_also_pulls_them_from_the_pool(client, db_session):
    created = await _grant(client, who="gov-target-arb", class_="arbitrator", as_=ISSUER)
    assert created.status_code == 201, created.text
    profile_id = created.json()["profile_id"]

    db_session.add(
        ArbitrationPoolMemberModel(
            arbitrator_identity_id="gov-target-arb", stake_amount=500.0, status="active"
        )
    )
    await db_session.flush()

    ok = await client.post(
        "/v1/identity/role-profiles/%s/governance-revoke" % profile_id, headers=ISSUER
    )
    assert ok.status_code == 200, ok.text

    member = await db_session.get(ArbitrationPoolMemberModel, "gov-target-arb")
    assert member.status == "inactive", "收回仲裁岗必须同时从仲裁池下架，不能再被派庭"


@pytest.mark.asyncio
async def test_ordinary_profiles_cannot_be_revoked_this_way(client):
    created = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": "gov-target", "class": "individual"},
        headers=TARGET,
    )
    assert created.status_code == 201, created.text
    r = await client.post(
        "/v1/identity/role-profiles/%s/governance-revoke" % created.json()["profile_id"],
        headers=ISSUER,
    )
    assert r.status_code == 409, r.text
