"""给链上绑定补上「买方已确认放款」的时刻。

问题（2026-09-21 状态机改造）
-----------------------------
v4 的合约多了一个买方的确认标记（``buyerConfirm``）：验证已经通过、resolver 已经
提交之后，买方自己点头就不必再等争议窗口 —— 窗口本来就是给「买方还没表态」留的
宽限期，而不是给双方都确认过的单子留的。

链上只回答「标记置位了没有」，回答不了「什么时候置的」，而操作台要能把这件事讲
清楚（谁在什么时候确认的、那次确认对应哪笔交易）。所以这一列记的是**账上**的
时间与来龙去脉，不参与任何金额计算：钱的事实仍然只在链上。

只加一列，不改既有列、不删数据。历史行留空 = 当时还没有这回事。

Revision ID: 0055_escrow_binding_buyer_confirm
Revises: 0054_binding_id_contract_namespace
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0055_escrow_binding_buyer_confirm"
down_revision = "0054_binding_id_contract_namespace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "escrow_bindings",
        sa.Column("buyer_confirmed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("escrow_bindings", "buyer_confirmed_at")
