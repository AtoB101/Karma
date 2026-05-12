"""Add capacity and voucher tables

Revision ID: 0003_capacity_and_voucher
Revises: 0002_onchain_fields
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_capacity_and_voucher"
down_revision = "0002_onchain_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capacity",
        sa.Column("identity_id", sa.String(64), primary_key=True),
        sa.Column("total_locked_usdc", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_bill_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("available_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("reserved_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("in_progress_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("confirmed_progress_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("disputed_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("pending_settlement_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("burned_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("released_credits", sa.Float, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "vouchers",
        sa.Column("voucher_id", sa.String(64), primary_key=True),
        sa.Column("buyer_identity_id", sa.String(64), nullable=False),
        sa.Column("seller_identity_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USDC"),
        sa.Column("bill_credit_amount", sa.Float, nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("task_description_hash", sa.String(128), nullable=False),
        sa.Column("progress_rule_hash", sa.String(128), nullable=False),
        sa.Column("evidence_requirement_hash", sa.String(128), nullable=False),
        sa.Column("expiry_time", sa.DateTime, nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("buyer_signature", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="created"),
        sa.Column("buyer_sub_identity_id", sa.String(64)),
        sa.Column("seller_sub_identity_id", sa.String(64)),
        sa.Column("accepted_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("buyer_identity_id", "nonce", name="uq_voucher_buyer_nonce"),
    )

    op.create_index("ix_vouchers_seller_status", "vouchers", ["seller_identity_id", "status"])
    op.create_index("ix_vouchers_buyer_status", "vouchers", ["buyer_identity_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_vouchers_buyer_status", table_name="vouchers")
    op.drop_index("ix_vouchers_seller_status", table_name="vouchers")
    op.drop_table("vouchers")
    op.drop_table("capacity")

