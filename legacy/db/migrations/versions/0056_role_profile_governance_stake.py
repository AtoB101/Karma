"""治理岗的质押承诺额：verifier / arbitrator 可以凭押金开通，也跟着押金失效。

背景（2026-09-23）
------------------
``verifier`` / ``arbitrator`` 此前只有一条入口：运维把身份写进
``GOVERNANCE_VERIFIER_IDS``。这一列让「质押即开通」这条路有地方记**承诺额**：

- 开通时按下限校验（低于下限 422、没有锁仓背书 409，见 services/governance_stake.py）；
- 每次动治理权限都拿这个数与 ``capacity.total_locked_usdc`` 现算一次，
  押金被划走（含罚没）之后岗位立刻失效，不需要再维护一张状态表。

也就是说这一列**不参与任何金额计算**，钱的事实仍然只在链上与 capacity 镜像里；
它记的是「这个人当时承诺押多少」，好让在任判定有据可查。

只加一列，不带索引、不改既有列、不删数据。历史行留 0 = 当时还没有这回事
（白名单开的岗不受质押约束）。

Revision ID: 0056_role_profile_governance_stake
Revises: 0055_escrow_binding_buyer_confirm
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0056_role_profile_governance_stake"
down_revision = "0055_escrow_binding_buyer_confirm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "identity_role_profiles",
        sa.Column("stake_amount", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("identity_role_profiles", "stake_amount")
