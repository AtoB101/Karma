"""治理岗的「质押即开通 / 押金走则岗停」（L3-2）集成测试。

这一层要证明两件事，缺一不可：

1. **开通**：``GOVERNANCE_OPEN_JOIN=true`` 之后，任何身份都能凭**已锁仓的 USDC**
   开 verifier / arbitrator 岗 —— 不带质押或低于下限 422、没有锁仓背书 409；
   两条路都没开还是 403（维持原样，谁也不能自助拿审批权）；
2. **在任**：岗不是「开一次管一辈子」。每次动治理权限都拿承诺额与
   ``capacity.total_locked_usdc`` 现算一遍，押金被划走后复核入口**当场** 403 ——
   「押金在则岗在，押金走则岗停」。

白名单（``GOVERNANCE_VERIFIER_IDS``）不受质押约束：那是平台自己承担责任的岗，
不该拿用户的押金来背书，也不该因为别人的押金变动而停摆。

身份走 dev 的 ``X-Karma-Identity-Id`` 回退（AUTH 关闭时），与
tests/integration/test_identity_role_profiles.py 同一套路。
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import CapacityModel

APPLICANT = {"X-Karma-Identity-Id": "gov-applicant"}
OPERATOR = {"X-Karma-Identity-Id": "gov-ops"}
OWNER = {"X-Karma-Identity-Id": "gov-owner"}


@pytest.fixture(autouse=True)
def _closed_door(monkeypatch):
    """默认：没有白名单、也没有开放申请。每个用例自己挑走哪条路。"""
    monkeypatch.setattr(settings, "governance_verifier_ids", "")
    monkeypatch.setattr(settings, "governance_open_join", False)
    monkeypatch.setattr(settings, "governance_min_stake_amount", 0.0)
    monkeypatch.setattr(settings, "governance_require_backed_stake", True)


def _open_join(monkeypatch, *, floor: float = 100.0, backed: bool = True) -> None:
    monkeypatch.setattr(settings, "governance_open_join", True)
    monkeypatch.setattr(settings, "governance_min_stake_amount", floor)
    monkeypatch.setattr(settings, "governance_require_backed_stake", backed)


def _whitelist(monkeypatch, *identities: str) -> None:
    monkeypatch.setattr(settings, "governance_verifier_ids", ",".join(identities))


async def _lock(db: AsyncSession, identity_id: str, amount: float) -> None:
    """改「这个身份锁了多少 USDC」（capacity 是链上那本账的本地镜像）。"""
    row = await db.get(CapacityModel, identity_id)
    if row is None:
        db.add(CapacityModel(identity_id=identity_id, total_locked_usdc=amount))
    else:
        row.total_locked_usdc = amount
    await db.flush()


async def _apply(
    client: AsyncClient, *, class_: str = "verifier", who: str = "gov-applicant", **over
) -> Response:
    body = {"owner_identity_id": who, "class": class_}
    body.update(over)
    return await client.post(
        "/v1/identity/role-profiles",
        json=body,
        headers={"X-Karma-Identity-Id": who},
    )


async def _pending_kyc(client: AsyncClient, owner: str) -> str:
    """在 owner 名下造一份「待复核」的子身份 KYC，返回 profile_id。"""
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": owner, "class": "merchant", "display_name": "待核小商户"},
        headers={"X-Karma-Identity-Id": owner},
    )
    assert r.status_code == 201, r.text
    profile_id = r.json()["profile_id"]

    r = await client.post(
        f"/v1/identity/role-profiles/{profile_id}/kyc",
        json={"kyc_payload": {"doc": "passport"}},
        headers={"X-Karma-Identity-Id": owner},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kyc_status"] == "pending"
    return profile_id


async def _verify_kyc(client: AsyncClient, profile_id: str, headers: dict) -> Response:
    return await client.post(
        f"/v1/identity/role-profiles/{profile_id}/kyc/verify",
        json={"decision": "verified"},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# 开通：两条入口，一把尺子
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_door_is_still_403(client: AsyncClient):
    """两条路都没开：老规矩 —— 自助开治理岗 403，谁也不能给自己开审批权。"""
    r = await _apply(client)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_open_join_needs_a_stake(client: AsyncClient, monkeypatch):
    """开放申请 ≠ 敞开大门：不带质押、或低于平台下限，都拒。"""
    _open_join(monkeypatch, floor=100.0)

    r = await _apply(client)
    assert r.status_code == 422, r.text

    r = await _apply(client, stake_amount=50.0)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_open_join_needs_locked_backing(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """押够了下限，但那份钱没锁在链上 —— 409：质押不是一句承诺，是锁仓。"""
    _open_join(monkeypatch, floor=100.0)

    r = await _apply(client, stake_amount=100.0)
    assert r.status_code == 409, r.text

    await _lock(db_session, "gov-applicant", 90.0)          # 锁得比承诺少 —— 还是不够
    r = await _apply(client, stake_amount=100.0)
    assert r.status_code == 409, r.text

    await _lock(db_session, "gov-applicant", 100.0)         # 锁满 —— 放行
    r = await _apply(client, stake_amount=100.0)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["class"] == "verifier"
    assert body["stake_amount"] == 100.0


@pytest.mark.asyncio
async def test_arbitrator_uses_the_same_door(client: AsyncClient, monkeypatch, db_session):
    """arbitrator 也走同一扇门：同一个下限、同一份锁仓。"""
    _open_join(monkeypatch, floor=250.0)
    await _lock(db_session, "gov-applicant", 250.0)

    r = await _apply(client, class_="arbitrator", stake_amount=250.0)
    assert r.status_code == 201, r.text
    assert r.json()["class"] == "arbitrator"


@pytest.mark.asyncio
async def test_raising_stake_beyond_collateral_is_rejected_on_update(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """改质押走同一把尺子：改到超过自己的锁仓，409，而且原地不动。"""
    _open_join(monkeypatch, floor=100.0)
    await _lock(db_session, "gov-applicant", 120.0)

    r = await _apply(client, stake_amount=100.0)
    assert r.status_code == 201, r.text
    profile_id = r.json()["profile_id"]

    r = await client.put(
        f"/v1/identity/role-profiles/{profile_id}",
        json={"stake_amount": 500.0},
        headers=APPLICANT,
    )
    assert r.status_code == 409, r.text

    r = await client.get(f"/v1/identity/role-profiles/{profile_id}", headers=APPLICANT)
    assert r.status_code == 200
    assert r.json()["stake_amount"] == 100.0


@pytest.mark.asyncio
async def test_whitelisted_governor_is_not_bound_by_collateral(client: AsyncClient, monkeypatch):
    """运维点名开的岗不押金化：记 0、不看锁仓，照样能批。"""
    _whitelist(monkeypatch, "gov-ops")

    r = await _apply(client, who="gov-ops")
    assert r.status_code == 201, r.text
    assert r.json()["stake_amount"] == 0.0

    profile_id = await _pending_kyc(client, "gov-owner")
    r = await _verify_kyc(client, profile_id, OPERATOR)
    assert r.status_code == 200, r.text
    assert r.json()["kyc_status"] == "verified"



@pytest.mark.asyncio
async def test_appointed_profile_without_stake_is_not_collateral_bound(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """运维直接建档（承诺额 0）那一档跟的是名单，不是押金 —— 不会因为别人的押金归零而停摆。

    这种岗在 API 上开不出来（没质押、没白名单就是 403），只可能是平台在服务端建的，
    所以它不是一条绕开质押的后门。
    """
    from db.models.orm import IdentityRoleProfile

    _open_join(monkeypatch, floor=100.0)
    appointed = "gov-appointed-1"
    db_session.add(
        IdentityRoleProfile(
            profile_id="gov-appointed-profile",
            owner_identity_id=appointed,
            class_="verifier",
            kyc_status="verified",
            visibility="public",
            display_name="运维建档核验方",
        )
    )
    await db_session.flush()

    profile_id = await _pending_kyc(client, "gov-owner")
    r = await _verify_kyc(client, profile_id, {"X-Karma-Identity-Id": appointed})
    assert r.status_code == 200, r.text
    assert r.json()["kyc_status"] == "verified"


# ---------------------------------------------------------------------------
# 在任：押金在则岗在，押金走则岗停
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drained_collateral_stops_kyc_authority(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """本轮核心：押金被划走之后，同一个 verifier 的复核入口**当场** 403。

    不是「等运维改名单」，也不是「下次登录才失效」—— 每次动治理权限都现算，
    所以押金一走，岗就停在这一个请求上。
    """
    _open_join(monkeypatch, floor=100.0)
    await _lock(db_session, "gov-applicant", 150.0)

    r = await _apply(client, stake_amount=150.0)
    assert r.status_code == 201, r.text

    first = await _pending_kyc(client, "gov-owner")
    r = await _verify_kyc(client, first, APPLICANT)
    assert r.status_code == 200, r.text

    # 押金没了：罚没 / 解仓 / 挪用都归到这一行（capacity 是链上那本账的镜像）
    await _lock(db_session, "gov-applicant", 0.0)

    second = await _pending_kyc(client, "gov-owner")
    r = await _verify_kyc(client, second, APPLICANT)
    assert r.status_code == 403, r.text
    assert "not active" in r.json()["detail"]

    # 状态机也没往前走：这份 KYC 还是 pending，没被批掉
    r = await client.get(f"/v1/identity/role-profiles/{second}", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["kyc_status"] == "pending"


@pytest.mark.asyncio
async def test_partial_drain_below_the_promise_also_stops_the_role(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """只划走一部分、但已经低于承诺额：一样停 —— 判的是「有没有兑现承诺」，不是「还有没有钱」。"""
    _open_join(monkeypatch, floor=100.0)
    await _lock(db_session, "gov-applicant", 150.0)
    r = await _apply(client, stake_amount=150.0)
    assert r.status_code == 201, r.text

    await _lock(db_session, "gov-applicant", 149.0)
    profile_id = await _pending_kyc(client, "gov-owner")
    r = await _verify_kyc(client, profile_id, APPLICANT)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_review_queue_closes_when_collateral_is_gone(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """复核台是「人工复核」的总入口，更要跟着押金走：押金一走，别人的材料就不该再看得到。"""
    _open_join(monkeypatch, floor=100.0)
    await _lock(db_session, "gov-applicant", 100.0)
    r = await _apply(client, stake_amount=100.0)
    assert r.status_code == 201, r.text

    r = await client.get("/v1/reviews/pending", headers=APPLICANT)
    assert r.status_code == 200, r.text

    await _lock(db_session, "gov-applicant", 0.0)
    r = await client.get("/v1/reviews/pending", headers=APPLICANT)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_operator_without_stake_is_unaffected_by_other_peoples_collateral(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """白名单岗的停摆只看自己的名单，不看任何人的押金 —— 运维岗不能被用户的押金开关牵走。"""
    _whitelist(monkeypatch, "gov-ops")
    _open_join(monkeypatch, floor=100.0)

    r = await _apply(client, who="gov-ops")
    assert r.status_code == 201, r.text

    await _lock(db_session, "gov-applicant", 0.0)
    profile_id = await _pending_kyc(client, "gov-owner")
    r = await _verify_kyc(client, profile_id, OPERATOR)
    assert r.status_code == 200, r.text
