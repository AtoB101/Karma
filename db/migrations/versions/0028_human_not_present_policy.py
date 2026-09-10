"""Phase 3 — human_not_present_allowed on automation policies.

Revision ID: 0028_human_not_present_policy
Revises: 0027_phase3_payment_intents
"""

from alembic import op
import sqlalchemy as sa

revision = "0028_human_not_present_policy"
down_revision = "0027_phase3_payment_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_automation_policies",
        sa.Column(
            "human_not_present_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_automation_policies", "human_not_present_allowed")
