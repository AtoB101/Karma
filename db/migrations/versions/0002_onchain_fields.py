"""Add on-chain settlement fields

Revision ID: 0002_onchain_fields
Revises: 0001_initial
Create Date: 2025-01-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision      = "0002_onchain_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column("settlements", sa.Column("settlement_mode",      sa.String(16),  nullable=False, server_default="offchain"))
    op.add_column("settlements", sa.Column("chain_id",             sa.Integer(),   nullable=True))
    op.add_column("settlements", sa.Column("contract_address",     sa.String(42),  nullable=True))
    op.add_column("settlements", sa.Column("tx_hash",              sa.String(66),  nullable=True))
    op.add_column("settlements", sa.Column("evidence_bundle_hash", sa.String(66),  nullable=True))
    op.add_column("settlements", sa.Column("onchain_status",       sa.String(32),  nullable=True))
    op.add_column("settlements", sa.Column("quote_id",             sa.String(66),  nullable=True))

    op.create_index("ix_settlements_tx_hash", "settlements", ["tx_hash"])


def downgrade() -> None:
    op.drop_index("ix_settlements_tx_hash", "settlements")
    for col in ["settlement_mode", "chain_id", "contract_address",
                "tx_hash", "evidence_bundle_hash", "onchain_status", "quote_id"]:
        op.drop_column("settlements", col)
