"""钱包签名里钉下 agent 公钥指纹：runtime_keys 加一列。

背景（2026-10-10 agent 自助接入加固）
------------------------------------
铸造 Runtime Key 时主人签的那段文字，此前只写了 ``agent_binding``（一个可以随手
改写的名字）。谁都可以把这个名字改成别的；名字对不上并不阻止钱花出去。

现在签名消息里追加 ``agent_public_key_fingerprint``：主人签字断言的是「这把钱钥匙
只授权给这个指纹对应的 agent」。绑定那一刻（activate_key_binding /
confirm_key_binding）服务端拿 agent 交上来的真实公钥重算指纹，对不上直接 403 ——
来绑的不是主人签字授权的那一个。

老行全部留 NULL → 业务代码按「没有这层约束」读，行为与升级前完全一致；回滚只是
丢这一列，不影响密钥本体、额度、已生效的绑定与已产生的记录。

原生 DDL + IF NOT EXISTS 的原因与 0060/0061 相同：应用 lifespan 里的
``Base.metadata.create_all`` 也可能已经建出这一列，迁移再来一次 ``ADD COLUMN``
会撞 ``DuplicateColumnError``。

Revision ID: 0063_runtime_key_agent_key_fingerprint
Revises: 0062_verification_revocation_requests
Create Date: 2026-10-10
"""
from alembic import op

revision = "0063_runtime_key_agent_key_fingerprint"
down_revision = "0062_verification_revocation_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE runtime_keys "
        "ADD COLUMN IF NOT EXISTS agent_public_key_fingerprint VARCHAR(32)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE runtime_keys DROP COLUMN IF EXISTS agent_public_key_fingerprint")
