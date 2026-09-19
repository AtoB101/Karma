"""放宽 settlement_transition_audits.guard_stage 到 64 字符。

问题（2026-09-19 测试网端到端实测发现）
--------------------------------------
``guard_stage`` 原本是 VARCHAR(16)，但有三处调用点写的字符串比这长：

* ``arbitration_case_create``     23 字符  —— api/routes/arbitration.py
* ``arbitration_execute``         19 字符  —— api/routes/arbitration.py
* ``progress_timeout_confirm``    24 字符  —— api/routes/progress.py

Postgres 严格执行宽度，插入时抛 ``StringDataRightTruncationError``，
整个请求 500。实测复现：一单进入 disputed 后调
``POST /v1/arbitration/cases`` 必定 500 —— 争议永远立不了案，
而立案是仲裁的必经入口，等于整条争议链路不可用。

这些 stage 名字是代码里的稳定枚举值，不该被列宽倒逼改名（改名会同时
改掉历史行的语义）。放宽列宽是正确的一侧。

纯加宽，不改类型、不删数据：老行原样保留，回滚只是把宽度收回 16
（前提是还没有长值落库）。

Revision ID: 0051_widen_transition_guard_stage
Revises: 0050_runtime_key_calls_notices
Create Date: 2026-09-19
"""
from alembic import op

revision = "0051_widen_transition_guard_stage"
down_revision = "0050_runtime_key_calls_notices"
branch_labels = None
depends_on = None

TABLE = "settlement_transition_audits"
COLUMN = "guard_stage"


def upgrade() -> None:
    # SQLite 不校验 VARCHAR 宽度，也基本不支持这种 ALTER，跳过即可。
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE %s ALTER COLUMN %s TYPE VARCHAR(64)" % (TABLE, COLUMN)
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE %s ALTER COLUMN %s TYPE VARCHAR(16)" % (TABLE, COLUMN)
        )
