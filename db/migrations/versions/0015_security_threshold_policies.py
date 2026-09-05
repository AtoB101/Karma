"""Add security threshold policy center table

Revision ID: 0015_security_threshold_policies
Revises: 0014_arbitration_case_events_timeline
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_security_threshold_policies"
down_revision = "0014_arbitration_case_events_timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_threshold_policies",
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rollout_percent", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("parent_policy_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("policy_id"),
        sa.UniqueConstraint("version", name="uq_security_threshold_policy_version"),
    )
    op.create_index(
        "ix_security_threshold_policies_status_created",
        "security_threshold_policies",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_security_threshold_policies_status_created", table_name="security_threshold_policies")
    op.drop_table("security_threshold_policies")
