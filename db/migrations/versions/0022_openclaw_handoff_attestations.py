"""Server-side OpenClaw handoff attestation (Console operator confirm).

Revision ID: 0022_openclaw_handoff_attestations
Revises: 0021_runtime_daily_spend_wallet
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_openclaw_handoff_attestations"
down_revision = "0021_runtime_daily_spend_wallet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openclaw_handoff_attestations",
        sa.Column("attestation_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("karma_identity_id", sa.String(length=128), nullable=False),
        sa.Column("attested_by_actor", sa.String(length=128), nullable=True),
        sa.Column("handoff_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=True),
        sa.Column("handoff_snapshot", sa.JSON(), nullable=False),
        sa.Column("readiness_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("attestation_id"),
        sa.UniqueConstraint(
            "task_id",
            "karma_identity_id",
            name="uq_handoff_attestation_task_identity",
        ),
    )
    op.create_index(
        "ix_handoff_attestations_task_id",
        "openclaw_handoff_attestations",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_handoff_attestations_task_id", table_name="openclaw_handoff_attestations")
    op.drop_table("openclaw_handoff_attestations")
