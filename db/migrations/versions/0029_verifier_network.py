"""Verifier Network — decentralized verification tables.

Revision ID: 0029_verifier_network
Revises: 0028_human_not_present_policy
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_verifier_network"
down_revision = "0028_human_not_present_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── verifier_nodes ───────────────────────────────────────────────
    op.create_table(
        "verifier_nodes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("wallet_address", sa.String(42), nullable=False),
        sa.Column("stake_amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("reputation_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_attestations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_attestations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("endpoint_url", sa.String(2048), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_verifier_nodes_wallet_address", "verifier_nodes", ["wallet_address"], unique=True)

    # ── attestations ─────────────────────────────────────────────────
    op.create_table(
        "attestations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("verifier_id", sa.String(64), nullable=False),
        sa.Column("bundle_id", sa.String(64), nullable=True),
        sa.Column("bundle_cid", sa.String(256), nullable=True),
        sa.Column("decision", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("checks_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eip712_signature", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_attestations_task_id", "attestations", ["task_id"])
    op.create_foreign_key(
        "fk_attestations_verifier_id",
        "attestations",
        "verifier_nodes",
        ["verifier_id"],
        ["id"],
    )

    # ── challenges ───────────────────────────────────────────────────
    op.create_table(
        "challenges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("bundle_id", sa.String(64), nullable=True),
        sa.Column("raised_by", sa.String(128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("window_end", sa.DateTime(), nullable=True),
        sa.Column("quorum_size", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_challenges_task_id", "challenges", ["task_id"])


def downgrade() -> None:
    op.drop_table("challenges")
    op.drop_table("attestations")
    op.drop_table("verifier_nodes")
