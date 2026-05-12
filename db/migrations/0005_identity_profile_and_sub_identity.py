"""Add identity profile and sub-identity tables

Revision ID: 0005_identity_profile_and_sub_identity
Revises: 0004_progress_receipts
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_identity_profile_and_sub_identity"
down_revision = "0004_progress_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_profiles",
        sa.Column("identity_id", sa.String(64), primary_key=True),
        sa.Column("display_id", sa.String(64), nullable=False, unique=True),
        sa.Column("legal_identity_status", sa.String(32), nullable=False, server_default="unbound"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "sub_identities",
        sa.Column("sub_identity_id", sa.String(64), primary_key=True),
        sa.Column("parent_identity_id", sa.String(64), nullable=False),
        sa.Column("sub_identity_type", sa.String(32), nullable=False),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("deleted_at", sa.DateTime),
        sa.UniqueConstraint("parent_identity_id", "alias", name="uq_sub_identity_alias_per_parent"),
    )

    op.create_index("ix_sub_identities_parent_status", "sub_identities", ["parent_identity_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_sub_identities_parent_status", table_name="sub_identities")
    op.drop_table("sub_identities")
    op.drop_table("identity_profiles")

