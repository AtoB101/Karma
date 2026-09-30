"""运行时密钥的 nonce 台账：重放保护 + 幂等回放，一行一次请求。

背景（2026-09-30）
------------------
并发压测（2026-09-30，见 outputs/concurrency/SUMMARY-2026-09-30.md）抓到两件事：

1. 重放保护只在**进程内存**里（``services/runtime_key_service.py::_replay``）。
   Dockerfile 写的是 ``--workers 4``，线上只是侥幸单进程；一旦多 worker，
   同一个 nonce 并行打到两个 worker 谁都拦不住。
2. 客户端拿到 504 之后**无从判断**。接单要在请求路径里等一个 Sepolia 区块
   （约 12s），nginx 一超时就断开；调用方重发只能拿到 409 duplicate ——
   既不知道上一笔成没成，也不敢再发。

所以把 nonce 落库，并多记一个状态：

* ``in_flight`` —— 有人正拿着这个 nonce 在跑；
* ``done``      —— 跑完了，第一次的响应原样存在这里，重发直接回放
                   （响应带 ``idempotent_replay: true``，不假装是新的一笔）。

同一个 nonce 配不同请求体一律 409（不管那条 nonce 是 in_flight 还是 done）。
见 services/runtime_nonce_log.py。

新表、不带外键、不改既有列、不迁移数据；下线时直接 drop 即可。

Revision ID: 0058_runtime_nonce_log
Revises: 0057_console_2fa_and_face
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0058_runtime_nonce_log"
down_revision = "0057_console_2fa_and_face"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_nonce_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="in_flight"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("key_id", "endpoint", "nonce", name="uq_runtime_nonce_log"),
    )
    op.create_index(
        "ix_runtime_nonce_log_created_at", "runtime_nonce_log", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_nonce_log_created_at", table_name="runtime_nonce_log")
    op.drop_table("runtime_nonce_log")
