"""Add scan run events timeline table

Revision ID: 0012_scan_run_events_timeline
Revises: 0011_scan_run_worker_claim_and_cancel
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_scan_run_events_timeline"
down_revision = "0011_scan_run_worker_claim_and_cancel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "responsibility_scan_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("scan_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["scan_id"], ["responsibility_scan_runs.scan_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_responsibility_scan_events_scan_created",
        "responsibility_scan_events",
        ["scan_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_responsibility_scan_events_scan_created", table_name="responsibility_scan_events")
    op.drop_table("responsibility_scan_events")

