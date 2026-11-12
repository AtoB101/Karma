"""结算回滚赔付台账（④-B2）：新建 settlement_reversals。

背景（2026-10-15）
------------------
链上没有「把钱倒回来」的原语 —— ``SETTLED`` / ``REFUNDED`` 是终局。所以「裁决被推翻」
这件事的后果只能记成**一笔债**：欠谁多少、由金库哪一路出账、已经真到账了多少。
``/overturn`` 当场按**推定**（不采信调用方口述）把它写出来；``paid_amount`` 只在
真正的链上 tx 回链核过之后才增加。

为什么单独一张表，而不是塞进 ``bond_slashes``
--------------------------------------------
``bond_slashes`` 记的是「**罚谁**」（主体 + 来源唯一，罚没额与 80/20 分账）；
本表记的是「**该退谁**」（案件 + 受害方唯一，欠款与实付）。两者的一对多关系是真实的：
一个案件被推翻，赔款的出账可以来自多条罚没 tx（每一条各贡献它自己的 victim 份额），
而罚没台账是按**被罚主体**逐条记的 —— 塞进一张表就分不清「罚」与「赔」。

幂等键 ``(case_id, victim_identity_id)``：同一案件对同一受害方只可能有一条账。
``funding_source`` 是动态的（先 ``bench_bond``，不够再 ``slash_pool``），不进唯一键。

原生 DDL + IF NOT EXISTS 的原因与 0060-0069 相同：应用 lifespan 里的
``Base.metadata.create_all`` 也可能已经建出这张表，迁移再来一次会撞重复错误。

Revision ID: 0070_settlement_reversals
Revises: 0069_arbitration_appeal_rounds
Create Date: 2026-10-15
"""
from alembic import op

revision = "0070_settlement_reversals"
down_revision = "0069_arbitration_appeal_rounds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS settlement_reversals (
            reversal_id VARCHAR(64) PRIMARY KEY,
            case_id VARCHAR(64) NOT NULL,
            task_id VARCHAR(64) NOT NULL,
            binding_id VARCHAR(80),
            victim_identity_id VARCHAR(64),
            victim_wallet VARCHAR(42),
            owed_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            paid_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            funding_source VARCHAR(16) NOT NULL DEFAULT 'bench_bond',
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            tx_hash VARCHAR(80),
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            note TEXT,
            credited_txs TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            settled_at TIMESTAMP,
            CONSTRAINT uq_settlement_reversal_case_victim
                UNIQUE (case_id, victim_identity_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_settlement_reversals_case_id "
        "ON settlement_reversals (case_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_settlement_reversals_task_id "
        "ON settlement_reversals (task_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_settlement_reversals_status "
        "ON settlement_reversals (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS settlement_reversals")
