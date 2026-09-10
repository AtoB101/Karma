"""Identity Role Profiles — one identity card, many role profiles (P1).

Revision ID: 0034_identity_role_profiles
Revises: 0033_reputation_pack
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0034_identity_role_profiles"
down_revision = "0033_reputation_pack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_role_profiles",
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column("owner_identity_id", sa.String(64), nullable=False),
        sa.Column("class", sa.String(32), nullable=False, server_default="individual"),
        sa.Column("kyc_status", sa.String(32), nullable=False, server_default="none"),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("kyc_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_identity_role_profiles_owner_identity_id",
        "identity_role_profiles",
        ["owner_identity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_identity_role_profiles_owner_identity_id",
        table_name="identity_role_profiles",
    )
    op.drop_table("identity_role_profiles")
