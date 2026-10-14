"""④-A 上诉窗口：裁决「下发」与「放款」拆两段。

链上没有「把钱倒回来」的原语（见 docs/ARBITRATION_SETTLEMENT_REVERSAL.md），
所以「被推翻要退钱」只能提前拦：窗口内**链上一笔不发、钱一步不动**，
推翻零成本；到点才由 /execute-due 落钱。

这条用例钉住四件事：

* 窗口**关着**（默认）时，/execute 与历史行为一致 —— 立刻落钱；
* 窗口**打开**时，/execute 只记 execute_after，链上零动作、结算仍是 disputed；
* 时间闸在服务端判 —— 窗口没到，/execute-due 一律 409（谁调都一样）；
* 到点后 /execute-due 落钱，且与 /execute 共用同一条落钱路径。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from core.schemas import TaskStatus
from db.models.orm import (
    ArbitrationCaseEventModel,
    ArbitrationCaseModel,
    SettlementModel,
    TaskContractModel,
)


async def _seed_decided_case(db, *, case_id: str, task_id: str, escrow: float = 100.0) -> None:
    db.add(
        TaskContractModel(
            task_id=task_id,
            client_agent_id="buyer-a1",
            title="appeal window case",
            description="d",
            expected_output_schema={},
            expected_step_count=1,
            escrow_amount=escrow,
            deadline_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    db.add(
        SettlementModel(
            settlement_id="settle-" + task_id,
            task_id=task_id,
            escrow_amount=escrow,
            currency="USD",
            # 注意：settlement 必须是 disputed→仲裁立案后才有的 arbitrated，
            # 见 api/routes/arbitration.py:220-238；写 disputed 会撞持久化守卫。
            status=TaskStatus.ARBITRATED.value,
            client_agent_id="buyer-a1",
            worker_agent_id="seller-a1",
            released_amount=0.0,
            refunded_amount=0.0,
        )
    )
    db.add(
        ArbitrationCaseModel(
            case_id=case_id,
            task_id=task_id,
            opened_by="buyer-a1",
            status="decided",
            required_arbitrators=3,
            decided_outcome="seller_wins",
        )
    )
    await db.commit()


def _capture_chain_sync(monkeypatch) -> list:
    """把链上那一步换成记录器 —— 这一层只考「有没有走到动钱那一步」。"""
    seen: list = []

    async def _recorder(*, db, state, target_status):
        seen.append(target_status)

    import api.routes.settlement as settlement_routes

    monkeypatch.setattr(settlement_routes, "_sync_escrow_settlement", _recorder)
    return seen


async def _case(db, case_id: str) -> ArbitrationCaseModel:
    return (
        await db.execute(select(ArbitrationCaseModel).where(ArbitrationCaseModel.case_id == case_id))
    ).scalars().one()


async def _settlement_status(db, task_id: str) -> str:
    row = (
        await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    ).scalars().one()
    return row.status


@pytest.mark.asyncio
async def test_window_off_executes_immediately(client_sec, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 0)
    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(db_session, case_id="case-a1-off", task_id="task-a1-off")

    resp = await client_sec.post("/v1/arbitration/cases/case-a1-off/execute", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == TaskStatus.SETTLED.value
    assert seen == [TaskStatus.SETTLED], seen

    case = await _case(db_session, "case-a1-off")
    assert case.status == "executed"
    assert case.execute_after is None, "窗口关着就不该留下到期时刻"


@pytest.mark.asyncio
async def test_window_on_defers_payout_and_touches_no_chain(client_sec, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(db_session, case_id="case-a1-on", task_id="task-a1-on")

    before = datetime.utcnow()
    resp = await client_sec.post("/v1/arbitration/cases/case-a1-on/execute", json={})
    assert resp.status_code == 200, resp.text

    # 关键：链上一步没走，结算一分钱没动。
    assert seen == [], "窗口内不许碰链"
    assert resp.json()["status"] == TaskStatus.ARBITRATED.value
    assert await _settlement_status(db_session, "task-a1-on") == TaskStatus.ARBITRATED.value

    case = await _case(db_session, "case-a1-on")
    assert case.status == "decided", "还没放款，案件不能算 executed"
    assert case.execute_after is not None
    assert case.execute_after >= before + timedelta(seconds=299)
    assert case.execute_after <= datetime.utcnow() + timedelta(seconds=300)

    events = (
        await db_session.execute(
            select(ArbitrationCaseEventModel).where(
                ArbitrationCaseEventModel.case_id == "case-a1-on"
            )
        )
    ).scalars().all()
    assert [e.event_type for e in events] == ["case_execute_scheduled"]


@pytest.mark.asyncio
async def test_window_on_repeat_execute_does_not_push_the_deadline(client_sec, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    _capture_chain_sync(monkeypatch)
    await _seed_decided_case(db_session, case_id="case-a1-idem", task_id="task-a1-idem")

    assert (
        await client_sec.post("/v1/arbitration/cases/case-a1-idem/execute", json={})
    ).status_code == 200
    first = (await _case(db_session, "case-a1-idem")).execute_after
    assert (
        await client_sec.post("/v1/arbitration/cases/case-a1-idem/execute", json={})
    ).status_code == 200
    assert (await _case(db_session, "case-a1-idem")).execute_after == first, (
        "重复下发不许把到期时刻往后推 —— 否则多调一次卖方就多等一轮"
    )


@pytest.mark.asyncio
async def test_due_before_the_window_closes_is_rejected(client_sec, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(db_session, case_id="case-a1-early", task_id="task-a1-early")
    await client_sec.post("/v1/arbitration/cases/case-a1-early/execute", json={})

    resp = await client_sec.post("/v1/arbitration/cases/case-a1-early/execute-due", json={})
    assert resp.status_code == 409, resp.text
    assert seen == [], "窗口没到，一分钱都不许动"
    assert (await _case(db_session, "case-a1-early")).status == "decided"


@pytest.mark.asyncio
async def test_due_after_the_window_runs_the_payout(client_sec, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(db_session, case_id="case-a1-due", task_id="task-a1-due")
    await client_sec.post("/v1/arbitration/cases/case-a1-due/execute", json={})

    # 把到期时刻挪到过去 = 窗口已过（测试里不能真等 300 秒）。
    row = await _case(db_session, "case-a1-due")
    row.execute_after = datetime.utcnow() - timedelta(seconds=1)
    await db_session.commit()

    resp = await client_sec.post("/v1/arbitration/cases/case-a1-due/execute-due", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == TaskStatus.SETTLED.value
    assert seen == [TaskStatus.SETTLED], seen
    assert (await _case(db_session, "case-a1-due")).status == "executed"


@pytest.mark.asyncio
async def test_due_on_an_already_executed_case_is_rejected(client_sec, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 0)
    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(db_session, case_id="case-a1-done", task_id="task-a1-done")
    await client_sec.post("/v1/arbitration/cases/case-a1-done/execute", json={})
    assert seen == [TaskStatus.SETTLED]

    resp = await client_sec.post("/v1/arbitration/cases/case-a1-done/execute-due", json={})
    assert resp.status_code == 409, resp.text
    assert seen == [TaskStatus.SETTLED], "第二次不许再放一次款（重复放款 = 双花）"


@pytest.mark.asyncio
async def test_due_is_operator_only(client_sec, db_session, monkeypatch):
    """两个入口都是运维岗：没登录/坏 key 401、登录但不在白名单 403。

    窗口把「放款」拆成了第二个入口，闸门必须跟着拆 —— 否则新入口就是一条
    绕过 ``require_arbitration_operator`` 的后门。
    """
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    monkeypatch.setattr(
        settings,
        "auth_api_keys",
        "sec-route-default:sec-route-default-secret-abcdef12,"
        "a1-outsider:a1-outsider-secret-abcdef12",
    )
    _capture_chain_sync(monkeypatch)
    await _seed_decided_case(db_session, case_id="case-a1-auth", task_id="task-a1-auth")

    # 有 key、登录了，但既不是仲裁员也不是管理员 -> 403
    outsider = await client_sec.post(
        "/v1/arbitration/cases/case-a1-auth/execute-due",
        json={},
        headers={"X-Karma-Api-Key": "karma_a1-outsider_a1-outsider-secret-abcdef12"},
    )
    assert outsider.status_code == 403, outsider.text

    # key 对不上 -> 401
    bogus = await client_sec.post(
        "/v1/arbitration/cases/case-a1-auth/execute-due",
        json={},
        headers={"X-Karma-Api-Key": "karma_nobody_not-a-real-key"},
    )
    assert bogus.status_code == 401, bogus.text

    assert (await _case(db_session, "case-a1-auth")).status == "decided"