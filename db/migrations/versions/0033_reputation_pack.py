"""Persist pack/rehab fields on reputation.

Revision ID: 0033_reputation_pack
Revises: 0032_bilateral_binding_ids
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_reputation_pack"
down_revision = "0032_bilateral_binding_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reputation", sa.Column("last_incident_at", sa.DateTime(), nullable=True))
    op.add_column("reputation", sa.Column("last_incident_kind", sa.String(32), nullable=True))
    op.add_column("reputation", sa.Column("onchain_packed_at", sa.DateTime(), nullable=True))
    op.add_column("reputation", sa.Column("onchain_packed_score", sa.Float(), nullable=True))
    op.add_column("reputation", sa.Column("onchain_pack_tx", sa.String(128), nullable=True))
    op.add_column("reputation", sa.Column("dividend_weight", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("reputation", "dividend_weight")
    op.drop_column("reputation", "onchain_pack_tx")
    op.drop_column("reputation", "onchain_packed_score")
    op.drop_column("reputation", "onchain_packed_at")
    op.drop_column("reputation", "last_incident_kind")
    op.drop_column("reputation", "last_incident_at")
