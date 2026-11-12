"""On-chain wallet locks: one row per credited KarmaBilateral.lock() receipt.

Revision ID: 0040_chain_lock
Revises: 0039_reputation_profile
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0040_chain_lock"
down_revision = "0039_reputation_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chain_locks",
        sa.Column("bill_id", sa.String(80), primary_key=True),
        sa.Column("identity_id", sa.String(64), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contract_address", sa.String(64), nullable=False, server_default=""),
        sa.Column("token_address", sa.String(64), nullable=False, server_default=""),
        sa.Column("amount_wei", sa.String(80), nullable=False, server_default="0"),
        sa.Column("amount_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("lock_tx_hash", sa.String(80), nullable=False),
        sa.Column("block_number", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="locked"),
        sa.Column("unlock_tx_hash", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("lock_tx_hash", name="uq_chain_locks_lock_tx_hash"),
    )
    op.create_index("ix_chain_locks_identity_id", "chain_locks", ["identity_id"])
    op.create_index("ix_chain_locks_wallet_address", "chain_locks", ["wallet_address"])


def downgrade() -> None:
    op.drop_index("ix_chain_locks_wallet_address", table_name="chain_locks")
    op.drop_index("ix_chain_locks_identity_id", table_name="chain_locks")
    op.drop_table("chain_locks")
