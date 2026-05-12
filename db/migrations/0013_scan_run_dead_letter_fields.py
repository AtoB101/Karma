"""Add dead-letter fields for scan runs

Revision ID: 0013_scan_run_dead_letter_fields
Revises: 0012_scan_run_events_timeline
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_scan_run_dead_letter_fields"
down_revision = "0012_scan_run_events_timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("responsibility_scan_runs", sa.Column("dead_lettered_at", sa.DateTime))
    op.add_column("responsibility_scan_runs", sa.Column("dead_letter_reason", sa.Text))
    op.create_index(
        "ix_responsibility_scan_runs_status_dead_lettered",
        "responsibility_scan_runs",
        ["status", "dead_lettered_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_responsibility_scan_runs_status_dead_lettered", table_name="responsibility_scan_runs")
    op.drop_column("responsibility_scan_runs", "dead_letter_reason")
    op.drop_column("responsibility_scan_runs", "dead_lettered_at")

