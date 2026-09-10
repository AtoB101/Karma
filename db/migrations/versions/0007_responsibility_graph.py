"""Add responsibility graph edge and signal tables

Revision ID: 0007_responsibility_graph
Revises: 0006_arbitration_pool_and_cases
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_responsibility_graph"
down_revision = "0006_arbitration_pool_and_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "responsibility_edges",
        sa.Column("edge_id", sa.String(64), primary_key=True),
        sa.Column("edge_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("source_identity_id", sa.String(64), nullable=False),
        sa.Column("target_identity_id", sa.String(64), nullable=False),
        sa.Column("edge_type", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(64)),
        sa.Column("voucher_id", sa.String(64)),
        sa.Column("metadata", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("voucher_id", name="uq_responsibility_edge_voucher"),
    )
    op.create_index(
        "ix_responsibility_edges_source_target",
        "responsibility_edges",
        ["source_identity_id", "target_identity_id"],
    )
    op.create_index("ix_responsibility_edges_task", "responsibility_edges", ["task_id", "created_at"])

    op.create_table(
        "responsibility_signals",
        sa.Column("signal_id", sa.String(64), primary_key=True),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("identity_id", sa.String(64), nullable=False),
        sa.Column("edge_hash", sa.String(64), nullable=False),
        sa.Column("related_edge_hashes", sa.JSON, nullable=False),
        sa.Column("task_id", sa.String(64)),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_responsibility_signals_identity_created",
        "responsibility_signals",
        ["identity_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_responsibility_signals_identity_created", table_name="responsibility_signals")
    op.drop_table("responsibility_signals")
    op.drop_index("ix_responsibility_edges_task", table_name="responsibility_edges")
    op.drop_index("ix_responsibility_edges_source_target", table_name="responsibility_edges")
    op.drop_table("responsibility_edges")

