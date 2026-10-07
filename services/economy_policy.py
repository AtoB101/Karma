"""收益口径（对外展示）—— 操作台「验证者身份 / 仲裁者身份」两页的唯一数据源。

为什么要有这一层
----------------
两个申请页都要摊给用户看的只有一件事：**干这份活能拿多少、要先押多少**。
这些数不能写在前端 —— 前端写死的数字和后端参数迟早对不上，用户照着页面
算出来的收益就是错的。所以口径只在这里定义一次，由
``GET /v1/console/economy-policy`` 原样交给页面。

边界（必须说清楚，否则这个接口就变成一句谎）
--------------------------------------------
这一层现在只做**展示**：

* 验证者的奖励在链上 ``VerifierRegistry.verificationReward`` —— 一条**固定值**，
  还没有按案值比例走，而且测试网上一个节点都没有；
* 仲裁费在 ``arbitration_cases`` 里连字段都还没有，立案也还不收费。

所以 ``snapshot()`` 带 ``status = "policy-preview"``：口径已定、钱还没按这个口径走。
页面必须把它按「预告」渲染，不许写成「你现在就能赚到」。

「开放申请 / 谁在白名单」这类**在任状态**一律现读现算，不在这里复制一份：
入池资格读 ``arbitration_rules.pool_open_join()``，治理岗读
``governance_stake.open_join()`` —— 与真正的闸门共用同一处口径。
"""
from __future__ import annotations

from typing import Any

from config.settings import settings
from services import arbitration_rules, governance_stake

#: 口径已定、结算侧还没接上。前端据此把整页按「预告」渲染。
STATUS_PREVIEW = "policy-preview"

#: 展示用的样例案值（USDC）：页面上的「以案值 100 为例」就是这个数。
SAMPLE_CASE_VALUE_USDC = 100.0

BPS = 10_000.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    """配置写反（下限比上限大）时不许算出负数奖励，先把两端摆正。"""
    lo, hi = (low, high) if low <= high else (high, low)
    return max(lo, min(hi, value))


def round_usdc(value: float, digits: int = 4) -> float:
    """钱一律按 4 位小数回，别让前端拿到 0.020000000000000004。"""
    return round(_num(value), digits)


def case_reward(case_value_usdc: float) -> float:
    """一条**计入门限**的有效出证值多少钱（USDC）。"""
    value = max(0.0, _num(case_value_usdc))
    return _clamp(
        value * _num(settings.verifier_reward_bps) / BPS,
        _num(settings.verifier_reward_min_usdc),
        _num(settings.verifier_reward_max_usdc),
    )


def case_fee(case_value_usdc: float) -> float:
    """一场争议的立案费（USDC，由败诉方承担）。"""
    value = max(0.0, _num(case_value_usdc))
    return _clamp(
        value * _num(settings.arbitration_fee_bps) / BPS,
        _num(settings.arbitration_fee_min_usdc),
        _num(settings.arbitration_fee_max_usdc),
    )


def settlement_block() -> dict[str, Any]:
    """结算侧只露一个费率：它是这两个岗收入的总闸门。"""
    return {
        "fee_bps": _num(settings.settlement_fee_bps),
        "note": "fee bps of GMV; the live rate and split live in karma-economy FeeBridge",
    }


def verifier_block() -> dict[str, Any]:
    return {
        # 节点注册当前没有任何门槛（见 api/routes/verifier_network.py：只有登录校验）。
        "open_join": True,
        "min_case_value_usdc": _num(settings.verifier_network_min_case_usdc),
        "reward_bps": _num(settings.verifier_reward_bps),
        "reward_min_usdc": _num(settings.verifier_reward_min_usdc),
        "reward_max_usdc": _num(settings.verifier_reward_max_usdc),
        "quorum_required": int(settings.verifier_quorum_required or 0),
        "quorum_total": int(settings.verifier_quorum_total or 0),
        "slash_on_false_attestation": bool(settings.verifier_slash_on_false_attestation),
    }


def arbitrator_block() -> dict[str, Any]:
    lo, hi = arbitration_rules.panel_bounds()
    return {
        "open_join": bool(arbitration_rules.pool_open_join()),
        "self_serve_profile": bool(governance_stake.open_join()),
        "actor_binding_required": bool(arbitration_rules.actor_binding_required()),
        "fee_bps": _num(settings.arbitration_fee_bps),
        "fee_min_usdc": _num(settings.arbitration_fee_min_usdc),
        "fee_max_usdc": _num(settings.arbitration_fee_max_usdc),
        "loser_pays": bool(settings.arbitration_fee_loser_pays),
        "slash_multiple": _num(settings.arbitration_slash_multiple),
        "min_stake_usdc": _num(arbitration_rules.min_stake_amount()),
        "require_backed_stake": bool(arbitration_rules.backed_stake_required()),
        "coverage_multiple": _num(arbitration_rules.stake_coverage_multiple()),
        "panel_min": lo,
        "panel_max": hi,
    }


def snapshot(sample_case_value: float = SAMPLE_CASE_VALUE_USDC) -> dict[str, Any]:
    """整页要用的口径 + 一份按样例案值算好的结果。"""
    sample = max(0.0, _num(sample_case_value))
    verifier = verifier_block()
    seats = max(1, int(verifier["quorum_required"] or 1))
    per_attestation = case_reward(sample)
    return {
        "status": STATUS_PREVIEW,
        "sample_case_value_usdc": round_usdc(sample, 2),
        "settlement": settlement_block(),
        "verifier": verifier,
        "arbitrator": arbitrator_block(),
        "preview": {
            "verifier_reward_per_attestation_usdc": round_usdc(per_attestation),
            "verifier_reward_per_panel_usdc": round_usdc(per_attestation * seats),
            "verifier_paid_seats": seats,
            "arbitrator_fee_usdc": round_usdc(case_fee(sample)),
        },
    }
