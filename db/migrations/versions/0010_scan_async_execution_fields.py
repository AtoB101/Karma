"""Add async execution and retry fields to scan runs

Revision ID: 0010_scan_async_execution_fields
Revises: 0009_scan_mode_and_report_signature_placeholder
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_scan_async_execution_fields"
down_revision = "0009_scan_mode_and_report_signature_placeholder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("execution_mode", sa.String(16), nullable=False, server_default="sync"),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("requested_identity_ids", sa.JSON),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("retry_max_attempts", sa.Integer, nullable=False, server_default="3"),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("retry_backoff_seconds", sa.Integer, nullable=False, server_default="30"),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("current_attempt", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("started_at", sa.DateTime),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("next_retry_at", sa.DateTime),
    )
    op.add_column(
        "responsibility_scan_runs",
        sa.Column("last_error", sa.Text),
    )
    op.create_index(
        "ix_responsibility_scan_runs_status_next_retry",
        "responsibility_scan_runs",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_responsibility_scan_runs_status_next_retry", table_name="responsibility_scan_runs")
    op.drop_column("responsibility_scan_runs", "last_error")
    op.drop_column("responsibility_scan_runs", "next_retry_at")
    op.drop_column("responsibility_scan_runs", "started_at")
    op.drop_column("responsibility_scan_runs", "current_attempt")
    op.drop_column("responsibility_scan_runs", "retry_backoff_seconds")
    op.drop_column("responsibility_scan_runs", "retry_max_attempts")
    op.drop_column("responsibility_scan_runs", "requested_identity_ids")
    op.drop_column("responsibility_scan_runs", "execution_mode")

