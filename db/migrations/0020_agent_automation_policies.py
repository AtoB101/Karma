"""Agent automation policy — fund limits and permissions before Runtime Key mint.

Revision ID: 0020_agent_automation_policies
Revises: 0019_runtime_keys
"""

from alembic import op
import sqlalchemy as sa

revision = "0020_agent_automation_policies"
down_revision = "0019_runtime_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_automation_policies",
        sa.Column("karma_identity_id", sa.String(length=128), nullable=False),
        sa.Column("auto_enabled", sa.Boolean(), nullable=False),
        sa.Column("single_limit", sa.Float(), nullable=False),
        sa.Column("daily_limit", sa.Float(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("high_risk_mode", sa.String(length=32), nullable=False),
        sa.Column("responsibility_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_actor", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("karma_identity_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_automation_policies")
