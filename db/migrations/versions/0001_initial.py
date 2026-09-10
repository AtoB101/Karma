"""Initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("agent_id",      sa.String(64),  primary_key=True),
        sa.Column("name",          sa.String(256), nullable=False),
        sa.Column("role",          sa.String(32),  nullable=False),
        sa.Column("public_key",    sa.Text,        nullable=False),
        sa.Column("endpoint_url",  sa.String(512)),
        sa.Column("capabilities",  sa.JSON,        nullable=False, server_default="[]"),
        sa.Column("is_active",     sa.Boolean,     nullable=False, server_default="true"),
        sa.Column("registered_at", sa.DateTime,    nullable=False),
    )

    op.create_table(
        "task_contracts",
        sa.Column("task_id",                sa.String(64),  primary_key=True),
        sa.Column("client_agent_id",        sa.String(64),  sa.ForeignKey("agents.agent_id"), nullable=False),
        sa.Column("worker_agent_id",        sa.String(64),  sa.ForeignKey("agents.agent_id")),
        sa.Column("title",                  sa.String(512), nullable=False),
        sa.Column("description",            sa.Text,        nullable=False),
        sa.Column("expected_output_schema", sa.JSON,        nullable=False),
        sa.Column("expected_step_count",    sa.Integer,     nullable=False),
        sa.Column("escrow_amount",          sa.Float,       nullable=False),
        sa.Column("currency",               sa.String(8),   nullable=False, server_default="USD"),
        sa.Column("deadline_at",            sa.DateTime,    nullable=False),
        sa.Column("contract_hash",          sa.String(64)),
        sa.Column("created_at",             sa.DateTime,    nullable=False),
    )

    op.create_table(
        "execution_receipts",
        sa.Column("receipt_id",    sa.String(64),  primary_key=True),
        sa.Column("task_id",       sa.String(64),  sa.ForeignKey("task_contracts.task_id"), nullable=False),
        sa.Column("agent_id",      sa.String(64),  nullable=False),
        sa.Column("step_index",    sa.Integer,     nullable=False),
        sa.Column("tool_name",     sa.String(256), nullable=False),
        sa.Column("input_hash",    sa.String(64),  nullable=False),
        sa.Column("output_hash",   sa.String(64),  nullable=False),
        sa.Column("started_at",    sa.DateTime,    nullable=False),
        sa.Column("ended_at",      sa.DateTime,    nullable=False),
        sa.Column("duration_ms",   sa.Integer,     nullable=False),
        sa.Column("status",        sa.String(16),  nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("metadata",      sa.JSON,        nullable=False, server_default="{}"),
        sa.Column("signature",     sa.Text),
        sa.UniqueConstraint("task_id", "step_index", name="uq_task_step"),
    )

    op.create_table(
        "evidence_bundles",
        sa.Column("bundle_id",          sa.String(64), primary_key=True),
        sa.Column("task_id",            sa.String(64), sa.ForeignKey("task_contracts.task_id"), nullable=False, unique=True),
        sa.Column("task_contract_hash", sa.String(64), nullable=False),
        sa.Column("receipt_ids",        sa.JSON,       nullable=False),
        sa.Column("receipt_hashes",     sa.JSON,       nullable=False),
        sa.Column("final_result_hash",  sa.String(64), nullable=False),
        sa.Column("total_steps",        sa.Integer,    nullable=False),
        sa.Column("successful_steps",   sa.Integer,    nullable=False),
        sa.Column("failed_steps",       sa.Integer,    nullable=False),
        sa.Column("total_duration_ms",  sa.Integer,    nullable=False),
        sa.Column("agent_signature",    sa.Text),
        sa.Column("storage_path",       sa.String(512)),
        sa.Column("settlement_status",  sa.String(32), nullable=False),
        sa.Column("created_at",         sa.DateTime,   nullable=False),
    )

    op.create_table(
        "settlements",
        sa.Column("settlement_id",     sa.String(64), primary_key=True),
        sa.Column("task_id",           sa.String(64), sa.ForeignKey("task_contracts.task_id"), nullable=False, unique=True),
        sa.Column("escrow_amount",     sa.Float,      nullable=False),
        sa.Column("currency",          sa.String(8),  nullable=False),
        sa.Column("status",            sa.String(32), nullable=False),
        sa.Column("client_agent_id",   sa.String(64), nullable=False),
        sa.Column("worker_agent_id",   sa.String(64)),
        sa.Column("released_amount",   sa.Float),
        sa.Column("refunded_amount",   sa.Float),
        sa.Column("dispute_reason",    sa.Text),
        sa.Column("arbitration_notes", sa.Text),
        sa.Column("created_at",        sa.DateTime,   nullable=False),
        sa.Column("updated_at",        sa.DateTime,   nullable=False),
        sa.Column("released_at",       sa.DateTime),
    )

    op.create_table(
        "verification_results",
        sa.Column("verification_id", sa.String(64), primary_key=True),
        sa.Column("task_id",         sa.String(64), sa.ForeignKey("task_contracts.task_id"), nullable=False),
        sa.Column("bundle_id",       sa.String(64), nullable=False),
        sa.Column("decision",        sa.String(16), nullable=False),
        sa.Column("confidence",      sa.Float,      nullable=False),
        sa.Column("checks",          sa.JSON,       nullable=False),
        sa.Column("notes",           sa.Text),
        sa.Column("verified_at",     sa.DateTime,   nullable=False),
    )

    op.create_table(
        "reputation",
        sa.Column("agent_id",             sa.String(64), sa.ForeignKey("agents.agent_id"), primary_key=True),
        sa.Column("role",                 sa.String(32), nullable=False),
        sa.Column("score",                sa.Float,      nullable=False, server_default="100.0"),
        sa.Column("total_tasks",          sa.Integer,    nullable=False, server_default="0"),
        sa.Column("successful_tasks",     sa.Integer,    nullable=False, server_default="0"),
        sa.Column("disputed_tasks",       sa.Integer,    nullable=False, server_default="0"),
        sa.Column("arbitration_wins",     sa.Integer,    nullable=False, server_default="0"),
        sa.Column("arbitration_losses",   sa.Integer,    nullable=False, server_default="0"),
        sa.Column("consecutive_successes",sa.Integer,    nullable=False, server_default="0"),
        sa.Column("wash_trade_flags",     sa.Integer,    nullable=False, server_default="0"),
        sa.Column("last_updated",         sa.DateTime,   nullable=False),
    )

    # Indexes
    op.create_index("ix_receipts_task_id",    "execution_receipts", ["task_id"])
    op.create_index("ix_settlements_status",  "settlements",        ["status"])
    op.create_index("ix_verifications_task",  "verification_results", ["task_id"])
    op.create_index("ix_contracts_client",    "task_contracts",     ["client_agent_id"])
    op.create_index("ix_reputation_score",    "reputation",         ["score"])


def downgrade() -> None:
    for t in ["reputation", "verification_results", "settlements",
              "evidence_bundles", "execution_receipts", "task_contracts", "agents"]:
        op.drop_table(t)
