"""Add progress receipt table

Revision ID: 0004_progress_receipts
Revises: 0003_capacity_and_voucher
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_progress_receipts"
down_revision = "0003_capacity_and_voucher"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "progress_receipts",
        sa.Column("progress_receipt_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("task_contracts.task_id"), nullable=False),
        sa.Column("seller_identity_id", sa.String(64), nullable=False),
        sa.Column("progress_percent", sa.Float, nullable=False),
        sa.Column("claimed_value_percent", sa.Float, nullable=False),
        sa.Column("evidence_hash", sa.String(128), nullable=False),
        sa.Column("runtime_log_hash", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        sa.Column("seller_signature", sa.Text, nullable=False),
        sa.Column("validation_method", sa.String(64), nullable=False),
        sa.Column("confirmation_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("confirmed_at", sa.DateTime),
    )

    op.create_index("ix_progress_task_id", "progress_receipts", ["task_id"])
    op.create_index("ix_progress_confirmation", "progress_receipts", ["confirmation_status"])


def downgrade() -> None:
    op.drop_index("ix_progress_confirmation", table_name="progress_receipts")
    op.drop_index("ix_progress_task_id", table_name="progress_receipts")
    op.drop_table("progress_receipts")

