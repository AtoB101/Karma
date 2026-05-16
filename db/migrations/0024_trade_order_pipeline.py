"""Trade order pipeline — voucher.task_id + trade_orders audit.

Revision ID: 0024_trade_order_pipeline
Revises: 0023_phase1_preauth_payment_code
"""

from alembic import op
import sqlalchemy as sa

revision = "0024_trade_order_pipeline"
down_revision = "0023_phase1_preauth_payment_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vouchers", sa.Column("task_id", sa.String(length=64), nullable=True))
    op.create_index("ix_vouchers_task_id", "vouchers", ["task_id"])

    op.add_column(
        "agent_automation_policies",
        sa.Column("auto_execute_pipeline", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "trade_orders",
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("voucher_id", sa.String(length=64), nullable=True),
        sa.Column("buyer_identity_id", sa.String(length=64), nullable=False),
        sa.Column("seller_identity_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_text", sa.Text(), nullable=False),
        sa.Column("decomposed_spec", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index("ix_trade_orders_task_id", "trade_orders", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_trade_orders_task_id", table_name="trade_orders")
    op.drop_table("trade_orders")
    op.drop_column("agent_automation_policies", "auto_execute_pipeline")
    op.drop_index("ix_vouchers_task_id", table_name="vouchers")
    op.drop_column("vouchers", "task_id")
