"""操作台的收益口径：把 services/economy_policy 那份公开口径原样交给页面。

和 ``console_caps`` 一样，这个接口不判定任何权限 —— 它说的是「平台公布的收益
标准是什么」，不是「你有没有资格」。资格在各自的闸门上（``require_*`` /
``arbitration_rules``），这里只负责让页面上的数字和后端参数**只有一处来源**。

任何已登录身份都能读：这是公示，不是机密。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from api.middleware.auth import get_current_agent_id
from services import economy_policy

router = APIRouter()


@router.get("")
async def get_economy_policy(
    case_value: float | None = Query(
        default=None, ge=0.0, le=1_000_000_000.0,
        description="样例案值（USDC）；留空用平台默认样例",
    ),
    _: str = Depends(get_current_agent_id),
) -> dict[str, Any]:
    """平台公布的验证者 / 仲裁员收益口径。``status=policy-preview`` = 口径已定、钱还没按它走。"""
    return economy_policy.snapshot(
        economy_policy.SAMPLE_CASE_VALUE_USDC if case_value is None else case_value
    )
