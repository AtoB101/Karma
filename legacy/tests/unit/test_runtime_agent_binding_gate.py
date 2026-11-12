"""Runtime Key「必须指名 agent + 必须过匹配码」这条闸门的判据。

生产口径（``RUNTIME_REQUIRE_AGENT_BINDING=true``）下不存在「不记名钥匙」：
光拿到 ``KRM_RT_…`` 什么都做不了 —— 服务端只认「agent 公钥 + 逐请求签名」，
而公钥要主人在操作台输码才绑得上。

这里钉的是那条判据本身（唯一口径），网关和测试都走它，避免两处漂移。
"""
from __future__ import annotations

from config.settings import Settings
from services.runtime_key_service import pending_activation_block

GATE_ON = {"require_agent_binding": True}


def test_the_safe_value_is_the_default() -> None:
    """旋钮默认必须是「开」：漏配的部署也拿到安全的那一侧。"""
    assert Settings.model_fields["runtime_require_agent_binding"].default is True


def test_agent_bound_key_with_a_public_key_passes() -> None:
    assert (
        pending_activation_block(
            key_binding="agent", agent_public_key="cHVi", **GATE_ON
        )
        is None
    )


def test_pending_key_is_refused_until_the_code_is_entered() -> None:
    reason = pending_activation_block(
        key_binding="agent_pending", agent_public_key=None, **GATE_ON
    )
    assert reason and "activation code" in reason


def test_bearer_key_is_refused_when_the_gate_is_on() -> None:
    reason = pending_activation_block(key_binding="service", agent_public_key=None, **GATE_ON)
    assert reason and "bearer key" in reason


def test_agent_marked_without_a_public_key_is_refused_when_the_gate_is_on() -> None:
    reason = pending_activation_block(key_binding="agent", agent_public_key=None, **GATE_ON)
    assert reason and "no agent public key" in reason


def test_missing_key_binding_is_treated_as_a_bearer_key() -> None:
    """脏数据（key_binding 为空）按最坏情况算，不放行。"""
    reason = pending_activation_block(key_binding=None, agent_public_key=None, **GATE_ON)
    assert reason and "bearer key" in reason


def test_the_pure_function_defaults_to_tolerant() -> None:
    """默认参数保持宽松：老调用点的语义不变，收紧口径必须显式传参。"""
    assert pending_activation_block(key_binding="service", agent_public_key=None) is None
