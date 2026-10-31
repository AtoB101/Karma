"""Spending grant agent_name — friendly label for the grant list page.

The approval challenge carries the agent's display name; persist it on the
grant row so owners see a name (not just an id) in the grant list. Nullable and
additive: existing rows stay readable.

Revision ID: 0063_spending_grant_agent_name
Revises: 0062_spending_grant_events
Create Date: 2026-11-01
"""
from alembic import op

revision = "0063_spending_grant_agent_name"
down_revision = "0062_spending_grant_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE spending_grants ADD COLUMN IF NOT EXISTS agent_name VARCHAR(128)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE spending_grants DROP COLUMN IF EXISTS agent_name")