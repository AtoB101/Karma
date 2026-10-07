"""双 key 轮换：给 runtime_keys 加 hash_key_version 列。

背景（2026-10-02 平滑轮换）
--------------------------
``APP_SECRET_KEY`` 一动，所有已铸 runtime key 的 ``secret_hash`` 都会验不过 ——
因为它们是用旧钥材料算的。双 key 过渡期内先用当前钥验、失败再试上一把钥，
验过之后把 ``secret_hash`` 用当前钥重算落库（惰性迁移）。

要判断「哪把 key 已经迁了、哪把还挂在旧钥上」，光看 64 位 hex 的
``secret_hash`` 看不出来（两代材料的产出都是 64 hex）。所以加一列
``hash_key_version``：16 位签发钥指纹，铸钥时写当前代，旧行回填 ``legacy``。

原生 DDL + IF NOT EXISTS 的原因与 0060 相同：应用 lifespan 里的
``Base.metadata.create_all`` 也可能已经建出这张列，迁移再来一次
``ADD COLUMN`` 会撞 ``DuplicateColumnError``。

Revision ID: 0061_runtime_key_secret_rotation
Revises: 0060_runtime_safety_mode
Create Date: 2026-10-02
"""
from alembic import op

revision = "0061_runtime_key_secret_rotation"
down_revision = "0060_runtime_safety_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE runtime_keys "
        "ADD COLUMN IF NOT EXISTS hash_key_version VARCHAR(32) NOT NULL DEFAULT 'legacy'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE runtime_keys DROP COLUMN IF EXISTS hash_key_version")
