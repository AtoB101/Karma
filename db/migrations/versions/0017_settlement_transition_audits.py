"""Add settlement transition audit table

Revision ID: 0017_settlement_transition_audits
Revises: 0016_security_policy_change_workflow
Create Date: 2026-05-12 00:00:01
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_settlement_transition_audits"
down_revision = "0016_security_policy_change_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settlement_transition_audits",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("settlement_id", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("transition_allowed", sa.Boolean(), nullable=False),
        sa.Column("guard_stage", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("route_path", sa.String(length=256), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            ["settlements.settlement_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_settlement_transition_audits_task_created",
        "settlement_transition_audits",
        ["task_id", "created_at"],
    )
    op.create_index(
        "ix_settlement_transition_audits_settlement_created",
        "settlement_transition_audits",
        ["settlement_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_settlement_transition_audits_settlement_created", table_name="settlement_transition_audits")
    op.drop_index("ix_settlement_transition_audits_task_created", table_name="settlement_transition_audits")
    op.drop_table("settlement_transition_audits")
