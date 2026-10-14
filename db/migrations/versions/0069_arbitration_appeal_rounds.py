"""④-A3 窗口内上诉：票按轮次计 + 案件记上诉次数。

背景
----
④-A1 把「判决落地」与「放款」拆开：窗口内链上一笔不发，所以推翻是**零成本**的。
但光有 ④-A1 时窗口里没有入口 —— 没有「打回去重审」这个动作，窗口是空转的。
④-A3 补的就是这个入口：把 ``decided`` 且未到期的案件打回 ``voting``。

打回必须开一轮新的投票，而 ``arbitration_votes`` 原来的唯一键是
``(case_id, arbitrator_identity_id)`` —— 同一批仲裁员在重审里根本投不出第二票。
所以这一版给票加上 ``vote_round``，把唯一键换成
``(case_id, vote_round, arbitrator_identity_id)``：同一个人**同一轮**只能投一票，
换一轮就能再投。

老行一律 ``vote_round = 0``，正好就是「没有轮次概念的那些票 = 第 0 轮」，
所以升级前后计票口径对老案件逐字一致（默认窗口关闭，本来就到不了这里）。

Revision ID: 0069_arbitration_appeal_rounds
Revises: 0068_arbitration_execute_after
Create Date: 2026-10-14
"""
from alembic import op

revision = "0069_arbitration_appeal_rounds"
down_revision = "0068_arbitration_execute_after"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 列定义与 ``db/models/orm.py`` 逐字对应（INTEGER NOT NULL DEFAULT 0）。
    # 用 IF NOT EXISTS 的原因与 0060-0068 相同：应用 lifespan 里的
    # ``Base.metadata.create_all`` / ``_migrate_missing_columns`` 可能先建出这几列。
    op.execute(
        "ALTER TABLE arbitration_cases "
        "ADD COLUMN IF NOT EXISTS vote_round INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE arbitration_cases "
        "ADD COLUMN IF NOT EXISTS appeal_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE arbitration_votes "
        "ADD COLUMN IF NOT EXISTS vote_round INTEGER NOT NULL DEFAULT 0"
    )
    # 换唯一键：老约束会把「上诉后同一个人再投一次」堵死。
    op.execute("ALTER TABLE arbitration_votes DROP CONSTRAINT IF EXISTS uq_arbitration_vote")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_arbitration_vote_round') "
        "THEN ALTER TABLE arbitration_votes ADD CONSTRAINT uq_arbitration_vote_round "
        "UNIQUE (case_id, vote_round, arbitrator_identity_id); "
        "END IF; END $$"
    )


def downgrade() -> None:
    # 回退到老约束前必须先确认「同一个案件里没有跨轮重复的仲裁员」——有的话这条
    # UNIQUE 会加不上，迁移会明确报错而不是静默把约束丢了（宁可红）。
    op.execute("ALTER TABLE arbitration_votes DROP CONSTRAINT IF EXISTS uq_arbitration_vote_round")
    op.execute(
        "ALTER TABLE arbitration_votes "
        "ADD CONSTRAINT uq_arbitration_vote UNIQUE (case_id, arbitrator_identity_id)"
    )
    op.execute("ALTER TABLE arbitration_votes DROP COLUMN IF EXISTS vote_round")
    op.execute("ALTER TABLE arbitration_cases DROP COLUMN IF EXISTS appeal_count")
    op.execute("ALTER TABLE arbitration_cases DROP COLUMN IF EXISTS vote_round")
