"""操作台侧栏按「当前身份」收窄功能区。

用户口径（2026-10）：选了哪个身份，就只显示那个身份对应的功能区 —— 不要把
订单、收付、任务、争议、Agent 接入、技能市场、复核台、仲裁台全部挤在一起。

钉住三件事：

1. 侧栏分组由「当前档案的类」驱动（cyber-identity.js 的 ROLE_LABELS 取值：
   individual / merchant / enterprise / verifier / arbitrator），**不再**是
   「主身份 / 其它」两档；
2. 「验证者身份 / 仲裁者身份」两个**自助申请入口任何身份都留着** ——
   把入口收掉，还没开通的人就永远开不了岗；
3. 每个侧栏分组至少有一个身份看得到；特权工作面只归它自己的岗
   （复核台 / 验证者网络 → 复核岗，仲裁台 → 仲裁岗）。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
BOOT = CONSOLE / "scripts/cyber-console.js"
PAGE = CONSOLE / "pages/cyber/index.html"

ROLES = {"master", "individual", "merchant", "enterprise", "verifier", "arbitrator"}
PRIVILEGED = {
    "reviews": "verifier",
    "verifiers": "verifier",
    "arbitration": "arbitrator",
}


def _role_groups(js: str) -> dict[str, list[str]]:
    block = js.split("var ROLE_NAV_GROUPS = {", 1)[1].split("};", 1)[0]
    return {
        m.group(1): re.findall(r'"([^"]+)"', m.group(2))
        for m in re.finditer(r"(\w+): \[([^\]]*)\]", block)
    }


def _always_visible(js: str) -> list[str]:
    m = re.search(r"var NAV_ALWAYS_VISIBLE = \[([^\]]*)\];", js)
    assert m, "找不到 NAV_ALWAYS_VISIBLE"
    return re.findall(r'"([^"]+)"', m.group(1))


def _nav_tags(html: str) -> dict[str, str]:
    return {
        m.group(1): m.group(0)
        for m in re.finditer(r'<div class="nav-group" data-group="([^"]+)"[^>]*>', html)
    }


def test_nav_scope_is_driven_by_the_role_not_a_two_way_master_flag():
    js = BOOT.read_text(encoding="utf-8")
    assert "MASTER_SCOPE_GROUPS" not in js, "侧栏不该再是「主身份 / 其它」两档"
    assert "getActiveProfile" in js, "要按当前档案的类收窄"
    assert set(_role_groups(js)) == ROLES


def test_self_service_entry_groups_are_never_scoped_away():
    js = BOOT.read_text(encoding="utf-8")
    assert set(_always_visible(js)) == {"verifier-id", "arbiter-id"}
    tags = _nav_tags(PAGE.read_text(encoding="utf-8"))
    for group in ("verifier-id", "arbiter-id"):
        assert group in tags, f"侧栏缺 {group} 这一组"
        assert "hidden" not in tags[group], f"{group} 是自助申请入口，不许默认藏起来"


def test_every_nav_group_is_reachable_from_some_role():
    js = BOOT.read_text(encoding="utf-8")
    reachable = set(_always_visible(js))
    for groups in _role_groups(js).values():
        reachable |= set(groups)
    groups = set(_nav_tags(PAGE.read_text(encoding="utf-8")))
    missing = sorted(groups - reachable)
    assert not missing, f"这些侧栏分组没有任何身份看得到：{missing}"


def test_privileged_work_areas_only_belong_to_their_own_role():
    roles = _role_groups(BOOT.read_text(encoding="utf-8"))
    for name, owner in PRIVILEGED.items():
        for role, groups in roles.items():
            if role == owner:
                assert name in groups, f"{owner} 身份看不到 {name}"
            else:
                assert name not in groups, f"{role} 身份不该把 {name} 收进功能区"
