"""Runtime Key 绑定 agent 公钥（使用时刻硬校验）。

`runtime_keys` 加三列：

* key_binding     —— service（老路径，服务端托管，认 key 不认人）或 agent（已绑定 agent 公钥）。
* agent_public_key —— agent 的 Ed25519 裸公钥（base64，32 字节）；绑定后每个请求都要它验签。
* nonce_required   —— 会动钱的权限（place_order / request_settlement）→ 每请求强制 nonce。

起因：Runtime Key 是不记名令牌，被偷走就等于被花掉。绑定 agent 公钥之后，
光有 key 字符串不再够用，还得有对应私钥签出来的每个请求。

老行全部留 NULL → 业务代码按「未绑定」读，行为与升级前完全一致；
回滚只是丢这三列，不影响密钥本体、额度与已产生的记录。

Revision ID: 0048_runtime_key_binding
Revises: 0047_identity_provider
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0048_runtime_key_binding"
down_revision = "0047_identity_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runtime_keys",
        sa.Column("key_binding", sa.String(length=16), nullable=True, server_default="service"),
    )
    op.add_column(
        "runtime_keys",
        sa.Column("agent_public_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "runtime_keys",
        sa.Column("nonce_required", sa.Boolean(), nullable=True, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("runtime_keys", "nonce_required")
    op.drop_column("runtime_keys", "agent_public_key")
    op.drop_column("runtime_keys", "key_binding")
