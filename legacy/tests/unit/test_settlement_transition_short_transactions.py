# -*- coding: utf-8 -*-
"""``apply_settlement_transition`` 的链上那一步必须在事务外（行锁不许跨链上等待）。

agent 下单（intent fulfillment / trade pipeline）走的就是这条路径。以前它一路不
commit：链上那一段（bind 之前两侧各读一次授权额，容器内实测 ~2s）期间，这一路在
``accept_voucher_row`` 里对 buyer 的 capacity 行做过的 UPDATE 还攥着行锁 —— 同一个
buyer 的并发下单只能一个接一个排队（2026-10-01 L1 实测第 10 单接单等 18.3s，每单 +2s）。

这两条用例钉住：

1. chain 调用之前一定先 commit（放掉所有行锁）；
2. 链上失败时业务状态退回原样 —— 界面不能声称一笔链上根本不认的结算。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, event, select

from core.schemas import SettlementState, TaskStatus
from db.models.orm import SettlementModel
from db.stores.settlement_store import PostgresSettlementStore

TASK = "task-short-transition"


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()
    yield
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()


async def _seed(db_session) -> SettlementState:
    store = PostgresSettlementStore(db_session)
    state = SettlementState(
        task_id=TASK,
        escrow_amount=30.0,
        currency="USD",
        client_agent_id="kid_buyer",
        worker_agent_id="kid_seller",
        status=TaskStatus.DRAFT,
    )
    await store.save(state)
    await db_session.flush()
    got = await store.get(TASK)
    assert got is not None
    return got


@pytest.mark.asyncio
async def test_chain_step_runs_after_the_commit(db_session, monkeypatch):
    from services import settlement_transitions as mod

    state = await _seed(db_session)
    store = PostgresSettlementStore(db_session)

    order: list[str] = []
    event.listen(db_session.sync_session, "after_commit", lambda _s: order.append("commit"))

    async def _fake_sync(*, db, state, target_status, buyer_confirmed=False):
        order.append("chain")

    monkeypatch.setattr(mod, "sync_chain_escrow_for_transition", _fake_sync)

    out = await mod.apply_settlement_transition(
        db=db_session,
        store=store,
        state=state,
        target_status=TaskStatus.PENDING,
        reason="test",
        route_path="/test",
        actor_id="tester",
    )

    assert out.status == TaskStatus.PENDING
    assert "chain" in order and "commit" in order
    assert order.index("commit") < order.index("chain"), "链上那一步还在事务里跑"


@pytest.mark.asyncio
async def test_chain_failure_rolls_the_row_back(db_session, monkeypatch):
    from services import settlement_transitions as mod

    state = await _seed(db_session)
    store = PostgresSettlementStore(db_session)

    async def _boom(*, db, state, target_status, buyer_confirmed=False):
        raise RuntimeError("chain said no")

    monkeypatch.setattr(mod, "sync_chain_escrow_for_transition", _boom)

    with pytest.raises(RuntimeError):
        await mod.apply_settlement_transition(
            db=db_session,
            store=store,
            state=state,
            target_status=TaskStatus.PENDING,
            reason="test",
            route_path="/test",
            actor_id="tester",
        )

    row = (
        await db_session.execute(
            select(SettlementModel).where(SettlementModel.task_id == TASK)
        )
    ).scalars().one()
    assert row.status == "draft", "链上失败后业务状态没退回去"

