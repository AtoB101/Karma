"""Phase 1 — preauth rules, payment code fields, voucher rejection.

Revision ID: 0023_phase1_preauth_payment_code
Revises: 0022_openclaw_handoff_attestations
"""

from alembic import op
import sqlalchemy as sa

revision = "0023_phase1_preauth_payment_code"
down_revision = "0022_openclaw_handoff_attestations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_automation_policies",
        sa.Column("preauth_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agent_automation_policies",
        sa.Column("allowed_task_types", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "agent_automation_policies",
        sa.Column("task_precision_min", sa.Float(), nullable=True),
    )
    op.add_column(
        "agent_automation_policies",
        sa.Column("task_precision_max", sa.Float(), nullable=True),
    )
    op.add_column(
        "agent_automation_policies",
        sa.Column("trusted_counterparty_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "agent_automation_policies",
        sa.Column("payment_code_ttl_seconds", sa.Integer(), nullable=False, server_default="3600"),
    )
    op.add_column(
        "agent_automation_policies",
        sa.Column("responsibility_boundary_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "agent_automation_policies",
        sa.Column("auto_accept_incoming", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column("vouchers", sa.Column("task_precision", sa.Float(), nullable=True))
    op.add_column("vouchers", sa.Column("payment_mode", sa.String(length=16), nullable=False, server_default="manual"))
    op.add_column("vouchers", sa.Column("chain_anchor_hash", sa.String(length=128), nullable=True))
    op.add_column("vouchers", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("vouchers", sa.Column("rejected_at", sa.DateTime(), nullable=True))
    op.add_column("vouchers", sa.Column("rejected_by_identity_id", sa.String(length=64), nullable=True))

    op.create_table(
        "voucher_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("voucher_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_identity_id", sa.String(length=64), nullable=True),
        sa.Column("target_identity_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_voucher_events_voucher_id", "voucher_events", ["voucher_id"])


def downgrade() -> None:
    op.drop_index("ix_voucher_events_voucher_id", table_name="voucher_events")
    op.drop_table("voucher_events")
    op.drop_column("vouchers", "rejected_by_identity_id")
    op.drop_column("vouchers", "rejected_at")
    op.drop_column("vouchers", "rejection_reason")
    op.drop_column("vouchers", "chain_anchor_hash")
    op.drop_column("vouchers", "payment_mode")
    op.drop_column("vouchers", "task_precision")
    op.drop_column("agent_automation_policies", "auto_accept_incoming")
    op.drop_column("agent_automation_policies", "responsibility_boundary_id")
    op.drop_column("agent_automation_policies", "payment_code_ttl_seconds")
    op.drop_column("agent_automation_policies", "trusted_counterparty_ids")
    op.drop_column("agent_automation_policies", "task_precision_max")
    op.drop_column("agent_automation_policies", "task_precision_min")
    op.drop_column("agent_automation_policies", "allowed_task_types")
    op.drop_column("agent_automation_policies", "preauth_enabled")
