"""Phase 2 x402 — settlement funding_source.

Revision ID: 0026_x402_funding_source
Revises: 0025_trade_pipeline_security
"""

from alembic import op
import sqlalchemy as sa

revision = "0026_x402_funding_source"
down_revision = "0025_trade_pipeline_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settlements",
        sa.Column("funding_source", sa.String(length=16), nullable=False, server_default="internal"),
    )


def downgrade() -> None:
    op.drop_column("settlements", "funding_source")
