"""Skill developer real-name: 技能开发者实名 + 开发者协议签名存证。

商业化口径：技能目录里每一个可收费的 endpoint，背后都要有一个**可追责的自然人**，
并且这个人签过开发者协议（协议正文是服务端常量，摘要落库，签名由钱包背书）。

* 新表 ``skill_developers``：一个身份可以有多个开发者档案（每人一个钱包），
  ``signer_wallet`` 是 recover 出来的地址；材料只存密文包 + 摘要。
* ``skills`` 加一列可空的 ``developer_id``：指向这次上架签名对应的开发者档案，
  用来回答「这个技能到底是谁上架的」。老行保持 NULL，不影响既有数据。

全部为新增，`skills.developer_id` 可空且无默认值，回滚安全。

Revision ID: 0046_skill_developers
Revises: 0045_data_api_commerce
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0046_skill_developers"
down_revision = "0045_data_api_commerce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_developers",
        sa.Column("developer_id", sa.String(64), primary_key=True),
        sa.Column("identity_id", sa.String(128), nullable=False),
        sa.Column("legal_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("real_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("role_title", sa.String(64), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(200), nullable=False, server_default=""),
        sa.Column("developer_role", sa.String(32), nullable=False, server_default="developer"),
        sa.Column("agreement_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("agreement_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("signer_wallet", sa.String(128), nullable=True),
        sa.Column("signature", sa.String(200), nullable=True),
        sa.Column("materials", sa.JSON(), nullable=True),
        sa.Column("package_digest", sa.String(128), nullable=True),
        sa.Column("package_cipher", sa.Text(), nullable=True),
        sa.Column("encryption", sa.JSON(), nullable=True),
        sa.Column("extracted", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("reviewer_identity_id", sa.String(128), nullable=True),
        sa.Column("review_note", sa.String(2000), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_skill_developers_identity_id", "skill_developers", ["identity_id"])
    op.create_index("ix_skill_developers_status", "skill_developers", ["status"])

    op.add_column("skills", sa.Column("developer_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("skills", "developer_id")
    op.drop_index("ix_skill_developers_status", table_name="skill_developers")
    op.drop_index("ix_skill_developers_identity_id", table_name="skill_developers")
    op.drop_table("skill_developers")