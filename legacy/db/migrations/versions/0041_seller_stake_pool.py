"""Seller stake pool: mark a locked bill as idle/reserved for one order.

Revision ID: 0041_seller_stake_pool
Revises: 0040_chain_lock
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0041_seller_stake_pool"
down_revision = "0040_chain_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chain_locks",
        sa.Column("stake_state", sa.String(16), nullable=False, server_default="idle"),
    )
    op.add_column("chain_locks", sa.Column("stake_task_id", sa.String(64), nullable=True))
    op.add_column("chain_locks", sa.Column("stake_reserved_at", sa.DateTime(), nullable=True))
    op.create_index("ix_chain_locks_stake_task_id", "chain_locks", ["stake_task_id"])


def downgrade() -> None:
    op.drop_index("ix_chain_locks_stake_task_id", table_name="chain_locks")
    op.drop_column("chain_locks", "stake_reserved_at")
    op.drop_column("chain_locks", "stake_task_id")
    op.drop_column("chain_locks", "stake_state")
