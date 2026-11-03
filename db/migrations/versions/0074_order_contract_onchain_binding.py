"""Order contract on-chain anchor: add ``onchain_binding_id`` to task_contracts.

The bilateral bind path writes the chain binding id back to the contract row so
``revise`` can lock after anchoring and ``/anchor`` can read the chain directly
even when no settlement row exists yet.

Revision ID: 0074_order_contract_onchain_binding
Revises: 0073_order_contract_revision
Create Date: 2026-11-03
"""
from alembic import op

revision = "0074_order_contract_onchain_binding"
down_revision = "0073_order_contract_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS onchain_binding_id INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE task_contracts DROP COLUMN IF EXISTS onchain_binding_id")
