"""退役合约的绑定主键加合约前缀 —— 把重号的链上 id 让给当前合约。

问题（2026-09-21 F13 链上动钱实测，P0）
--------------------------------------
``escrow_bindings.binding_id`` 存的是**链上** binding id，而链上 id 是每台合约
各自计数的：v2 用到 58，v3 从 1 重新开始。于是 v3 的第 9 条绑定撞上 v2 的第 9 条：

* 链上 ``bind`` 已经成功（买方账单被占住 0.2 USDC，tx 0x181766c5…）；
* 账上 INSERT 被 ``escrow_bindings_pkey`` 打回 —— HTTP 500；
* 结果是链上多出一条谁也不认的绑定，而且**从此每一条新锁仓都会撞**。

本次只改数据：把**退役合约**（不是最近一次使用的那台）的历史行改名成
``<合约地址>:<链上 id>``，把 9 以后的裸 id 让给当前合约。退役合约那 46 条绑定
全是终态（settled / cancelled / slashed），没有一条还在钱路上。

代码侧同时收紧了写入与解析（services/chain/escrow_settlement.py）：
``local_binding_id()`` 只在裸 id 被占时才加前缀，``chain_binding_id()`` 负责还原，
``find_binding()`` 让改名前的老引用还能取到行 —— 所以以后**任何一次合约升级**
都不会再撞上历史主键，不必每次升级都手工改一遍数据。

Revision ID: 0054_binding_id_contract_namespace
Revises: 0053_binding_contract_address
Create Date: 2026-09-21
"""
from alembic import op

revision = "0054_binding_id_contract_namespace"
down_revision = "0053_binding_contract_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE escrow_bindings AS b
           SET binding_id = b.contract_address || ':' || b.binding_id
         WHERE COALESCE(b.contract_address, '') <> ''
           AND POSITION(':' IN b.binding_id) = 0
           AND b.contract_address <> (
                SELECT c.contract_address
                  FROM escrow_bindings AS c
                 WHERE COALESCE(c.contract_address, '') <> ''
                 ORDER BY c.created_at DESC
                 LIMIT 1
           )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE escrow_bindings
           SET binding_id = split_part(binding_id, ':', 2)
         WHERE POSITION(':' IN binding_id) > 0
        """
    )
