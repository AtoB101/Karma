"""Add security policy change workflow tables

Revision ID: 0016_security_policy_change_workflow
Revises: 0015_security_threshold_policies
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_security_policy_change_workflow"
down_revision = "0015_security_threshold_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_policy_change_requests",
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("target_policy_id", sa.String(length=64), nullable=True),
        sa.Column("target_rollback_policy_id", sa.String(length=64), nullable=True),
        sa.Column("rollout_percent", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("dry_run_report", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        "ix_security_policy_change_requests_status_requested",
        "security_policy_change_requests",
        ["status", "requested_at"],
    )

    op.create_table(
        "security_policy_change_approvals",
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("approver_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["security_policy_change_requests.request_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
        sa.UniqueConstraint("request_id", "approver_id", name="uq_security_policy_change_approver"),
    )
    op.create_index(
        "ix_security_policy_change_approvals_request_created",
        "security_policy_change_approvals",
        ["request_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_security_policy_change_approvals_request_created", table_name="security_policy_change_approvals")
    op.drop_table("security_policy_change_approvals")
    op.drop_index("ix_security_policy_change_requests_status_requested", table_name="security_policy_change_requests")
    op.drop_table("security_policy_change_requests")
