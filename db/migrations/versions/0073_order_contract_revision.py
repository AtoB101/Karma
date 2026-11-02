"""Order contract revision versioning: add ``version`` column.

Revision ID: 0073_order_contract_revision
Revises: 0072_order_contract_trade_clauses
Create Date: 2026-11-03
"""
from alembic import op

revision = "0073_order_contract_revision"
down_revision = "0072_order_contract_trade_clauses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS version")
