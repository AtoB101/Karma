"""Identity verification via real-name/liveness providers: 主身份核验接第三方服务商。

`identity_verifications` 加一列 ``provider``（JSON，可空）：

* 起因：实名 / 活体不该由 Karma 自建（红线是服务端永不接收证件 / 人脸明文）。
  接一家服务商之后，浏览器直连服务商，Karma 只收「结论 + 会话号」。
* 这一列存这次核验走的是哪家、我们签发的会话号、服务商那边的会话号，
  以及最近若干条事件（验签通过 / 回查结果 / 是否置位），供审计回溯。
* 老行保持 NULL，业务代码按空字典读，不影响既有数据；回滚只是丢这一列。

Revision ID: 0047_identity_provider
Revises: 0046_skill_developers
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0047_identity_provider"
down_revision = "0046_skill_developers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "identity_verifications",
        sa.Column("provider", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("identity_verifications", "provider")
