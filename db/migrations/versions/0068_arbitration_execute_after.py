"""④-A 上诉窗口：arbitration_cases.execute_after。

背景
----
链上**没有**「把钱倒回来」的原语：托管合约的终局函数只有
``finalizeSettlement`` / ``finalizeBreach`` / ``cancelBinding`` / ``markDisputed``，
``Settled`` / ``StakeSlashed`` 一旦落定，钱就在对方钱包里（详见
``docs/ARBITRATION_SETTLEMENT_REVERSAL.md`` 的三条硬约束）。所以「裁决被推翻要
退钱」这件事只能靠**提前拦截**，不能靠事后回滚。

这一列就是那个拦截点：裁决下发后先记一个到期时刻 ``execute_after``，
窗口内**链上一笔都不发**（钱一步不动），推翻零成本；到点再由
``POST /v1/arbitration/cases/{id}/execute-due`` 落钱。

``ARBITRATION_APPEAL_WINDOW_SECONDS=0``（默认）= 关闭：``/execute`` 与历史
行为逐字一致，这一列保持 NULL —— 老行全是 NULL，正好就是「没有窗口」。
原生 ``ADD COLUMN IF NOT EXISTS`` 的原因与 0060-0067 相同：应用 lifespan 里的
``Base.metadata.create_all`` / ``_migrate_missing_columns`` 可能先建出这一列。

Revision ID: 0068_arbitration_execute_after
Revises: 0067_receipt_step_index_one_based
Create Date: 2026-10-14
"""
from alembic import op

revision = "0068_arbitration_execute_after"
down_revision = "0067_receipt_step_index_one_based"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 列定义与 ``db/models/orm.py`` 的 ``ArbitrationCaseModel.execute_after`` 逐字对应
    # （TIMESTAMP WITHOUT TIME ZONE / nullable），改一边必须改另一边。
    op.execute(
        "ALTER TABLE arbitration_cases "
        "ADD COLUMN IF NOT EXISTS execute_after TIMESTAMP WITHOUT TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE arbitration_cases DROP COLUMN IF EXISTS execute_after")