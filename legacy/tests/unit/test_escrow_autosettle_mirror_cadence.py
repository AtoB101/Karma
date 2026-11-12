# -*- coding: utf-8 -*-
"""台账自愈（capacity mirror）单独走更慢的节拍 —— 别每 15 秒重读一次全链。

``reconcile_all_capacity_mirrors`` 对每个持有活承诺的身份读一次链上 ERC-20 授权额
（``backing_report`` 里那次同步 ``eth_call``，实测 0.5~1s/身份）。7 个身份时一轮就是
3.4~7.1s，而主 tick 只隔 15 秒 —— 身份数一多，整轮 tick 就被这一段吃掉，循环越跑越
追不上。修法不是把它删掉（它兜的是「链上变了、账上还停在半路」，删了用户可用额度会
变成 0），而是给它一个更慢的节拍：便宜的步骤照常每 15 秒跑，自愈按
``escrow_autosettle_mirror_interval_seconds`` 到点才跑。

安全口径不变：正常交易在请求路径上（commit / revoke / 结算放款）已经各自对过一次账，
这一遍只是兜底。所以这里钉住的是「分频」，不是「跳过」。
"""
from __future__ import annotations

import ast
import inspect

from config.settings import settings
from services.chain import escrow_autosettle as mod

# ------------------------------------------------------------ 纯函数：到点了吗

def test_first_pass_always_runs():
    """进程刚起来时台账最可能和链上不一致：第一轮必须跑。"""
    assert mod._capacity_mirror_due(last_at=None, now=1234.0, interval_seconds=60) is True


def test_skips_before_the_interval_elapses():
    assert mod._capacity_mirror_due(last_at=1000.0, now=1059.9, interval_seconds=60) is False


def test_runs_once_the_interval_has_elapsed():
    assert mod._capacity_mirror_due(last_at=1000.0, now=1060.0, interval_seconds=60) is True
    assert mod._capacity_mirror_due(last_at=1000.0, now=1400.0, interval_seconds=60) is True


def test_zero_or_negative_interval_keeps_the_old_every_tick_behaviour():
    """开关关掉（<=0）时语义必须回到旧行为：每一轮 tick 都跑。"""
    assert mod._capacity_mirror_due(last_at=1000.0, now=1000.0, interval_seconds=0) is True
    assert mod._capacity_mirror_due(last_at=1000.0, now=1000.0, interval_seconds=-5) is True


def test_default_interval_is_slower_than_the_main_tick():
    """默认节拍必须比主 tick 慢，否则这个开关等于没开。"""
    defaults = settings.__class__.model_fields
    mirror = defaults["escrow_autosettle_mirror_interval_seconds"].default
    tick = defaults["escrow_autosettle_interval_seconds"].default
    assert mirror > 0
    assert mirror >= tick


# --------------------------------------------------- 接线：run_forever 真的用了它

def _run_forever_tree() -> ast.Module:
    return ast.parse(inspect.getsource(mod.run_forever))


def _mirror_gate(tree: ast.Module) -> ast.If:
    gates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_capacity_mirror_due"
            for call in ast.walk(node.test)
        )
    ]
    assert len(gates) == 1, "run_forever 必须只有一处 _capacity_mirror_due 闸门"
    return gates[0]


def test_run_forever_gates_the_mirror_pass():
    """自愈那一步必须在闸门里 —— 不能在 while 循环里裸跑（那就是每轮都读链）。"""
    guarded = [
        call
        for stmt in _mirror_gate(_run_forever_tree()).body
        for call in ast.walk(stmt)
        if isinstance(call, ast.Attribute)
        and call.attr == "reconcile_all_capacity_mirrors"
    ]
    assert guarded, "reconcile_all_capacity_mirrors 必须挂在 _capacity_mirror_due 的 if 里"


def test_run_forever_uses_the_configured_interval():
    source = inspect.getsource(mod.run_forever)
    assert "settings.escrow_autosettle_mirror_interval_seconds" in source
    assert "interval_seconds=mirror_interval" in source
