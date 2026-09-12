"""v2 allowance escrow: commitments are responsibilities, not deposits.

Revision ID: 0042_allowance_escrow
Revises: 0041_seller_stake_pool
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0042_allowance_escrow"
down_revision = "0041_seller_stake_pool"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allowance_commits",
        sa.Column("bill_id", sa.String(80), primary_key=True),
        sa.Column("identity_id", sa.String(64), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contract_address", sa.String(64), nullable=False, server_default=""),
        sa.Column("token_address", sa.String(64), nullable=False, server_default=""),
        sa.Column("operator", sa.String(64), nullable=False, server_default=""),
        sa.Column("amount_wei", sa.String(80), nullable=False, server_default="0"),
        sa.Column("amount_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spent_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reserved_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("backed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("commit_tx_hash", sa.String(80), nullable=False),
        sa.Column("revoke_tx_hash", sa.String(80), nullable=True),
        sa.Column("block_number", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="open"),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("commit_tx_hash", name="uq_allowance_commits_commit_tx_hash"),
    )
    op.create_index("ix_allowance_commits_identity_id", "allowance_commits", ["identity_id"])
    op.create_index("ix_allowance_commits_wallet_address", "allowance_commits", ["wallet_address"])

    op.create_table(
        "escrow_bindings",
        sa.Column("binding_id", sa.String(80), primary_key=True),
        sa.Column("buyer_identity_id", sa.String(64), nullable=False),
        sa.Column("seller_identity_id", sa.String(64), nullable=True),
        sa.Column("buyer_bill_id", sa.String(80), nullable=False),
        sa.Column("seller_bill_id", sa.String(80), nullable=False),
        sa.Column("scope_hash", sa.String(80), nullable=False, server_default=""),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("amount_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stake_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("proof_hash", sa.String(80), nullable=True),
        sa.Column("bind_tx_hash", sa.String(80), nullable=True),
        sa.Column("submit_tx_hash", sa.String(80), nullable=True),
        sa.Column("finalize_tx_hash", sa.String(80), nullable=True),
        sa.Column("pull_after", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("bind_tx_hash", name="uq_escrow_bindings_bind_tx_hash"),
    )
    op.create_index("ix_escrow_bindings_buyer_identity_id", "escrow_bindings", ["buyer_identity_id"])
    op.create_index("ix_escrow_bindings_seller_identity_id", "escrow_bindings", ["seller_identity_id"])
    op.create_index("ix_escrow_bindings_task_id", "escrow_bindings", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_escrow_bindings_task_id", table_name="escrow_bindings")
    op.drop_index("ix_escrow_bindings_seller_identity_id", table_name="escrow_bindings")
    op.drop_index("ix_escrow_bindings_buyer_identity_id", table_name="escrow_bindings")
    op.drop_table("escrow_bindings")
    op.drop_index("ix_allowance_commits_wallet_address", table_name="allowance_commits")
    op.drop_index("ix_allowance_commits_identity_id", table_name="allowance_commits")
    op.drop_table("allowance_commits")