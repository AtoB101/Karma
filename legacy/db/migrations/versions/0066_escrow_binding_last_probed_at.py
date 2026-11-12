"""台账自愈的「最久没问过的先问」：escrow_bindings.last_probed_at。

背景（2026-10-14 线上实测）
---------------------------
``escrow_autosettle.reconcile_from_chain`` 每一轮只取 ``escrow_autosettle_batch``
（默认 5）条没走到终局的绑定，回链问一次「链上是不是早就落定了」。取数是
``order_by(created_at).limit(5)`` —— 于是最老的那 5 条被反复问，**第 6 条起永远
轮不到**。线上当时有 65 条 ``active``：``#5 / #29 / #30 / #31 / #32`` 每轮都被问，
其余 60 条一次都没被问过。这不是「慢」，是**覆盖不到**：链上早就终局的绑定会永远
停在 active，占着买方的授权额也永远不会回来。

修法：加一列「上一次来问过链的时刻」，取数改成「从没问过的排最前 + 最久没问过的
在前面」，问完立刻盖章。于是一轮一轮把所有绑定都盖到，同一条不会被反复问。

老行默认 NULL = 从没问过，迁移后第一轮会把它们全部排到前面依次盖上（行为与升级前
一样保守：先问一遍再说）。原生 ``ADD COLUMN IF NOT EXISTS`` 的原因与 0060-0065
相同：应用 lifespan 里的 ``Base.metadata.create_all`` / ``_migrate_missing_columns``
可能先建出这一列，迁移再来一次会撞重复错误。

Revision ID: 0066_escrow_binding_last_probed_at
Revises: 0065_runtime_safety_manual_override
Create Date: 2026-10-14
"""
from alembic import op

revision = "0066_escrow_binding_last_probed_at"
down_revision = "0065_runtime_safety_manual_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 列定义与 ``db/models/orm.py`` 的 ``EscrowBindingModel.last_probed_at`` 逐字对应
    # （TIMESTAMP WITHOUT TIME ZONE / nullable），改一边必须改另一边。
    op.execute(
        "ALTER TABLE escrow_bindings "
        "ADD COLUMN IF NOT EXISTS last_probed_at TIMESTAMP WITHOUT TIME ZONE"
    )
    # 取数是 "state IN (...) AND (last_probed_at IS NULL OR last_probed_at < cutoff)
    # ORDER BY last_probed_at NULLS FIRST, created_at"。
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_escrow_bindings_state_probed "
        "ON escrow_bindings (state, last_probed_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_escrow_bindings_state_probed")
    op.execute("ALTER TABLE escrow_bindings DROP COLUMN IF EXISTS last_probed_at")