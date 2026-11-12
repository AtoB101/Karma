"""刹车迟滞：runtime_safety_mode 记录最近一次**人工**放闸的时刻。

背景（2026-10-13 线上实测）
---------------------------
``runtime_safety_mode`` 的自动刹车（``api/routes/security.py`` 里
``should_auto_brake`` -> ``set_runtime_safety_mode_persisted``）只看告警报表里的
「结算迁移拒绝率」。而报表是**往后看窗口**的（运维轮询器默认 window=60 分钟），
于是出现了一个自锁：

    一次拒绝尖峰把闸拉下 -> 人看清楚、手动清闸 -> 窗口里那批**旧**拒绝还在 ->
    下一轮轮询（几分钟后）用同一批证据把闸原样拉回去。

结果就是人工清闸等于白清，谁也跑不完一笔测试网闭环（实测 02:43 清、02:45 跳回）。

修法分两半：一半在 ``services/security_monitoring.py``（把「链上腿失败」这类会被
autosettle 反复重试的拒绝从拒绝率里摘出去，另立 chain-gate 告警），另一半就是这一列
—— 人工放闸时盖个时间戳，自动刹车只认**比它更晚发生**的拒绝。

老行默认 NULL = 从没有过人工放闸记录，行为与升级前完全一致（该刹车照样刹）。
原生 ``ADD COLUMN IF NOT EXISTS`` 的原因与 0060-0064 相同：应用 lifespan 里的
``Base.metadata.create_all`` 可能先建出这一列，迁移再来一次会撞重复错误。

Revision ID: 0065_runtime_safety_manual_override
Revises: 0064_verifier_bond_and_slash
Create Date: 2026-10-13
"""
from alembic import op

revision = "0065_runtime_safety_manual_override"
down_revision = "0064_verifier_bond_and_slash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 列定义与 ``db/models/orm.py`` 的 ``RuntimeSafetyModeModel.manual_override_at``
    # 逐字对应（TIMESTAMP WITHOUT TIME ZONE / nullable），改一边必须改另一边。
    op.execute(
        "ALTER TABLE runtime_safety_mode "
        "ADD COLUMN IF NOT EXISTS manual_override_at TIMESTAMP WITHOUT TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE runtime_safety_mode DROP COLUMN IF EXISTS manual_override_at")
