"""P1 agent onboarding fields: identity class, owner bind, boundary hash, readiness.

Revision ID: 0031_agent_p1_onboarding
Revises: 0030_identity_did_projection
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_agent_p1_onboarding"
down_revision = "0030_identity_did_projection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("identity_class", sa.String(length=32), nullable=True))
    op.add_column("agents", sa.Column("owner_identity_id", sa.String(length=128), nullable=True))
    op.add_column("agents", sa.Column("boundary_hash", sa.String(length=80), nullable=True))
    op.add_column(
        "agents",
        sa.Column("p1_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agents",
        sa.Column("onboarding_meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_agents_owner_identity_id", "agents", ["owner_identity_id"])
    op.create_index("ix_agents_identity_class", "agents", ["identity_class"])
    op.create_index("ix_agents_p1_ready", "agents", ["p1_ready"])


def downgrade() -> None:
    op.drop_index("ix_agents_p1_ready", table_name="agents")
    op.drop_index("ix_agents_identity_class", table_name="agents")
    op.drop_index("ix_agents_owner_identity_id", table_name="agents")
    op.drop_column("agents", "onboarding_meta")
    op.drop_column("agents", "p1_ready")
    op.drop_column("agents", "boundary_hash")
    op.drop_column("agents", "owner_identity_id")
    op.drop_column("agents", "identity_class")
