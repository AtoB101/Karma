"""Add arbitration pool/case/material/vote tables

Revision ID: 0006_arbitration_pool_and_cases
Revises: 0005_identity_profile_and_sub_identity
Create Date: 2026-05-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_arbitration_pool_and_cases"
down_revision = "0005_identity_profile_and_sub_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "arbitration_pool_members",
        sa.Column("arbitrator_identity_id", sa.String(64), primary_key=True),
        sa.Column("stake_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "arbitration_cases",
        sa.Column("case_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False, unique=True),
        sa.Column("settlement_id", sa.String(64)),
        sa.Column("opened_by", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("required_arbitrators", sa.Integer, nullable=False, server_default="3"),
        sa.Column("decided_outcome", sa.String(16)),
        sa.Column("final_partial_percent", sa.Float),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("executed_at", sa.DateTime),
    )

    op.create_table(
        "arbitration_assignments",
        sa.Column("assignment_id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("arbitrator_identity_id", sa.String(64), nullable=False),
        sa.Column("assigned_at", sa.DateTime, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="assigned"),
        sa.ForeignKeyConstraint(["case_id"], ["arbitration_cases.case_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("case_id", "arbitrator_identity_id", name="uq_arbitration_assignment"),
    )

    op.create_table(
        "arbitration_material_packages",
        sa.Column("material_id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("submitted_by", sa.String(64), nullable=False),
        sa.Column("bundle_id", sa.String(64)),
        sa.Column("progress_receipt_ids", sa.JSON, nullable=False),
        sa.Column("evidence_hashes", sa.JSON, nullable=False),
        sa.Column("package_hash", sa.String(128), nullable=False),
        sa.Column("storage_uri", sa.String(512)),
        sa.Column("format_version", sa.String(32), nullable=False, server_default="arbitration-material-v1"),
        sa.Column("submitted_at", sa.DateTime, nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["arbitration_cases.case_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("case_id", "package_hash", name="uq_arbitration_material_hash_per_case"),
    )

    op.create_table(
        "arbitration_votes",
        sa.Column("vote_id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("arbitrator_identity_id", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("partial_percent", sa.Float),
        sa.Column("rationale", sa.Text),
        sa.Column("voted_at", sa.DateTime, nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["arbitration_cases.case_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("case_id", "arbitrator_identity_id", name="uq_arbitration_vote"),
    )

    op.create_index("ix_arbitration_pool_status", "arbitration_pool_members", ["status"])
    op.create_index("ix_arbitration_case_status", "arbitration_cases", ["status"])
    op.create_index("ix_arbitration_material_case", "arbitration_material_packages", ["case_id", "submitted_at"])
    op.create_index("ix_arbitration_vote_case", "arbitration_votes", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_arbitration_vote_case", table_name="arbitration_votes")
    op.drop_index("ix_arbitration_material_case", table_name="arbitration_material_packages")
    op.drop_index("ix_arbitration_case_status", table_name="arbitration_cases")
    op.drop_index("ix_arbitration_pool_status", table_name="arbitration_pool_members")
    op.drop_table("arbitration_votes")
    op.drop_table("arbitration_material_packages")
    op.drop_table("arbitration_assignments")
    op.drop_table("arbitration_cases")
    op.drop_table("arbitration_pool_members")

