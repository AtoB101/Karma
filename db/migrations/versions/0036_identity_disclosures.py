"""Identity disclosures — authorized access to private (enterprise) profile ledgers.

Revision ID: 0036_identity_disclosures
Revises: 0035_profile_binding
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_identity_disclosures"
down_revision = "0035_profile_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_disclosures",
        sa.Column("disclosure_id", sa.String(64), primary_key=True),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("authorized_identity_id", sa.String(128), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False, server_default="transaction"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_identity_disclosures_profile_id", "identity_disclosures", ["profile_id"])
    op.create_index("ix_identity_disclosures_authorized_identity_id", "identity_disclosures", ["authorized_identity_id"])
    op.create_index("ix_identity_disclosures_task_id", "identity_disclosures", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_identity_disclosures_task_id", table_name="identity_disclosures")
    op.drop_index("ix_identity_disclosures_authorized_identity_id", table_name="identity_disclosures")
    op.drop_index("ix_identity_disclosures_profile_id", table_name="identity_disclosures")
    op.drop_table("identity_disclosures")
