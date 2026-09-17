"""平台级权限闸门：谁能动刹车、谁能审争议、谁能发治理身份。

背景（2026-09-17 全量复核）：

* ``/v1/security`` 下 20 多个端点此前只挂了「已登录」（``get_current_agent_id``），
  于是**任何一个普通身份**都能：
    - ``POST /v1/security/runtime/safety-mode`` 把整个平台停摆；
    - 改安全阈值策略、走变更审批流、回滚；
    - 读平台资金面（``GET /v1/security/funds-overview``）与运维告警。
* 仲裁池此前没有任何白名单校验，任何身份都能把**别人**加进仲裁池（详见
  ``api/routes/arbitration.py``），``ARBITRATOR_ACTOR_IDS`` 这条生产门禁
  实际上只有小程序端在读 —— 是「假安全」。

这里把三类角色拆开、互不隐含，全部走 ``.env`` 白名单，**默认谁都不给**：

==============  ==========================================
角色            环境变量
==============  ==========================================
平台管理员      ``ADMIN_ACTOR_IDS``
争议仲裁员      ``ARBITRATOR_ACTOR_IDS``
治理身份发放方  ``GOVERNANCE_VERIFIER_IDS``
==============  ==========================================

白名单里的 id 是 **agent/api-key 维度**的 actor id（``get_current_agent_id`` 的返回值），
不是 ``kid_`` 身份号 —— 两者在 ``services/identity_actor.py`` 里有明确的映射规则。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from api.middleware.auth import (
    get_current_agent_id,
    resolve_actor_id_with_dev_fallback,
    resolve_agent_id_from_request,
)
from config.settings import settings


def admin_actor_ids() -> set[str]:
    return settings.admin_actor_id_set()


def arbitrator_actor_ids() -> set[str]:
    return settings.arbitrator_actor_id_set()


def governance_verifier_ids() -> set[str]:
    return settings.governance_verifier_id_set()


def _require(actor_id: str, allow: set[str], *, what: str, env_var: str) -> str:
    if not allow or actor_id not in allow:
        raise HTTPException(
            status_code=403,
            detail="%s requires an actor id listed in %s" % (what, env_var),
        )
    return actor_id


async def require_admin_actor(agent_id: str = Depends(get_current_agent_id)) -> str:
    """平台管理员：刹车、安全阈值策略、平台资金面、运维告警。"""
    return _require(
        agent_id,
        admin_actor_ids(),
        what="admin controls",
        env_var="ADMIN_ACTOR_IDS",
    )


async def require_arbitrator_actor(agent_id: str = Depends(get_current_agent_id)) -> str:
    """争议仲裁员：只用于仲裁池的入池与投票，不能开刹车。"""
    return _require(
        agent_id,
        arbitrator_actor_ids(),
        what="arbitration pool",
        env_var="ARBITRATOR_ACTOR_IDS",
    )


async def require_arbitration_operator(agent_id: str = Depends(get_current_agent_id)) -> str:
    """仲裁运维动作（派庭、执行裁决、读运维报表）：仲裁员白名单 ∪ 管理员白名单。"""
    return _require(
        agent_id,
        arbitrator_actor_ids() | admin_actor_ids(),
        what="arbitration operations",
        env_var="ARBITRATOR_ACTOR_IDS or ADMIN_ACTOR_IDS",
    )


async def require_governance_verifier(agent_id: str = Depends(get_current_agent_id)) -> str:
    """治理身份发放方：给自己或他人开 verifier / arbitrator 档案。"""
    return _require(
        agent_id,
        governance_verifier_ids(),
        what="governance role grants",
        env_var="GOVERNANCE_VERIFIER_IDS",
    )


# ---------------------------------------------------------------------------
# 调用者身份（供证据包归属这类「路由内自行判定」的场景复用）
# ---------------------------------------------------------------------------

def caller_actor_id(request: Request) -> str | None:
    # Runtime Gateway 委托进来的请求把已验身份盖在 request.state 上，
    # 必须先认它，否则运维岗走 /runtime/* 会被当成普通调用者。
    actor = resolve_agent_id_from_request(request) or resolve_actor_id_with_dev_fallback(request)
    return actor.strip() if actor and actor.strip() else None


def caller_is_privileged(request: Request) -> bool:
    """调用者是否属于管理员/仲裁员白名单（平台运维岗）。"""
    actor = caller_actor_id(request)
    if not actor:
        return False
    return actor in admin_actor_ids() or actor in arbitrator_actor_ids()
