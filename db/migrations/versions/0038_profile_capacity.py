"""Per-profile capacity allocation (one master card -> N identity quotas).

Revision ID: 0038_profile_capacity
Revises: 0037_voucher_profile_binding
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0038_profile_capacity"
down_revision = "0037_voucher_profile_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_capacity",
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column("owner_identity_id", sa.String(128), nullable=False),
        sa.Column("allocated_credits", sa.Float(), nullable=False, server_default="0"),
        sa.Column("available_credits", sa.Float(), nullable=False, server_default="0"),
        sa.Column("in_progress_credits", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pending_settlement_credits", sa.Float(), nullable=False, server_default="0"),
        sa.Column("disputed_credits", sa.Float(), nullable=False, server_default="0"),
        sa.Column("released_credits", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_profile_capacity_owner_identity_id", "profile_capacity", ["owner_identity_id"])


def downgrade() -> None:
    op.drop_index("ix_profile_capacity_owner_identity_id", table_name="profile_capacity")
    op.drop_table("profile_capacity")
