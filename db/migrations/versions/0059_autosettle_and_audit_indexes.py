"""给对账与审计的热路径补索引。

问题（2026-10-01 全面审计发现）
--------------------------------
三张表上各有一条「只增不减 + 被定时任务反复扫」的查询，但对应列都没有索引：

1. ``settlement_transition_audits`` —— 迁移 0017 **声明了**两个索引，可是
   ``SettlementTransitionAuditModel`` 里从来没写 ``__table_args__``。于是任何走
   ``Base.metadata.create_all()`` 建库的环境（含测试）都不会有它们，
   **生产上也真的没有**：2026-10-01 核对 ``pg_indexes``，这张表只有主键。
   ``/v1/settlement/{task_id}/transitions`` 按 ``task_id`` 查、
   ``escrow_settlement`` 的对账按 ``settlement_id`` 查，而这张表只增不减。

2. ``escrow_bindings.state`` —— autosettle 的每一次扫描都按它过滤
   （``due_bindings`` / ``due_breach_bindings`` / ``stranded_bindings`` /
   ``reconcile_from_chain``，见 ``services/chain/escrow_autosettle.py``），
   却完全没索引，实测走 Seq Scan。

3. ``settlements.status`` —— ``align_disputed_settlements`` 每 15s 扫
   ``WHERE status = 'disputed' ORDER BY updated_at``，同样无索引。

当前规模（settlements 385 / escrow_bindings 363 / audits 1870 行）下这些都只要
0.3ms，**不是今天的性能问题**；但它们的成本随行数线性增长，而这三条都是
资金对账路径 —— 等它变慢的时候，正好是最不该慢的时候。

为什么用原生 SQL + IF NOT EXISTS
--------------------------------
0017 已经声明过两个审计表索引。生产上它们不存在（所以必须补），但某个环境
理论上可能已经有（例如从 0017 正常建库的环境）。``op.create_index`` 没有
IF NOT EXISTS 语义，撞上已存在的索引会直接报错中断迁移，所以这里用原生 DDL。
index 名与 0017 保持一致，避免同一个索引出现两个名字。

Revision ID: 0059_autosettle_and_audit_indexes
Revises: 0058_runtime_nonce_log
Create Date: 2026-10-01
"""
from alembic import op

revision = "0059_autosettle_and_audit_indexes"
down_revision = "0058_runtime_nonce_log"
branch_labels = None
depends_on = None

#: (索引名, 表名, 列定义)
INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "ix_settlement_transition_audits_task_created",
        "settlement_transition_audits",
        "task_id, created_at",
    ),
    (
        "ix_settlement_transition_audits_settlement_created",
        "settlement_transition_audits",
        "settlement_id, created_at",
    ),
    (
        "ix_escrow_bindings_state_created",
        "escrow_bindings",
        "state, created_at",
    ),
    (
        "ix_settlements_status_updated",
        "settlements",
        "status, updated_at",
    ),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.execute(
            "CREATE INDEX IF NOT EXISTS %s ON %s (%s)" % (name, table, columns)
        )


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute("DROP INDEX IF EXISTS %s" % name)
