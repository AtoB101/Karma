"""管道回执的 step_index 必须是 1 基 —— 写成 0 就再也读不出来（2026-10-14 线上 500）。

回归的是这一条：``core/schemas.py::ExecutionReceipt.step_index`` 是
``Field(ge=1)``，而 ``services/trade_auto_execution.kickoff_seller_execution`` 一路来
把管线 ``agent_steps`` 的 **0 基下标** 直接当成了 ``step_index``。于是
``execution_receipts`` 里多一条读不出来的行：任何 ``list_by_task`` /
``get_latest_by_task`` 都在 pydantic 那一步抛 ValidationError，变成裸 500。
而这张表正是放款前「至少一条成功执行回执」那道闸要读的。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from db.models.orm import ReceiptModel, SettlementModel, TaskContractModel
from db.stores.receipt_store import PostgresReceiptStore
from services.trade_auto_execution import kickoff_seller_execution

TASK = "pipe-step-index-task-1"
BUYER = "pipe-step-index-buyer"
SELLER = "pipe-step-index-seller"


async def _seed(db) -> None:
    db.add(
        TaskContractModel(
            task_id=TASK,
            client_agent_id=BUYER,
            worker_agent_id=SELLER,
            title="caption",
            description="caption",
            expected_output_schema={"type": "object"},
            expected_step_count=2,
            escrow_amount=10.0,
            currency="USD",
            deadline_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    db.add(
        SettlementModel(
            settlement_id="pipe-step-index-settlement-1",
            task_id=TASK,
            escrow_amount=10.0,
            currency="USD",
            status="in_progress",
            client_agent_id=BUYER,
            worker_agent_id=SELLER,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    await db.commit()


async def _kickoff(db) -> None:
    await kickoff_seller_execution(
        db,
        task_id=TASK,
        seller_identity_id=SELLER,
        decomposed_spec={
            "agent_steps": [{"index": 0, "action": "parse_requirement"}],
            "pipeline_version": "v2",
        },
    )


@pytest.mark.asyncio
async def test_pipeline_kickoff_receipt_is_readable(db_session):
    """kickoff 写下的那条回执必须能被 store 读回来（step_index >= 1）。

    变异验证：把 ``trade_auto_execution`` 里的 ``step_index`` 改回 0，
    这一条必红：
    ``ValidationError: step_index Input should be greater than or equal to 1``。
    """
    await _seed(db_session)
    await _kickoff(db_session)

    rows = (
        await db_session.execute(
            select(ReceiptModel).where(ReceiptModel.task_id == TASK)
        )
    ).scalars().all()
    assert [r.step_index for r in rows] == [1]

    # 真正会炸的是「读出来」这一步 —— 它正是放款闸门走的那条路。
    receipts = await PostgresReceiptStore(db_session).list_by_task(TASK)
    assert [r.step_index for r in receipts] == [1]
    assert receipts[0].status.value == "success"
    assert await PostgresReceiptStore(db_session).get_latest_by_task(TASK) is not None


@pytest.mark.asyncio
async def test_pipeline_kickoff_does_not_collide_with_existing_receipt(db_session):
    """卖家已经有一条 1 号回执时，管线补的那条要落到下一个空位。

    直接写 1 会撞 ``uq_task_step(task_id, step_index)`` —— 那会把接单
    路径变成 500。取「当前最大 + 1」就不会。
    """
    await _seed(db_session)
    ts = datetime.utcnow()
    db_session.add(
        ReceiptModel(
            task_id=TASK,
            agent_id=SELLER,
            step_index=1,
            tool_name="seller.real_step",
            input_hash="a" * 64,
            output_hash="b" * 64,
            started_at=ts,
            ended_at=ts,
            duration_ms=1,
            status="success",
            metadata_={},
        )
    )
    await db_session.commit()

    await _kickoff(db_session)

    receipts = await PostgresReceiptStore(db_session).list_by_task(TASK)
    assert [r.step_index for r in receipts] == [1, 2]
    assert receipts[1].tool_name == "trade_pipeline.parse_requirement"
