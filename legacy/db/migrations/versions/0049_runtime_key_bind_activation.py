"""Runtime Key 接入匹配码（用户手输才生效）。

`runtime_keys` 再加五列，全是「待确认接入」的暂存位：

* pending_agent_public_key —— agent 申请接入时提交的 Ed25519 公钥，**还没生效**。
* pending_code_hash        —— 匹配码的 HMAC（只存哈希，明文只在 agent 手里）。
* pending_expires_at       —— 匹配码 15 分钟过期。
* pending_attempts         —— 试错计数，满 5 次作废，得让 agent 重新申请。
* pending_requested_at     —— 申请时间，操作台按它排序展示。

起因：Runtime Key 是不记名令牌，光绑公钥还挡不住「偷到 key 的人抢先绑上自己的公钥」。
现在 agent 申请后只是拿到一串码，必须由用户在操作台手输这串码，绑定才落库 ——
偷到 key 的人手里没有用户那串码。

老行全部留 NULL → 业务代码按「无待确认请求」读，行为与升级前完全一致；
回滚只是丢这五列，不影响密钥本体、额度、已生效的绑定与已产生的记录。

Revision ID: 0049_runtime_key_bind_activation
Revises: 0048_runtime_key_binding
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0049_runtime_key_bind_activation"
down_revision = "0048_runtime_key_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runtime_keys",
        sa.Column("pending_agent_public_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "runtime_keys",
        sa.Column("pending_code_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "runtime_keys",
        sa.Column("pending_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "runtime_keys",
        sa.Column(
            "pending_attempts", sa.Integer(), nullable=True, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "runtime_keys",
        sa.Column("pending_requested_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runtime_keys", "pending_requested_at")
    op.drop_column("runtime_keys", "pending_attempts")
    op.drop_column("runtime_keys", "pending_expires_at")
    op.drop_column("runtime_keys", "pending_code_hash")
    op.drop_column("runtime_keys", "pending_agent_public_key")
