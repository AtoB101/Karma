"""Runtime Key table for Agent Runtime Gateway (public SDK + Console).

Revision ID: 0019_runtime_keys
Revises: 0018_settlement_voucher_and_progress_rules
"""

from alembic import op
import sqlalchemy as sa

revision = "0019_runtime_keys"
down_revision = "0018_settlement_voucher_and_progress_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_keys",
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=256), nullable=False),
        sa.Column("wallet_address", sa.String(length=128), nullable=False),
        sa.Column("karma_identity_id", sa.String(length=128), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("single_limit", sa.Float(), nullable=False),
        sa.Column("daily_limit", sa.Float(), nullable=False),
        sa.Column("expire_at", sa.DateTime(), nullable=False),
        sa.Column("agent_name", sa.String(length=256), nullable=False),
        sa.Column("agent_binding", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key_id"),
    )
    op.create_index("ix_runtime_keys_wallet_address", "runtime_keys", ["wallet_address"])
    op.create_index("ix_runtime_keys_karma_identity_id", "runtime_keys", ["karma_identity_id"])


def downgrade() -> None:
    op.drop_index("ix_runtime_keys_karma_identity_id", table_name="runtime_keys")
    op.drop_index("ix_runtime_keys_wallet_address", table_name="runtime_keys")
    op.drop_table("runtime_keys")
