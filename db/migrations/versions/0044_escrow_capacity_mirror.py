"""Allowance escrow: mirror v2 commitments into the master capacity ledger.

v2 锁仓是非托管的：钱留在用户自己钱包里，链上只有一条 commit() 承诺。但这条承诺
此前只写进 allowance_commits，没有记进 capacity 台账 —— 于是用户「锁仓成功」之后，
付款码 / 任务合同 / agent request-voucher / 子身份额度分配都会以为自己一分钱都没有，
直接 409。这里补上镜像列，并把历史承诺一次性回填进台账。

Revision ID: 0044_escrow_capacity_mirror
Revises: 0043_payee_profile_binding
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0044_escrow_capacity_mirror"
down_revision = "0043_payee_profile_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "allowance_commits",
        sa.Column("capacity_credited_usdc", sa.Float(), nullable=False, server_default="0"),
    )

    conn = op.get_bind()
    # 每条未撤销的承诺能支配的额度 = amount - spent。
    conn.execute(
        sa.text(
            """
            UPDATE allowance_commits
               SET capacity_credited_usdc =
                   CASE WHEN state = 'revoked' THEN 0
                        ELSE GREATEST(amount_usdc - COALESCE(spent_usdc, 0), 0) END
            """
        )
    )
    # 为每个身份补一条 / 补足 capacity 台账；不动已经存在的责任桶。
    conn.execute(
        sa.text(
            """
            INSERT INTO capacity (identity_id, total_locked_usdc, total_bill_credits,
                                  available_credits, reserved_credits, in_progress_credits,
                                  confirmed_progress_credits, disputed_credits,
                                  pending_settlement_credits, burned_credits,
                                  released_credits, updated_at)
            SELECT identity_id, SUM(credited), SUM(credited), SUM(credited), 0, 0, 0, 0, 0, 0, 0, NOW()
              FROM (SELECT identity_id, capacity_credited_usdc AS credited
                      FROM allowance_commits) AS mirrored
             WHERE credited > 0
             GROUP BY identity_id
            ON CONFLICT (identity_id) DO UPDATE
               SET available_credits = capacity.available_credits + EXCLUDED.available_credits,
                   total_bill_credits = capacity.total_bill_credits + EXCLUDED.total_bill_credits,
                   total_locked_usdc = capacity.total_locked_usdc + EXCLUDED.total_locked_usdc,
                   updated_at = NOW()
            """
        )
    )


def downgrade() -> None:
    op.drop_column("allowance_commits", "capacity_credited_usdc")
