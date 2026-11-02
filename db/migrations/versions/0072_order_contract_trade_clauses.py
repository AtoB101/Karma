"""Foreign-trade clause template: optional order-term columns.

Adds optional trade clauses to ``task_contracts`` (quality / inspection /
shipment / delivery / penalty / arbitration). When set, they enter the canonical
terms hash and therefore the on-chain ``scopeHash`` anchor.

Revision ID: 0072_order_contract_trade_clauses
Revises: 0071_order_contract_signatures
Create Date: 2026-11-03
"""
from alembic import op

revision = "0072_order_contract_trade_clauses"
down_revision = "0071_order_contract_signatures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in (
        "quality_standard",
        "inspection_standard",
        "shipment_terms",
        "delivery_criteria",
        "penalty",
        "arbitration_rules",
    ):
        op.execute(f"ALTER TABLE task_contracts ADD COLUMN IF NOT EXISTS {col} TEXT")


def downgrade() -> None:
    for col in (
        "quality_standard",
        "inspection_standard",
        "shipment_terms",
        "delivery_criteria",
        "penalty",
        "arbitration_rules",
    ):
        op.execute(f"ALTER TABLE task_contracts DROP COLUMN IF EXISTS {col}")
