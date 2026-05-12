"""Add scan mode metadata fields for responsibility scan runs

Revision ID: 0009_scan_mode_and_report_signature_placeholder
Revises: 0008_responsibility_scan_runs
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_scan_mode_and_report_signature_placeholder"
down_revision = "0008_responsibility_scan_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("scan_mode", sa.String(16), nullable=False, server_default="full"),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("base_scan_id", sa.String(64)),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("incremental_since_at", sa.DateTime),
    )
    op.create_index(
        "ix_responsibility_scan_runs_mode_created",
        "responsibility_scan_runs",
        ["scan_mode", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_responsibility_scan_runs_mode_created", table_name="responsibility_scan_runs")
    op.drop_column("responsibility_scan_runs", "incremental_since_at")
    op.drop_column("responsibility_scan_runs", "base_scan_id")
    op.drop_column("responsibility_scan_runs", "scan_mode")

