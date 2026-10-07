"""Karma — 操作台的能力位（capabilities）：当前这个 actor 能开哪些工作面。

为什么要有这个接口
------------------
操作台的入驻岗（仲裁台、验证者网络看板）只对 ``ARBITRATOR_ACTOR_IDS`` /
``ADMIN_ACTOR_IDS`` / ``GOVERNANCE_VERIFIER_IDS`` 白名单里的人开放。前端要做到
「不在白名单里就看不到这个入口」，就不能靠「打一下真接口、看到 403 再藏」——
那会让每个普通用户每开一次操作台就产生一串 403，混进安全告警里
``privileged_action`` 那条基线，把真信号淹掉。

这个接口只回**调用者自己**的布尔位：
- 名单本身仍然只在服务器 ``.env`` 里（仓库是公开的，白名单不进仓）；
- 前端拿到 ``false`` 就隐藏入口，拿到 ``true`` 才去读真正的数据接口。

判定权威始终在后端那三道 ``require_*`` 上（``services/actor_guards.py``）；
这里说的只是「提前知道要不要画这个按钮」，不是第二道门。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.middleware.auth import get_current_agent_id
from services.actor_guards import (
    admin_actor_ids,
    arbitrator_actor_ids,
    governance_verifier_ids,
)

router = APIRouter()


class ConsoleCapabilities(BaseModel):
    """调用者自己的工作面开关。只增不减语义：字段加人看得懂，不加权限。"""

    actor_id: str
    is_admin: bool = False
    is_arbitrator: bool = False
    can_operate_arbitration: bool = False
    is_governance_verifier: bool = False
    can_view_verifier_network: bool = False


@router.get("", response_model=ConsoleCapabilities)
async def get_console_capabilities(
    actor: str = Depends(get_current_agent_id),
) -> ConsoleCapabilities:
    """回当前 actor 的能力位。没有会话就 401（由依赖给出），不会回匿名结果。"""
    actor = (actor or "").strip()
    is_admin = actor in admin_actor_ids()
    is_arbitrator = actor in arbitrator_actor_ids()
    is_governance = actor in governance_verifier_ids()
    return ConsoleCapabilities(
        actor_id=actor,
        is_admin=is_admin,
        is_arbitrator=is_arbitrator,
        # 与 services/actor_guards.require_arbitration_operator 的口径逐字对齐：
        # 仲裁员白名单 ∪ 管理员白名单。
        can_operate_arbitration=is_admin or is_arbitrator,
        is_governance_verifier=is_governance,
        # 验证者网络是治理看板：管理员与治理发放方看得到，普通身份看不到入口。
        # （只读数据本身对已登录用户开放，这里管的是「画不画这个入口」。）
        can_view_verifier_network=is_admin or is_governance,
    )