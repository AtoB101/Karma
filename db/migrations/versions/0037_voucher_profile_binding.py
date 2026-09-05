"""Voucher profile binding — tag vouchers with the role profile that created them.

Revision ID: 0037_voucher_profile_binding
Revises: 0036_identity_disclosures
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0037_voucher_profile_binding"
down_revision = "0036_identity_disclosures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vouchers", sa.Column("profile_id", sa.String(64), nullable=True))
    op.create_index("ix_vouchers_profile_id", "vouchers", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_vouchers_profile_id", table_name="vouchers")
    op.drop_column("vouchers", "profile_id")
