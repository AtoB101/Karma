"""Identity DID projection fields (on-chain DID as SSOT).

Revision ID: 0030_identity_did_projection
Revises: 0029_verifier_network
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_identity_did_projection"
down_revision = "0029_verifier_network"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widen identity_id to fit did:karma:0x… (51 chars) with headroom
    op.alter_column(
        "identity_profiles",
        "identity_id",
        existing_type=sa.String(64),
        type_=sa.String(128),
        existing_nullable=False,
    )
    op.add_column("identity_profiles", sa.Column("did_agent_address", sa.String(64), nullable=True))
    op.add_column("identity_profiles", sa.Column("on_chain_did", sa.String(66), nullable=True))
    op.add_column(
        "identity_profiles",
        sa.Column("projection_readonly", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("identity_profiles", sa.Column("projection_source", sa.String(32), nullable=True))
    op.create_index("ix_identity_profiles_did_agent", "identity_profiles", ["did_agent_address"])
    op.create_unique_constraint("uq_identity_profiles_on_chain_did", "identity_profiles", ["on_chain_did"])


def downgrade() -> None:
    op.drop_constraint("uq_identity_profiles_on_chain_did", "identity_profiles", type_="unique")
    op.drop_index("ix_identity_profiles_did_agent", table_name="identity_profiles")
    op.drop_column("identity_profiles", "projection_source")
    op.drop_column("identity_profiles", "projection_readonly")
    op.drop_column("identity_profiles", "on_chain_did")
    op.drop_column("identity_profiles", "did_agent_address")
    op.alter_column(
        "identity_profiles",
        "identity_id",
        existing_type=sa.String(128),
        type_=sa.String(64),
        existing_nullable=False,
    )
