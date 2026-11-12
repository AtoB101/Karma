# -*- coding: utf-8 -*-
"""autosettle 的每一步各自结事务 —— 行锁不许跨步（死锁根因之二）。

2026-09-30 的并发压测里 Postgres 报 deadlock detected。环上有几条边都是
autosettle 自己拉出来的：

* ``reap_stranded`` 一条绑定一个事务，可它偏偏在 ``for`` 里一路 ``await`` 到循环
  结束才 ``commit`` —— 中途那一步要等链上回执（Sepolia 上 40~100s），
  ``settlements`` / ``escrow_bindings`` 的行锁一直不放；
* ``bind_due`` 的补绑跑在 ``FOR UPDATE`` 里，等链上回执的时候那个行锁也攥着，
  下一笔接着用同一条连接；
* ``run_forever`` 的 ``_lap`` 只在最末尾 commit 一次，于是上一步拿到的锁全被
  下一步继承。

修法就一条：每条绑定 / 每一步自己结事务。这里钉住它。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete

from db.models.orm import EscrowBindingModel, SettlementModel


def _binding(binding_id: str, *, task_id: str, age_seconds: int = 600) -> EscrowBindingModel:
    return EscrowBindingModel(
        binding_id=binding_id,
        buyer_identity_id="kid_buyer",
        seller_identity_id="kid_seller",
        buyer_bill_id="1",
        seller_bill_id="2",
        scope_hash="0x" + "00" * 32,
        task_id=task_id,
        amount_usdc=4.0,
        stake_usdc=1.2,
        state="active",
        created_at=datetime.utcnow() - timedelta(seconds=age_seconds),
    )


def _settlement(status: str, *, task_id: str) -> SettlementModel:
    return SettlementModel(
        settlement_id="stl-" + task_id,
        task_id=task_id,
        escrow_amount=4.0,
        currency="USD",
        status=status,
        client_agent_id="kid_buyer",
        worker_agent_id="kid_seller",
    )


def _pending(task_id: str) -> SettlementModel:
    return SettlementModel(
        settlement_id="stl-" + task_id,
        task_id=task_id,
        escrow_amount=30.0,
        currency="USD",
        status="accepted",
        client_agent_id="kid_buyer",
        worker_agent_id="kid_seller",
        settlement_mode="escrow_allowance",
        onchain_status="pending_bind",
    )


class _CommitSpy:
    """把 commit 数出来，顺便记事件顺序（动作 -> commit）。"""

    def __init__(self, session) -> None:
        # 先把原来那个 bound method 攥在手里：否则 __call__ 里再调 session.commit
        # 会调回自己（无限递归）。
        self._original = session.commit
        self.count = 0
        self.events: list[str] = []

    async def __call__(self) -> None:
        self.count += 1
        self.events.append("commit")
        await self._original()


def _every_action_is_followed_by_a_commit(events: list[str]) -> bool:
    for idx, ev in enumerate(events):
        if ev == "commit":
            continue
        if idx + 1 >= len(events) or events[idx + 1] != "commit":
            return False
    return True


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(
        delete(SettlementModel).where(SettlementModel.task_id.like("task-short%"))
    )
    await db_session.commit()
    yield
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(
        delete(SettlementModel).where(SettlementModel.task_id.like("task-short%"))
    )
    await db_session.commit()


@pytest.fixture
def armed(monkeypatch):
    from services.chain import escrow_autosettle as mod

    mod.reset_backoff()

    async def _noop_sync(db, identity_id):
        return []

    monkeypatch.setattr(mod.escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(mod.escrow, "can_server_settle", lambda: True)
    monkeypatch.setattr(mod.escrow, "sync_commits", _noop_sync)
    # 链上读不到（对账只在真读到落定状态时才改写台账）
    monkeypatch.setattr(mod.escrow, "binding_state", lambda *, binding_id, **kw: None)
    yield mod
    mod.reset_backoff()


# ---------------------------------------------------------------- reap_stranded

@pytest.mark.asyncio
async def test_reap_stranded_commits_once_per_row(db_session, armed, monkeypatch):
    """每解开一条绑定就结一次事务：链上那一步等回执时，行锁已经不在了。"""
    db_session.add_all([
        _binding("1", task_id="task-short-cancel", age_seconds=600),
        _binding("2", task_id="task-short-refund", age_seconds=500),
        _binding("3", task_id="task-short-settled", age_seconds=400),
    ])
    db_session.add_all([
        _settlement("cancelled", task_id="task-short-cancel"),
        _settlement("refunded", task_id="task-short-refund"),
        _settlement("settled", task_id="task-short-settled"),
    ])
    await db_session.commit()

    spy = _CommitSpy(db_session)
    monkeypatch.setattr(db_session, "commit", spy)

    async def _cancel(db, *, task_id):
        spy.events.append("cancel:" + task_id)
        return {"status": "cancelled"}

    async def _slash(db, *, task_id):
        spy.events.append("slash:" + task_id)
        return {"status": "breaching"}

    async def _submit(db, *, task_id, released_amount=None):
        spy.events.append("submit:" + task_id)
        return {"status": "finalizing"}

    monkeypatch.setattr(armed.escrow_settlement, "cancel_for_task", _cancel)
    monkeypatch.setattr(armed.escrow_settlement, "slash_for_task", _slash)
    monkeypatch.setattr(armed.escrow_settlement, "submit_for_task", _submit)

    freed = await armed.reap_stranded(db_session)

    assert len(freed) == 3
    assert spy.count >= 3, "三条绑定至少要三次 commit"
    assert _every_action_is_followed_by_a_commit(spy.events), spy.events
    assert spy.events == [
        "cancel:task-short-cancel", "commit",
        "slash:task-short-refund", "commit",
        "submit:task-short-settled", "commit",
    ]


@pytest.mark.asyncio
async def test_reap_stranded_commits_after_a_failed_row(db_session, armed, monkeypatch):
    """坏一笔也要结事务：那个行锁不该被下一条继承。"""
    db_session.add_all([
        _binding("10", task_id="task-short-boom", age_seconds=600),
        _binding("11", task_id="task-short-ok", age_seconds=500),
    ])
    db_session.add_all([
        _settlement("cancelled", task_id="task-short-boom"),
        _settlement("cancelled", task_id="task-short-ok"),
    ])
    await db_session.commit()

    spy = _CommitSpy(db_session)
    monkeypatch.setattr(db_session, "commit", spy)

    async def _cancel(db, *, task_id):
        spy.events.append("cancel:" + task_id)
        if task_id.endswith("boom"):
            raise RuntimeError("rpc hiccup")
        return {"status": "cancelled"}

    monkeypatch.setattr(armed.escrow_settlement, "cancel_for_task", _cancel)

    freed = await armed.reap_stranded(db_session)

    assert [f["binding_id"] for f in freed] == ["11"]
    assert spy.events == [
        "cancel:task-short-boom", "commit",
        "cancel:task-short-ok", "commit",
    ]


# -------------------------------------------------------------------- bind_due

@pytest.mark.asyncio
async def test_bind_due_commits_after_every_row(db_session, armed, monkeypatch):
    """补绑一笔就结一次事务：FOR UPDATE 等链上回执的行锁不带给下一笔。"""
    db_session.add_all([_pending("task-short-bind-1"), _pending("task-short-bind-2")])
    await db_session.commit()

    spy = _CommitSpy(db_session)
    monkeypatch.setattr(db_session, "commit", spy)

    async def _fake(db, *, task_id):
        spy.events.append("bind:" + task_id)
        return {"status": "bound", "binding_id": "9", "amount_usdc": 30.0}

    monkeypatch.setattr(armed.escrow_settlement, "materialize_pending_bind", _fake)

    out = await armed.bind_due(db_session)

    assert [o["task_id"] for o in out] == ["task-short-bind-1", "task-short-bind-2"]
    assert spy.count >= 2
    assert spy.events == [
        "bind:task-short-bind-1", "commit",
        "bind:task-short-bind-2", "commit",
    ]


@pytest.mark.asyncio
async def test_bind_due_commits_after_a_failed_row(db_session, armed, monkeypatch):
    """补绑失败也要结事务（原实现只在成功那条 commit 一次）。"""
    db_session.add_all([_pending("task-short-bind-boom"), _pending("task-short-bind-fine")])
    await db_session.commit()

    spy = _CommitSpy(db_session)
    monkeypatch.setattr(db_session, "commit", spy)

    async def _fake(db, *, task_id):
        spy.events.append("bind:" + task_id)
        if task_id.endswith("boom"):
            raise RuntimeError("rpc hiccup")
        return {"status": "bound", "binding_id": "9", "amount_usdc": 30.0}

    monkeypatch.setattr(armed.escrow_settlement, "materialize_pending_bind", _fake)

    out = await armed.bind_due(db_session)

    assert [o["task_id"] for o in out] == ["task-short-bind-fine"]
    assert _every_action_is_followed_by_a_commit(spy.events), spy.events
    assert spy.count >= 2

