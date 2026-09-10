"""Profile binding for runtime keys and per-profile accounting (P1 remainder).

Adds a nullable ``profile_id`` dimension to:
- runtime_keys          (agent key → profile binding)
- settlements           (per-profile settlement accounting)
- execution_receipts    (per-profile receipt accounting)
- capacity              (per-profile capacity dimension tag)

Nullable + indexed: backward compatible with existing rows that predate the
multi-profile model. Authorized-disclosure enforcement is a later phase.

Revision ID: 0035_profile_binding
Revises: 0034_identity_role_profiles
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0035_profile_binding"
down_revision = "0034_identity_role_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runtime_keys", sa.Column("profile_id", sa.String(64), nullable=True))
    op.add_column("settlements", sa.Column("profile_id", sa.String(64), nullable=True))
    op.add_column("execution_receipts", sa.Column("profile_id", sa.String(64), nullable=True))
    op.add_column("capacity", sa.Column("profile_id", sa.String(64), nullable=True))

    op.create_index("ix_runtime_keys_profile_id", "runtime_keys", ["profile_id"])
    op.create_index("ix_settlements_profile_id", "settlements", ["profile_id"])
    op.create_index("ix_execution_receipts_profile_id", "execution_receipts", ["profile_id"])
    op.create_index("ix_capacity_profile_id", "capacity", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_capacity_profile_id", table_name="capacity")
    op.drop_index("ix_execution_receipts_profile_id", table_name="execution_receipts")
    op.drop_index("ix_settlements_profile_id", table_name="settlements")
    op.drop_index("ix_runtime_keys_profile_id", table_name="runtime_keys")

    op.drop_column("capacity", "profile_id")
    op.drop_column("execution_receipts", "profile_id")
    op.drop_column("settlements", "profile_id")
    op.drop_column("runtime_keys", "profile_id")
