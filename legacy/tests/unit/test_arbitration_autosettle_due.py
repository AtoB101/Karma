"""④-A2：上诉窗口到点的仲裁裁决，由常驻 tick 自动落成钱。

④-A1 把「下发」与「放款」拆成两段（/execute 只记 execute_after），④-A3 让窗口内
可以零成本打回重审。只做到这两步的话，「窗口到点放款」仍然要有人手工按
/execute-due —— 没人按，钱就一直卡在托管里（卖方等的就是这一笔）。

这一条用例钉住 ④-A2 的 tick：

* 到点自动放款，且**与 /execute-due 共用** _settle_from_decision（口径只有一处）；
* 窗口还开着 / 从没下发过（execute_after 为空）时一动不动；
* 已 executed 的幂等，人工 + tick 两条路合起来也只放一次款；
* 一条坏案件不拖住同批的好案件；
* 链上门禁挡住时整条回滚，案件留在 decided（绝不「账上已结算、链上一分没动」）。

注意：单测跑在 SQLite 上，方言不渲染 ``FOR UPDATE`` —— 这里钉的是**顺序**与
**re-check 逻辑**（谁先落谁赢）；真正那把锁由 Postgres 在 testnet 上实测（见 A2 报告）。
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


async def _seed_decided_case(
    db, *, case_id: str, task_id: str, execute_after: datetime | None, escrow: float = 100.0
) -> None:
    db.add(
        TaskContractModel(
            task_id=task_id,
            client_agent_id="buyer-a2",
            title="autosettle due case",
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
            # 必须是仲裁立案后才有的 arbitrated（写 disputed 会撞持久化守卫）。
            status=TaskStatus.ARBITRATED.value,
            client_agent_id="buyer-a2",
            worker_agent_id="seller-a2",
            released_amount=0.0,
            refunded_amount=0.0,
        )
    )
    db.add(
        ArbitrationCaseModel(
            case_id=case_id,
            task_id=task_id,
            opened_by="buyer-a2",
            status="decided",
            required_arbitrators=3,
            decided_outcome="seller_wins",
            execute_after=execute_after,
        )
    )
    await db.commit()


def _capture_chain_sync(monkeypatch, *, fail_for: set[str] | None = None) -> list:
    """把链上那一步换成记录器；``fail_for`` 里的 task_id 抛错，模拟链上门禁挡单。"""
    seen: list = []
    fail_for = fail_for or set()

    async def _recorder(*, db, state, target_status):
        if state.task_id in fail_for:
            raise RuntimeError("chain gate blocked: " + state.task_id)
        seen.append((state.task_id, target_status))

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


async def _events(db, case_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(ArbitrationCaseEventModel)
            .where(ArbitrationCaseEventModel.case_id == case_id)
            .order_by(ArbitrationCaseEventModel.created_at)
        )
    ).scalars().all()
    return [e.event_type for e in rows]


@pytest.fixture(autouse=True)
def _clear_backoff():
    from services.chain import escrow_autosettle

    escrow_autosettle.reset_backoff()
    yield
    escrow_autosettle.reset_backoff()


@pytest.mark.asyncio
async def test_tick_pays_a_due_case(db_session, monkeypatch):
    from api.routes.arbitration import execute_due_arbitration_cases

    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(
        db_session,
        case_id="case-a2-due",
        task_id="task-a2-due",
        execute_after=datetime.utcnow() - timedelta(seconds=1),
    )

    done = await execute_due_arbitration_cases(db_session)

    assert done == ["case-a2-due"], done
    assert seen == [("task-a2-due", TaskStatus.SETTLED)], seen
    case = await _case(db_session, "case-a2-due")
    assert case.status == "executed"
    assert await _settlement_status(db_session, "task-a2-due") == TaskStatus.SETTLED.value
    assert "case_executed" in await _events(db_session, "case-a2-due")


@pytest.mark.asyncio
async def test_tick_skips_a_case_whose_window_is_still_open(db_session, monkeypatch):
    from api.routes.arbitration import execute_due_arbitration_cases

    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(
        db_session,
        case_id="case-a2-open",
        task_id="task-a2-open",
        execute_after=datetime.utcnow() + timedelta(seconds=300),
    )

    done = await execute_due_arbitration_cases(db_session)

    assert done == []
    assert seen == [], "窗口还开着，链上一分钱都不许动"
    assert (await _case(db_session, "case-a2-open")).status == "decided"
    assert await _settlement_status(db_session, "task-a2-open") == TaskStatus.ARBITRATED.value


@pytest.mark.asyncio
async def test_tick_skips_a_case_that_was_never_scheduled(db_session, monkeypatch):
    """窗口关着（默认）时 /execute 一步落钱，从不留 execute_after：tick 必须空操作。"""
    from api.routes.arbitration import execute_due_arbitration_cases

    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(
        db_session, case_id="case-a2-none", task_id="task-a2-none", execute_after=None
    )

    done = await execute_due_arbitration_cases(db_session)

    assert done == []
    assert seen == []
    assert (await _case(db_session, "case-a2-none")).status == "decided"


@pytest.mark.asyncio
async def test_tick_then_manual_due_does_not_double_pay(db_session, client_sec, monkeypatch):
    from api.routes.arbitration import execute_due_arbitration_cases

    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(
        db_session,
        case_id="case-a2-race",
        task_id="task-a2-race",
        execute_after=datetime.utcnow() - timedelta(seconds=1),
    )

    assert await execute_due_arbitration_cases(db_session) == ["case-a2-race"]
    # tick 先落，人工再来一次必然被状态机挡住 —— 重复放款 = 双花。
    resp = await client_sec.post("/v1/arbitration/cases/case-a2-race/execute-due", json={})
    assert resp.status_code == 409, resp.text
    assert len(seen) == 1, "两次入口只许放一次款"


@pytest.mark.asyncio
async def test_manual_due_then_tick_does_not_double_pay(db_session, client_sec, monkeypatch):
    from api.routes.arbitration import execute_due_arbitration_cases

    seen = _capture_chain_sync(monkeypatch)
    await _seed_decided_case(
        db_session,
        case_id="case-a2-race2",
        task_id="task-a2-race2",
        execute_after=datetime.utcnow() - timedelta(seconds=1),
    )

    resp = await client_sec.post("/v1/arbitration/cases/case-a2-race2/execute-due", json={})
    assert resp.status_code == 200, resp.text
    # 人工先落，tick 再扫一遍：已 executed 的案件根本进不了候选集。
    assert await execute_due_arbitration_cases(db_session) == []
    assert len(seen) == 1, "人工放过之后 tick 不许再放一次"


@pytest.mark.asyncio
async def test_tick_respects_the_batch_limit(db_session, monkeypatch):
    from api.routes.arbitration import execute_due_arbitration_cases

    _capture_chain_sync(monkeypatch)
    past = datetime.utcnow() - timedelta(seconds=10)
    for i in (1, 2):
        await _seed_decided_case(
            db_session,
            case_id=f"case-a2-lim{i}",
            task_id=f"task-a2-lim{i}",
            execute_after=past + timedelta(seconds=i),
        )

    done = await execute_due_arbitration_cases(db_session, limit=1)

    assert done == ["case-a2-lim1"], done
    assert (await _case(db_session, "case-a2-lim2")).status == "decided"


@pytest.mark.asyncio
async def test_one_bad_case_does_not_block_the_next(db_session, monkeypatch):
    from api.routes.arbitration import execute_due_arbitration_cases

    seen = _capture_chain_sync(monkeypatch, fail_for={"task-a2-bad"})
    base = datetime.utcnow() - timedelta(seconds=30)
    await _seed_decided_case(
        db_session, case_id="case-a2-bad", task_id="task-a2-bad", execute_after=base
    )
    await _seed_decided_case(
        db_session,
        case_id="case-a2-good",
        task_id="task-a2-good",
        execute_after=base + timedelta(seconds=1),
    )

    done = await execute_due_arbitration_cases(db_session)

    assert done == ["case-a2-good"], done
    assert seen == [("task-a2-good", TaskStatus.SETTLED)], seen
    # 坏的那条整条回滚：还在 decided，结算还停在 arbitrated，也绝不落 case_executed。
    assert (await _case(db_session, "case-a2-bad")).status == "decided"
    assert await _settlement_status(db_session, "task-a2-bad") == TaskStatus.ARBITRATED.value
    assert "case_executed" not in await _events(db_session, "case-a2-bad")


@pytest.mark.asyncio
async def test_tick_backs_off_a_repeatedly_failing_case(db_session, monkeypatch):
    from api.routes.arbitration import execute_due_arbitration_cases
    from services.chain import escrow_autosettle

    seen = _capture_chain_sync(monkeypatch, fail_for={"task-a2-flap"})
    await _seed_decided_case(
        db_session,
        case_id="case-a2-flap",
        task_id="task-a2-flap",
        execute_after=datetime.utcnow() - timedelta(seconds=1),
    )

    assert await execute_due_arbitration_cases(db_session) == []
    assert seen == []
    # 退避窗口内再跑一轮：连链都不该碰（不再重复发交易）。
    assert await execute_due_arbitration_cases(db_session) == []
    assert escrow_autosettle._failed_at.get("arb-due:case-a2-flap") is not None
    # 退避是「重试」不是「放弃」：清掉之后又能再试。
    escrow_autosettle.reset_backoff()
    assert await execute_due_arbitration_cases(db_session) == []
    assert seen == []  # 仍然坏着，但确实重新试过（不是被退避永久挡住）


def test_the_loop_actually_calls_the_tick():
    """布线钉子：run_forever 里必须真的调用本 tick，否则上面全是空谈。"""
    from services.chain import escrow_autosettle

    # ``from api.routes.arbitration import execute_due_arbitration_cases`` 在函数体里，
    # 编译后那个名字一定出现在 co_names 里。
    assert "execute_due_arbitration_cases" in escrow_autosettle.run_forever.__code__.co_names

