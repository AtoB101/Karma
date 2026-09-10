"""Bind reputation to role profiles (per-identity success/breach history).

Revision ID: 0039_reputation_profile
Revises: 0038_profile_capacity
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0039_reputation_profile"
down_revision = "0038_profile_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reputation", sa.Column("profile_id", sa.String(64), nullable=True))
    op.create_index("ix_reputation_profile_id", "reputation", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_reputation_profile_id", table_name="reputation")
    op.drop_column("reputation", "profile_id")
