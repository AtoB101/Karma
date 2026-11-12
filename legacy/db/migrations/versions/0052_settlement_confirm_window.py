"""给结算单补上 MVVS V1 的确认窗口两列。

问题（2026-09-20 测试网端到端实测发现，F6 报告第 9 条）
------------------------------------------------------
``core/schemas.py`` 里 ``confirm_window_hours`` / ``confirm_deadline_at`` 两个字段
一直只是「模型里写着」，``settlements`` 表根本没有对应的列，store 也不映射它们：

* 全代码库没有任何一处给 ``confirm_window_hours`` 赋值 —— 它恒为 null；
* ``POST /v1/settlement/{task_id}/auto-confirm` 第一件事就是读它，null 直接 409
  "confirm_window_hours not set"。

后果：交付（delivered）之后买方不表态的单子没有任何出口 —— 既不能取消，唯一的
超时兜底 ``/auto-confirm`` 又永远不可达，买卖双方的钱一直卡在托管里。
另外 ``DELIVERED → AUTO_CONFIRMED`` 这条状态边此前也不在 VALID_TRANSITIONS 里，
即便窗口写上了也走不通（这条边在 core/settlement/engine.py 里一并补上）。

本次只加两列，不改既有列、不删数据。老行的这两列是 NULL，语义等价于
「这一单没有确认窗口」，与改动前的行为完全一致。

Revision ID: 0052_settlement_confirm_window
Revises: 0051_widen_transition_guard_stage
Create Date: 2026-09-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0052_settlement_confirm_window"
down_revision = "0051_widen_transition_guard_stage"
branch_labels = None
depends_on = None

TABLE = "settlements"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("confirm_window_hours", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("confirm_deadline_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "confirm_deadline_at")
    op.drop_column(TABLE, "confirm_window_hours")
