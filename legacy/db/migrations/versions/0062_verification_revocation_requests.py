"""合规撤销：新建 verification_revocation_requests 表。

背景（2026-10-08 审计 O4）
--------------------------
企业与个体户认证一旦 verified 就是终态 —— 正常复核路径没有出边（对：一名复核员不该能
单独打掉别人的认证）。但「永远不能撤销」对消费者不负责。这里给撤销开一条只对
verified 生效的边，闸门是「复核员两人（发起 + 确认）」或「运维白名单单人」，申请本身落这张表，
带 24h TTL，见 services/compliance_revocation.py。

CREATE TABLE IF NOT EXISTS 的原因与 0060/0061 相同：应用 lifespan 里的
``Base.metadata.create_all`` 可能已经建出这张表，迁移再来一次会撞
``DuplicateTableError``。

Revision ID: 0062_verification_revocation_requests
Revises: 0061_runtime_key_secret_rotation
Create Date: 2026-10-08
"""
from alembic import op

revision = "0062_verification_revocation_requests"
down_revision = "0061_runtime_key_secret_rotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS verification_revocation_requests ("
        " revocation_id VARCHAR(64) PRIMARY KEY,"
        " target_kind VARCHAR(24) NOT NULL,"
        " target_id VARCHAR(128) NOT NULL,"
        " proposed_by VARCHAR(128) NOT NULL,"
        " reason VARCHAR(2000) NOT NULL,"
        " proposed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " confirmed_by VARCHAR(128),"
        " confirmed_at TIMESTAMP,"
        " status VARCHAR(16) NOT NULL DEFAULT 'pending'"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_verification_revocation_requests_target_id "
        "ON verification_revocation_requests (target_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS verification_revocation_requests")
