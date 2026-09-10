"""Add worker claim and cancel fields to scan runs

Revision ID: 0011_scan_run_worker_claim_and_cancel
Revises: 0010_scan_async_execution_fields
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_scan_run_worker_claim_and_cancel"
down_revision = "0010_scan_async_execution_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("responsibility_scan_runs", sa.Column("claimed_by", sa.String(64)))
    op.add_column("responsibility_scan_runs", sa.Column("claimed_at", sa.DateTime))
    op.add_column("responsibility_scan_runs", sa.Column("lease_expires_at", sa.DateTime))
    op.add_column("responsibility_scan_runs", sa.Column("last_heartbeat_at", sa.DateTime))
    op.add_column("responsibility_scan_runs", sa.Column("cancelled_at", sa.DateTime))
    op.add_column("responsibility_scan_runs", sa.Column("cancel_reason", sa.Text))
    op.create_index(
        "ix_responsibility_scan_runs_status_lease_expires",
        "responsibility_scan_runs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_responsibility_scan_runs_status_lease_expires", table_name="responsibility_scan_runs")
    op.drop_column("responsibility_scan_runs", "cancel_reason")
    op.drop_column("responsibility_scan_runs", "cancelled_at")
    op.drop_column("responsibility_scan_runs", "last_heartbeat_at")
    op.drop_column("responsibility_scan_runs", "lease_expires_at")
    op.drop_column("responsibility_scan_runs", "claimed_at")
    op.drop_column("responsibility_scan_runs", "claimed_by")

