"""Order contract version history: add ``task_contract_versions`` table.

Snapshot the contract on every ``revise`` so the terms version anchored on-chain
can always be reconstructed for dispute resolution.

Revision ID: 0075_order_contract_version_history
Revises: 0074_order_contract_onchain_binding
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0075_order_contract_version_history"
down_revision = "0074_order_contract_onchain_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_contract_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.String(length=64),
            sa.ForeignKey("task_contracts.task_id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("terms_hash", sa.String(length=64), nullable=True),
        sa.Column("terms", sa.JSON(), nullable=False),
        sa.Column("worker_agent_id", sa.String(length=64), nullable=True),
        sa.Column("contract_status", sa.String(length=24), nullable=True),
        sa.Column("buyer_signature", sa.String(length=256), nullable=True),
        sa.Column("buyer_address", sa.String(length=42), nullable=True),
        sa.Column("worker_signature", sa.String(length=256), nullable=True),
        sa.Column("worker_public_key", sa.String(length=256), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("task_id", "version", name="uq_task_contract_version"),
    )
    op.create_index(
        "ix_task_contract_versions_task_id",
        "task_contract_versions",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_contract_versions_task_id", table_name="task_contract_versions")
    op.drop_table("task_contract_versions")
