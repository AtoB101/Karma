"""Persist KarmaBilateral binding / bill ids on settlements.

Revision ID: 0032_bilateral_binding_ids
Revises: 0031_agent_p1_onboarding
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_bilateral_binding_ids"
down_revision = "0031_agent_p1_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settlements", sa.Column("onchain_binding_id", sa.Integer(), nullable=True))
    op.add_column("settlements", sa.Column("onchain_buyer_bill_id", sa.Integer(), nullable=True))
    op.add_column("settlements", sa.Column("onchain_agent_bill_id", sa.Integer(), nullable=True))
    op.create_index("ix_settlements_onchain_binding_id", "settlements", ["onchain_binding_id"])


def downgrade() -> None:
    op.drop_index("ix_settlements_onchain_binding_id", table_name="settlements")
    op.drop_column("settlements", "onchain_agent_bill_id")
    op.drop_column("settlements", "onchain_buyer_bill_id")
    op.drop_column("settlements", "onchain_binding_id")
