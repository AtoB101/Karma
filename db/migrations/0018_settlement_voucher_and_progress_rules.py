"""P0–P2: settlement voucher link, delivery deadline, progress rule JSON on vouchers/settlements.

Revision ID: 0018_settlement_voucher_and_progress_rules
Revises: 0017_settlement_transition_audits
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_settlement_voucher_and_progress_rules"
down_revision = "0017_settlement_transition_audits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vouchers", sa.Column("progress_rule_spec", sa.JSON(), nullable=True))
    op.add_column(
        "settlements",
        sa.Column("voucher_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "settlements",
        sa.Column("delivery_deadline_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "settlements",
        sa.Column("progress_rule_spec", sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        "fk_settlements_voucher_id",
        "settlements",
        "vouchers",
        ["voucher_id"],
        ["voucher_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_settlements_voucher_id", "settlements", type_="foreignkey")
    op.drop_column("settlements", "progress_rule_spec")
    op.drop_column("settlements", "delivery_deadline_at")
    op.drop_column("settlements", "voucher_id")
    op.drop_column("vouchers", "progress_rule_spec")
