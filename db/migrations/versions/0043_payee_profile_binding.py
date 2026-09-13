"""Payment ledger: attribute the payee side of an order to a sub-identity.

收付中心要按子身份拆「收入 / 支出」，但此前只有付款方一侧记录了角色档案 id
（settlements.profile_id / escrow_bindings.buyer_profile_id）。这里给收款方一侧
补上同样的归属字段，全部可空 —— 老数据、老 agent 行为不变。

Revision ID: 0043_payee_profile_binding
Revises: 0042_allowance_escrow
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0043_payee_profile_binding"
down_revision = "0042_allowance_escrow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settlements",
        sa.Column("worker_profile_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "escrow_bindings",
        sa.Column("seller_profile_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "vouchers",
        sa.Column("seller_profile_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vouchers", "seller_profile_id")
    op.drop_column("escrow_bindings", "seller_profile_id")
    op.drop_column("settlements", "worker_profile_id")