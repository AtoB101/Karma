"""买方沉默到期的自动放行 —— 「72 小时窗口」必须有人真的去推（P2-4）。

F7 修好了 ``POST /auto-confirm`` 本身（窗口写得进、状态机走得通），但生产里没有任何
调度器会去调那个端点：唯一的后台循环是 ``services/chain/escrow_autosettle.run_forever``。
于是 ``SETTLEMENT_CONFIRM_WINDOW_HOURS=72`` 只是一句没人执行的承诺 —— 买方只要不表态，
钱就永远卡在托管里，卖方也拿不到本该拿到的款。

这个文件守两件事：

* 后台兜底 ``auto_confirm_expired_settlements()`` 的行为：到期的放行；没到期的、
  没有窗口的、验证层没过的，一分钱都不许动；
* ``run_forever`` 的那一轮里真的会调它（否则兜底等于没接上，这个缺陷会原样复现）。
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from config.settings import settings
from core.schemas import TaskStatus
from db.models.orm import SettlementModel
from tests.integration.test_f7_confirmation_and_partial_repairs import _to_delivered


async def _row(db, task_id: str) -> SettlementModel:
    result = await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    return result.scalars().one()


async def _patch(db, task_id: str, **fields) -> None:
    row = await _row(db, task_id)
    for key, value in fields.items():
        setattr(row, key, value)
    await db.commit()


async def _delivered(client, activate_identity, task_id: str, *, tag: str) -> None:
    await _to_delivered(
        client,
        activate_identity,
        task_id=task_id,
        buyer=f"buyer-{tag}",
        seller=f"seller-{tag}",
        task_type=f"agent.{tag}",
    )


class TestAutoConfirmReaper:
    @pytest.mark.asyncio
    async def test_releases_delivered_whose_window_expired(self, client, db_session, activate_identity):
        from api.routes.settlement import auto_confirm_expired_settlements

        task_id = "task-reap-expired"
        await _delivered(client, activate_identity, task_id, tag="reap_expired")
        await _patch(db_session, task_id, confirm_deadline_at=datetime.utcnow() - timedelta(hours=1))

        confirmed = await auto_confirm_expired_settlements(db_session)

        assert task_id in confirmed
        row = await _row(db_session, task_id)
        assert row.status == TaskStatus.SETTLED.value
        assert row.released_amount == 100.0
        assert row.refunded_amount == 0.0

    @pytest.mark.asyncio
    async def test_leaves_open_window_alone(self, client, db_session, activate_identity):
        from api.routes.settlement import auto_confirm_expired_settlements

        task_id = "task-reap-open"
        await _delivered(client, activate_identity, task_id, tag="reap_open")

        confirmed = await auto_confirm_expired_settlements(db_session)

        assert task_id not in confirmed
        assert (await _row(db_session, task_id)).status == TaskStatus.DELIVERED.value

    @pytest.mark.asyncio
    async def test_skips_settlement_without_window(self, client, db_session, activate_identity, monkeypatch):
        """窗口关掉（=0）的单子只能由人显式表态，兜底不许替买卖双方决定。"""
        from api.routes.settlement import auto_confirm_expired_settlements

        monkeypatch.setattr(settings, "settlement_confirm_window_hours", 0)
        task_id = "task-reap-nowindow"
        await _delivered(client, activate_identity, task_id, tag="reap_nowindow")
        await _patch(db_session, task_id, confirm_deadline_at=None, updated_at=datetime.utcnow() - timedelta(days=30))

        confirmed = await auto_confirm_expired_settlements(db_session)

        assert task_id not in confirmed
        assert (await _row(db_session, task_id)).status == TaskStatus.DELIVERED.value

    @pytest.mark.asyncio
    async def test_backfills_missing_deadline_from_updated_at(self, client, db_session, activate_identity):
        """老单兜底：交付时还没写 deadline 的行，用 updated_at 现算一次（和路由同口径）。"""
        from api.routes.settlement import auto_confirm_expired_settlements

        task_id = "task-reap-null-deadline"
        await _delivered(client, activate_identity, task_id, tag="reap_nulldeadline")
        window = int(settings.settlement_confirm_window_hours)
        await _patch(
            db_session,
            task_id,
            confirm_deadline_at=None,
            updated_at=datetime.utcnow() - timedelta(hours=window + 1),
        )

        confirmed = await auto_confirm_expired_settlements(db_session)

        assert task_id in confirmed
        assert (await _row(db_session, task_id)).status == TaskStatus.SETTLED.value

    @pytest.mark.asyncio
    async def test_holds_when_delivery_verification_fails(
        self, client, db_session, activate_identity, monkeypatch
    ):
        """验证层没过：超时也不能放款，而且不许把这一轮整个炸掉。"""
        import api.routes.settlement as settlement_routes

        task_id = "task-reap-unverified"
        await _delivered(client, activate_identity, task_id, tag="reap_unverified")
        await _patch(db_session, task_id, confirm_deadline_at=datetime.utcnow() - timedelta(hours=1))

        def _boom(task_id_: str, state, *, stage: str):
            raise HTTPException(409, {"error": "delivery_verification_required", "stage": stage})

        monkeypatch.setattr(settlement_routes, "_assert_p7_delivery_gate", _boom)

        confirmed = await settlement_routes.auto_confirm_expired_settlements(db_session)

        assert task_id not in confirmed
        assert (await _row(db_session, task_id)).status == TaskStatus.DELIVERED.value

    @pytest.mark.asyncio
    async def test_limit_caps_work_per_tick(self, client, db_session, activate_identity):
        from api.routes.settlement import auto_confirm_expired_settlements

        for idx in (1, 2):
            task_id = f"task-reap-limit-{idx}"
            await _delivered(client, activate_identity, task_id, tag=f"reap_limit{idx}")
            await _patch(db_session, task_id, confirm_deadline_at=datetime.utcnow() - timedelta(hours=1))

        confirmed = await auto_confirm_expired_settlements(db_session, limit=1)

        assert len(confirmed) == 1


class TestReaperIsWiredIntoTheLoop:
    def test_run_forever_calls_auto_confirm(self):
        """结构回归：这个循环必须真的调用兜底，否则缺陷原样复现（没人敲那扇门）。"""
        from services.chain import escrow_autosettle

        source = inspect.getsource(escrow_autosettle.run_forever)
        assert "auto_confirm_expired_settlements" in source
