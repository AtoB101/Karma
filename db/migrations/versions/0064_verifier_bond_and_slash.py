"""验证者质押金库（G12）：verifier_nodes 加金库列 + 新建 bond_slashes 罚没台账。

背景（2026-10-11）
------------------
节点质押此前只是 ``verifier_nodes.stake_amount`` 一个记数：没有锁仓背书、没有下限，
也没有罚没 / 退出闭环 —— 节点作恶没有经济成本。这次补三件事：

1. ``verifier_nodes`` 加金库列：``owner_identity_id``（节点主人身份，空 = 名单档）、
   ``bond_state``（现算状态快照）、``bond_floor``（登记时的下限）、
   ``unbond_requested_at`` / ``unbond_amount``（退出冷却）、``slash_unsettled``
   （判负但链上还没出账的金额）。
2. 新建 ``bond_slashes``：罚没台账，**先落账、后出账**。按
   （subject_kind, subject_id, source_kind, source_id）唯一 —— 重复裁决是幂等 no-op。
3. 分账 80/20 由 ``VERIFIER_SLASH_VICTIM_SHARE_BPS`` / ``..._POOL_SHARE_BPS`` 决定，
   两个数相加必须 = 10000（见 config/settings.py 的生产校验）。

老行全部按默认值读 → 与升级前行为一致（``bond_state='appointed'`` = 名单档，
跟名单不跟押金）。回滚只丢这些列与这张表，不影响既有节点、出证与挑战。

原生 DDL + IF NOT EXISTS 的原因与 0060-0063 相同：应用 lifespan 里的
``Base.metadata.create_all`` 也可能已经建出这些列 / 表，迁移再来一次会撞重复错误。

Revision ID: 0064_verifier_bond_and_slash
Revises: 0063_runtime_key_agent_key_fingerprint
Create Date: 2026-10-11
"""
from alembic import op

revision = "0064_verifier_bond_and_slash"
down_revision = "0063_runtime_key_agent_key_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE verifier_nodes "
        "ADD COLUMN IF NOT EXISTS owner_identity_id VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE verifier_nodes "
        "ADD COLUMN IF NOT EXISTS bond_state VARCHAR(16) DEFAULT 'appointed' NOT NULL"
    )
    op.execute(
        "ALTER TABLE verifier_nodes ADD COLUMN IF NOT EXISTS bond_floor DOUBLE PRECISION DEFAULT 0 NOT NULL"
    )
    op.execute(
        "ALTER TABLE verifier_nodes ADD COLUMN IF NOT EXISTS unbond_requested_at TIMESTAMP"
    )
    op.execute(
        "ALTER TABLE verifier_nodes ADD COLUMN IF NOT EXISTS unbond_amount DOUBLE PRECISION DEFAULT 0 NOT NULL"
    )
    op.execute(
        "ALTER TABLE verifier_nodes ADD COLUMN IF NOT EXISTS slash_unsettled DOUBLE PRECISION DEFAULT 0 NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_verifier_nodes_owner_identity_id "
        "ON verifier_nodes (owner_identity_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bond_slashes (
            id VARCHAR(64) PRIMARY KEY,
            subject_kind VARCHAR(32) NOT NULL,
            subject_id VARCHAR(64) NOT NULL,
            wallet_address VARCHAR(42),
            victim_wallet_address VARCHAR(42),
            victim_identity_id VARCHAR(64),
            source_kind VARCHAR(32) NOT NULL,
            source_id VARCHAR(64) NOT NULL,
            amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            victim_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            pool_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            victim_share_bps INTEGER NOT NULL DEFAULT 8000,
            pool_share_bps INTEGER NOT NULL DEFAULT 2000,
            reason TEXT,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            tx_hash VARCHAR(80),
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            settled_at TIMESTAMP,
            CONSTRAINT uq_bond_slash_source
                UNIQUE (subject_kind, subject_id, source_kind, source_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bond_slashes_subject_kind ON bond_slashes (subject_kind)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bond_slashes_subject_id ON bond_slashes (subject_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bond_slashes_status ON bond_slashes (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bond_slashes")
    op.execute("DROP INDEX IF EXISTS ix_verifier_nodes_owner_identity_id")
    op.execute("ALTER TABLE verifier_nodes DROP COLUMN IF EXISTS slash_unsettled")
    op.execute("ALTER TABLE verifier_nodes DROP COLUMN IF EXISTS unbond_amount")
    op.execute("ALTER TABLE verifier_nodes DROP COLUMN IF EXISTS unbond_requested_at")
    op.execute("ALTER TABLE verifier_nodes DROP COLUMN IF EXISTS bond_floor")
    op.execute("ALTER TABLE verifier_nodes DROP COLUMN IF EXISTS bond_state")
    op.execute("ALTER TABLE verifier_nodes DROP COLUMN IF EXISTS owner_identity_id")
