"""Trade pipeline security — idempotency key + pipeline version audit.

Revision ID: 0025_trade_pipeline_security
Revises: 0024_trade_order_pipeline
"""

from alembic import op
import sqlalchemy as sa

revision = "0025_trade_pipeline_security"
down_revision = "0024_trade_order_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trade_orders",
        sa.Column("launch_idempotency_key", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "trade_orders",
        sa.Column("pipeline_version", sa.String(length=32), nullable=False, server_default="v2"),
    )
    op.create_index(
        "ix_trade_orders_launch_idempotency_key",
        "trade_orders",
        ["launch_idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_trade_orders_launch_idempotency_key", table_name="trade_orders")
    op.drop_column("trade_orders", "pipeline_version")
    op.drop_column("trade_orders", "launch_idempotency_key")
