"""Order contract signatures: dual-party signing + on-chain termsHash anchor.

Adds terms/signature columns to ``task_contracts`` so a contract can carry:

- ``terms_hash`` — canonical order terms SHA-256 (source of on-chain ``scopeHash``).
- ``contract_status`` — draft | buyer_signed | signed.
- buyer EIP-712 signature + wallet address, and worker Ed25519 signature + public key.

Native DDL + IF NOT EXISTS for the same reason as 0060: app lifespan
``Base.metadata.create_all`` may already have added these columns.

Revision ID: 0071_order_contract_signatures
Revises: 0063_spending_grant_agent_name
Create Date: 2026-11-03
"""
from alembic import op

revision = "0071_order_contract_signatures"
down_revision = "0063_spending_grant_agent_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS terms_hash VARCHAR(64)")
    op.execute(
        "ALTER TABLE task_contracts "
        "ADD COLUMN IF NOT EXISTS contract_status VARCHAR(24) NOT NULL DEFAULT 'draft'"
    )
    op.execute("ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS buyer_signature VARCHAR(256)")
    op.execute("ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS buyer_address VARCHAR(42)")
    op.execute("ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS worker_signature VARCHAR(256)")
    op.execute("ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS worker_public_key VARCHAR(256)")
    op.execute("ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS signed_at TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS terms_hash")
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS contract_status")
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS buyer_signature")
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS buyer_address")
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS worker_signature")
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS worker_public_key")
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS signed_at")
