"""Runtime daily spend persistence + identity wallet binding.

Revision ID: 0021_runtime_daily_spend_wallet
Revises: 0020_agent_automation_policies
"""

from alembic import op
import sqlalchemy as sa

revision = "0021_runtime_daily_spend_wallet"
down_revision = "0020_agent_automation_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_key_daily_spend",
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("spend_date", sa.String(length=10), nullable=False),
        sa.Column("amount_used", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key_id", "spend_date"),
    )
    op.create_index("ix_runtime_key_daily_spend_key_id", "runtime_key_daily_spend", ["key_id"])

    with op.batch_alter_table("identity_profiles") as batch_op:
        batch_op.add_column(sa.Column("bound_wallet_address", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("identity_profiles") as batch_op:
        batch_op.drop_column("bound_wallet_address")
    op.drop_index("ix_runtime_key_daily_spend_key_id", table_name="runtime_key_daily_spend")
    op.drop_table("runtime_key_daily_spend")
