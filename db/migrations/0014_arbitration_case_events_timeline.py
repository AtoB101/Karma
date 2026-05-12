"""Add arbitration case events timeline table

Revision ID: 0014_arbitration_case_events_timeline
Revises: 0013_scan_run_dead_letter_fields
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_arbitration_case_events_timeline"
down_revision = "0013_scan_run_dead_letter_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "arbitration_case_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["arbitration_cases.case_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_arbitration_case_events_case_created",
        "arbitration_case_events",
        ["case_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_arbitration_case_events_case_created", table_name="arbitration_case_events")
    op.drop_table("arbitration_case_events")

