"""刹车开关落库：安全模式 / 运维暂停不再随重启清零。

背景（2026-10-01 安全审计）
---------------------------
``services/runtime_safety.py`` 的 ``_STATE`` 是**进程内**变量：

1. **重启即清零** —— ``docker compose up -d --force-recreate app``（或者容器 OOM
   重启）之后，之前手动或自动拉下的刹车自动弹回「关」。它在最需要它的时刻失效。
2. **多 worker 各记一份** —— 一个 worker 拉下的刹车，另一个 worker 照常住放行。
   ``deploy/Dockerfile.api`` 里写的正是 ``--workers 4``；0058（nonce 台账）
   已经因为同一件事吃过一次亏，那份迁移的说明可以对照着看。

新表只存**开关本身**，单行（``id=1``）。容量锚的遥测
（``last_anchor_audit_at`` / ``total_locked_usdc`` / ``total_bill_credits``）
每次审计重算，不进库 —— 否则每一笔动钱的请求都会多写一次库。

为什么用原生 SQL + IF NOT EXISTS
--------------------------------
这条迁移第一次上线时就撞上了 —— 而且是**真的红了 CI**（run 36895559445）：

    部署顺序是「拉代码 → 跑迁移 → 重建容器」，但**应用自己也会建表**
    （``db/session.py::init_db`` 走 ``Base.metadata.create_all``，在 lifespan 里
    每次启动都跑）。只要新代码的容器先起来过一次（手动 recreate、崩溃重启、
    机器 reboot 后自启），``runtime_safety_mode`` 就已经被 create_all 建出来了；
    迁移再来一次 ``CREATE TABLE`` 就是
    ``asyncpg.exceptions.DuplicateTableError: relation "runtime_safety_mode"
    already exists``，而这一步失败会让**整次部署失败**。

    ``create_all`` 和 alembic 谁先到是谁也保证不了的事（0059 的索引就是同一类
    问题）。所以这里跟 0059 用同一个办法：原生 DDL + IF NOT EXISTS —— 表已经在
    就跳过，不在就建，两种情况都把版本推进到 0060。

不带外键、不改既有列、不迁移数据；下线时直接 drop 即可。
写入用**独立会话当场提交**，不借业务请求的事务（那些调用点有的正处在半截业务
写入当中，借它们的会话提交会把半截业务带上，跟着回滚又会把刹车丢掉）。
详见 ``services/runtime_safety.py`` 的落库段落。

Revision ID: 0060_runtime_safety_mode
Revises: 0059_autosettle_and_audit_indexes
Create Date: 2026-10-01
"""
from alembic import op

revision = "0060_runtime_safety_mode"
down_revision = "0059_autosettle_and_audit_indexes"
branch_labels = None
depends_on = None

#: 列定义与 ``db/models/orm.py`` 的 ``RuntimeSafetyModeModel`` 逐字对应。
#: 列名/类型两边对不上就会在这张表上留下「模型和库不一致」的隐患，改一边必须改另一边。
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS runtime_safety_mode (
    id INTEGER NOT NULL,
    enabled BOOLEAN DEFAULT false NOT NULL,
    reason VARCHAR(512),
    triggered_by VARCHAR(128),
    triggered_at TIMESTAMP WITHOUT TIME ZONE,
    pause_new_lock BOOLEAN DEFAULT false NOT NULL,
    pause_new_authorization BOOLEAN DEFAULT false NOT NULL,
    pause_new_task BOOLEAN DEFAULT false NOT NULL,
    pause_new_settlement BOOLEAN DEFAULT false NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id)
)
"""


def upgrade() -> None:
    op.execute(CREATE_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS runtime_safety_mode")
