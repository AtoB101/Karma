"""操作台的第二把锁（2FA）与刷脸模板：授权 / 取消授权要过验证码，追加身份要过同人比对。

背景（2026-09-23）
------------------
操作台的钥匙是**不记名**的：绑到 agent 上的运行时密钥、钱包会话，谁拿到谁就能动。
这一轮把「动额度」和「摘公钥」这两类动作加上第二道锁，并让「刷脸一次」成为
主身份的激活方式、让「再刷脸一次」成为追加身份的自动审核方式。为此加两张表：

``console_two_factors``
    TOTP 密钥（base32）+ 恢复码哈希 + 失败计数 / 锁定时间。验证码本身不落库。
    一条身份一行，没绑过就没有行。

``identity_face_templates``
    首次刷脸留下的**脸型模板密文**（浏览器里加密，Karma 只拿密文 + 摘要）
    与采集元数据。追加身份时用户在本机解出它、跟现采的脸比一次，服务端复核结论。

两张表都是新表、不带外键、不改既有列、不迁移数据；下线时直接 drop 即可。

Revision ID: 0057_console_2fa_and_face
Revises: 0056_role_profile_governance_stake
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0057_console_2fa_and_face"
down_revision = "0056_role_profile_governance_stake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "console_two_factors",
        sa.Column("identity_id", sa.String(length=128), primary_key=True),
        sa.Column("secret", sa.String(length=64), nullable=True),
        sa.Column("enabled_at", sa.DateTime(), nullable=True),
        sa.Column("pending_secret", sa.String(length=64), nullable=True),
        sa.Column("pending_created_at", sa.DateTime(), nullable=True),
        sa.Column("recovery_hashes", sa.JSON(), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "identity_face_templates",
        sa.Column("identity_id", sa.String(length=128), primary_key=True),
        sa.Column("template_cipher", sa.Text(), nullable=False),
        sa.Column("template_digest", sa.String(length=128), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=True),
        sa.Column("encryption", sa.JSON(), nullable=True),
        sa.Column("liveness", sa.JSON(), nullable=True),
        sa.Column("capture_digest", sa.String(length=128), nullable=True),
        sa.Column("wallet_address", sa.String(length=128), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="face_liveness"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("identity_face_templates")
    op.drop_table("console_two_factors")
