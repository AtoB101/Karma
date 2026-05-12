"""Add responsibility batch scan run tables

Revision ID: 0008_responsibility_scan_runs
Revises: 0007_responsibility_graph
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_responsibility_scan_runs"
down_revision = "0007_responsibility_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "responsibility_scan_runs",
        sa.Column("scan_id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("window_hours", sa.Integer, nullable=False, server_default="24"),
        sa.Column("max_hops", sa.Integer, nullable=False, server_default="4"),
        sa.Column("min_score_threshold", sa.Float, nullable=False, server_default="8"),
        sa.Column("total_identities", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flagged_identities", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime),
    )

    op.create_table(
        "responsibility_scan_findings",
        sa.Column("finding_id", sa.String(64), primary_key=True),
        sa.Column("scan_id", sa.String(64), nullable=False),
        sa.Column("identity_id", sa.String(64), nullable=False),
        sa.Column("normalized_score", sa.Float, nullable=False),
        sa.Column("risk_band", sa.String(16), nullable=False),
        sa.Column("signal_count", sa.Integer, nullable=False),
        sa.Column("cycle_paths_detected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.ForeignKeyConstraint(["scan_id"], ["responsibility_scan_runs.scan_id"], ondelete="CASCADE"),
    )

    op.create_index(
        "ix_responsibility_scan_findings_scan",
        "responsibility_scan_findings",
        ["scan_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_responsibility_scan_findings_scan", table_name="responsibility_scan_findings")
    op.drop_table("responsibility_scan_findings")
    op.drop_table("responsibility_scan_runs")

