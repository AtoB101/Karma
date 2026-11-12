"""给链上绑定补上「它落在哪台托管合约上」。

问题（2026-09-20 资金细节深测 F11）
-----------------------------------
``escrow_bindings`` 从来没记过合约地址：所有链上动作（submit / finalize /
cancel / 读状态）都打向 ``ALLOWANCE_ESCROW_ADDRESS`` **当前**指向的那台合约。
把 v2 换成 v3 之后：

* 46 条历史绑定全在 v2 上，其中任何一条再被 autosettle 碰一次（finalize /
  cancel）就是 UnknownBinding revert —— 钱停在买方的授权里，谁也解不开；
* 反过来，旧合约的账单 id 拿去新合约 ``available()`` 也是 revert，把
  ``/v1/settlement/{task}/lock`` 直接打成 500（实测的报错就是这个）。

本次只加一列并按买方账单回填，不改既有列、不删数据。回填不出来的历史行留空串，
读取时按「当前合约」处理 —— 与改动前的行为完全一致。

Revision ID: 0053_binding_contract_address
Revises: 0052_settlement_confirm_window
Create Date: 2026-09-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0053_binding_contract_address"
down_revision = "0052_settlement_confirm_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "escrow_bindings",
        sa.Column("contract_address", sa.String(length=64), nullable=False, server_default=""),
    )
    op.execute(
        """
        UPDATE escrow_bindings AS b
           SET contract_address = a.contract_address
          FROM allowance_commits AS a
         WHERE a.bill_id = b.buyer_bill_id
           AND COALESCE(b.contract_address, '') = ''
           AND COALESCE(a.contract_address, '') <> ''
        """
    )


def downgrade() -> None:
    op.drop_column("escrow_bindings", "contract_address")
