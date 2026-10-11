"""G12 同期项：仲裁员「被推翻」罚没闭环。

``ARBITRATION_SLASH_MULTIPLE``（默认 2×立案费）此前只是一条 policy ——
``economy-policy`` 接口把它展示给用户，但没有任何入口去执行它。整庭判错被推翻
= 换个人再判一次，判错的人零成本。这条用例考的是「有后果」：

* 在庭且有质押承诺的仲裁员被按 立案费 × 倍数 罚没（上限是其承诺额）；
* 承诺额当场下调 —— 押金走则岗停；
* 台账按 80/20 分账、按来源幂等；
* 白名单档（没有质押承诺）不罚，也不凭空造债；
* 非执行态的案件不许推翻。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from db.models.orm import (
    ArbitrationAssignmentModel,
    ArbitrationCaseModel,
    IdentityRoleProfile,
    TaskContractModel,
)
from decentralized_verifier.models import BondSlash


async def _seed_executed_case(db, *, case_id: str, task_id: str, case_value: float = 100.0):
    db.add(
        TaskContractModel(
            task_id=task_id,
            client_agent_id="buyer-agent",
            title="g12 overturn case",
            description="d",
            expected_output_schema={},
            expected_step_count=1,
            escrow_amount=case_value,
            deadline_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    db.add(
        ArbitrationCaseModel(
            case_id=case_id,
            task_id=task_id,
            opened_by="buyer-agent",
            status="executed",
            required_arbitrators=3,
            decided_outcome="buyer_wins",
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_overturn_slashes_the_bench_by_fee_multiple(client_sec, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_slash_multiple", 2.0)
    monkeypatch.setattr(settings, "arbitration_fee_bps", 150.0)
    monkeypatch.setattr(settings, "arbitration_fee_min_usdc", 0.5)
    monkeypatch.setattr(settings, "arbitration_fee_max_usdc", 100.0)

    await _seed_executed_case(db_session, case_id="case-g12-1", task_id="task-g12-1")
    db_session.add(
        ArbitrationAssignmentModel(case_id="case-g12-1", arbitrator_identity_id="arb-staked")
    )
    db_session.add(
        ArbitrationAssignmentModel(case_id="case-g12-1", arbitrator_identity_id="arb-nostake")
    )
    db_session.add(
        IdentityRoleProfile(
            owner_identity_id="arb-staked",
            class_="arbitrator",
            kyc_status="verified",
            stake_amount=10.0,
        )
    )
    await db_session.commit()

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-g12-1/overturn",
        json={"reason": "appeal upheld: the bench misread the evidence"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 案值 100 × 150bps = 1.5 立案费；×2 = 3.0 每人。
    assert body["case_fee_usdc"] == 1.5
    assert body["per_arbitrator_usdc"] == 3.0
    assert body["slashed_arbitrators"] == 1
    assert body["skipped_unstaked"] == 1, "a whitelist bench member has no bond to slash"
    assert body["settlement_reversal"] == "not_performed"

    profile = (
        await db_session.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == "arb-staked"
            )
        )
    ).scalars().first()
    assert profile.stake_amount == 7.0, "committed stake drops → role fails the next active check"

    rows = (await db_session.execute(select(BondSlash))).scalars().all()
    assert len(rows) == 1
    assert rows[0].subject_kind == "arbitrator_role"
    assert rows[0].subject_id == "arb-staked"
    assert rows[0].amount == 3.0
    assert rows[0].victim_amount == 0.0, "no victim wallet supplied → the whole slash stays in the pool"
    assert rows[0].pool_amount == 3.0
    assert rows[0].status == "pending"


@pytest.mark.asyncio
async def test_overturn_caps_at_committed_stake(client_sec, db_session):
    await _seed_executed_case(db_session, case_id="case-g12-2", task_id="task-g12-2", case_value=100000.0)
    db_session.add(
        ArbitrationAssignmentModel(case_id="case-g12-2", arbitrator_identity_id="arb-thin")
    )
    db_session.add(
        IdentityRoleProfile(
            owner_identity_id="arb-thin",
            class_="arbitrator",
            kyc_status="verified",
            stake_amount=2.0,
        )
    )
    await db_session.commit()

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-g12-2/overturn",
        json={"reason": "bench reversed", "slash_amount": 999.0},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["slashed_arbitrators"] == 1

    rows = (await db_session.execute(select(BondSlash))).scalars().all()
    assert rows[0].amount == 2.0, "never slash more than the arbitrator actually committed"

    profile = (
        await db_session.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == "arb-thin"
            )
        )
    ).scalars().first()
    assert profile.stake_amount == 0.0


@pytest.mark.asyncio
async def test_overturn_requires_executed_case(client_sec, db_session):
    await _seed_executed_case(db_session, case_id="case-g12-3", task_id="task-g12-3")
    case_row = await db_session.get(ArbitrationCaseModel, "case-g12-3")
    case_row.status = "voting"
    await db_session.commit()

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-g12-3/overturn",
        json={"reason": "not executed yet"},
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_overturn_requires_operator(client, db_session):
    await _seed_executed_case(db_session, case_id="case-g12-4", task_id="task-g12-4")

    resp = await client.post(
        "/v1/arbitration/cases/case-g12-4/overturn",
        json={"reason": "no credentials"},
    )
    assert resp.status_code in (401, 403), resp.text
