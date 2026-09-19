"""Runtime Key 调用记录 + 操作台站内提醒。

两张新表，都是「让主人看得见」用的：

* runtime_key_call_log —— agent 拿这把钥匙调了哪个动作端、结果如何、金额多少。
  额度表只有汇总（今日花了多少），回答不了「哪一次花掉的」。这张表按请求逐条落。
* console_notices —— 主人自己的钥匙发生的事（先落「取消绑定」）。取消绑定是个
  不可逆动作，落库留痕 + 进操作台就有红点，比只在页面上闪一行提示靠谱。

两张表都是纯新增：老行不受影响，业务代码在没有新行时读空列表，行为与升级前一致。
回滚只删这两张表，不动密钥、额度与已产生的凭证。

Revision ID: 0050_runtime_key_call_log_and_notices
Revises: 0049_runtime_key_bind_activation
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0050_runtime_key_call_log_and_notices"
down_revision = "0049_runtime_key_bind_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_key_call_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("karma_identity_id", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False, server_default="POST"),
        sa.Column("outcome", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("http_status", sa.Integer(), nullable=False, server_default=sa.text("200")),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("detail", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_key_call_log_key_id", "runtime_key_call_log", ["key_id"])
    op.create_index(
        "ix_runtime_key_call_log_identity", "runtime_key_call_log", ["karma_identity_id"]
    )
    op.create_index("ix_runtime_key_call_log_created_at", "runtime_key_call_log", ["created_at"])

    op.create_table(
        "console_notices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("karma_identity_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_console_notices_identity", "console_notices", ["karma_identity_id"])
    op.create_index("ix_console_notices_created_at", "console_notices", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_console_notices_created_at", table_name="console_notices")
    op.drop_index("ix_console_notices_identity", table_name="console_notices")
    op.drop_table("console_notices")
    op.drop_index("ix_runtime_key_call_log_created_at", table_name="runtime_key_call_log")
    op.drop_index("ix_runtime_key_call_log_identity", table_name="runtime_key_call_log")
    op.drop_index("ix_runtime_key_call_log_key_id", table_name="runtime_key_call_log")
    op.drop_table("runtime_key_call_log")
