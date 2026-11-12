"""回执 step_index 归一：管道旧行写的是 0，读不出来（2026-10-14 线上 500）。

背景（2026-10-14 实测）
----------------------
``core/schemas.py::ExecutionReceipt.step_index`` 是 **1 基**（``Field(ge=1)``），
收据路由也要求「这一单第一条必须是 1」。但
``services/trade_auto_execution.kickoff_seller_execution`` 一路来把管线
``agent_steps`` 的下标（0 起）直接当成了 ``step_index``，写成 0。
于是 ``execution_receipts`` 里躺着一条**读都读不出来**的行：
``PostgresReceiptStore`` 把它喂给 pydantic 时当场
``ValidationError: Input should be greater than or equal to 1``，任何
``list_by_task`` / ``get_latest_by_task`` 都炸成裸 500。

放款那几道闸都要读这张表 —— testnet 实测：一单带 0 号回执的交易走到
``POST /v1/settlement/{task}/buyer-accept`` 直接 500，**卖方一分钱收不到**。
线上（prod）同一形状的行也有一条。

修法：把 ``step_index < 1`` 的历史行补成这条单上第一个空出来的正整数。
写入侧已经在 ``services/trade_auto_execution.py`` 改成 1 基，这里只补历史数据。

为什么不用一句 ``UPDATE ... SET step_index = 1``：``uq_task_step`` 是
``(task_id, step_index)`` 唯一，同一单上已经有一条 1 号回执时会撞约束。
逐行取「当前最大 + 1」既能落地，又保住唯一性。

Revision ID: 0067_receipt_step_index_one_based
Revises: 0066_escrow_binding_last_probed_at
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0067_receipt_step_index_one_based"
down_revision = "0066_escrow_binding_last_probed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT task_id, receipt_id FROM execution_receipts "
            "WHERE step_index < 1 ORDER BY task_id, started_at, receipt_id"
        )
    ).fetchall()
    for task_id, receipt_id in rows:
        nxt = bind.execute(
            sa.text(
                "SELECT COALESCE(MAX(step_index), 0) + 1 FROM execution_receipts "
                "WHERE task_id = :task_id"
            ),
            {"task_id": task_id},
        ).scalar_one()
        bind.execute(
            sa.text("UPDATE execution_receipts SET step_index = :n WHERE receipt_id = :r"),
            {"n": int(nxt), "r": receipt_id},
        )


def downgrade() -> None:
    # 有意为空：把回执降回 0 会重新造出「读不出来」的行，
    # 没有回滚的价值（上游：把管道写入改回 0 只会再把放款打挂）。
    pass
