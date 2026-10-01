"""刹车开关落库：安全模式 / 运维暂停不再随重启清零。

背景（2026-10-01 安全审计）
---------------------------
``services/runtime_safety.py`` 的 ``_STATE`` 是**进程内**变量：

1. **重启即清零** —— ``docker compose up -d --force-recreate app``（或者容器 OOM
   重启）之后，之前手动或自动拉下的刹车自动弹回「关」。它在最需要它的时刻失效。
2. **多 worker 各记一份** —— 一个 worker 拉下的刹车，另一个 worker 照常住放行。
   ``deploy/Dockerfile.api`` 里写的正是 ``--workers 4``；0058（nonce 台账）
   已经因为同一件事吃过一次亏，那份迁移的说明可以对照着看。

新表只存**开关本身**，单行（``id=1``）。容量锚的遥测
（``last_anchor_audit_at`` / ``total_locked_usdc`` / ``total_bill_credits``）
每次审计重算，不进库 —— 否则每一笔动钱的请求都会多写一次库。

不带外键、不改既有列、不迁移数据；下线时直接 drop 即可。
写入用**独立会话当场提交**，不借业务请求的事务（那些调用点有的正处在半截业务
写入当中，借它们的会话提交会把半截业务带上，跟着回滚又会把刹车丢掉）。
详见 ``services/runtime_safety.py`` 的落库段落。

Revision ID: 0060_runtime_safety_mode
Revises: 0059_autosettle_and_audit_indexes
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0060_runtime_safety_mode"
down_revision = "0059_autosettle_and_audit_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_safety_mode",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("triggered_by", sa.String(length=128), nullable=True),
        sa.Column("triggered_at", sa.DateTime(), nullable=True),
        sa.Column("pause_new_lock", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pause_new_authorization", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pause_new_task", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pause_new_settlement", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("runtime_safety_mode")
