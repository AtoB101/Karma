"""Phase 3 — payment_intents table.

Revision ID: 0027_phase3_payment_intents
Revises: 0026_x402_funding_source
"""

from alembic import op
import sqlalchemy as sa

revision = "0027_phase3_payment_intents"
down_revision = "0026_x402_funding_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_intents",
        sa.Column("intent_id", sa.String(length=64), primary_key=True),
        sa.Column("merchant_ref", sa.String(length=256), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("payer", sa.String(length=128), nullable=False),
        sa.Column("payee", sa.String(length=128), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.String(length=64), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("voucher_id", sa.String(length=64), nullable=True),
        sa.Column("ap2_mandate_digest", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payment_intents_merchant_ref", "payment_intents", ["merchant_ref"])
    op.create_index("ix_payment_intents_task_id", "payment_intents", ["task_id"])
    op.create_index("ix_payment_intents_idempotency_key", "payment_intents", ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_payment_intents_idempotency_key", table_name="payment_intents")
    op.drop_index("ix_payment_intents_task_id", table_name="payment_intents")
    op.drop_index("ix_payment_intents_merchant_ref", table_name="payment_intents")
    op.drop_table("payment_intents")
