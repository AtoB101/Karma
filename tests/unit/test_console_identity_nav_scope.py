"""操作台侧栏按「当前身份」收窄功能区。

用户口径（2026-10）：选了哪个身份，就只显示那个身份对应的功能区 —— 不要把
订单、收付、任务、争议、Agent 接入、技能市场、复核台、仲裁台全部挤在一起。

用户口径（2026-10-10）：切到**助理身份**时，功能区只留
订单 / 收付中心 / 任务执行 / 账单 / 争议 / Agent 接入 / 设置 这七项 ——
身份 · 认证（建卡、主身份账房）和技能市场属于别的视角，不再画在助理页上。
技能市场那一组因此退役：侧栏不再给任何身份显示（整页与接口都还在，只是入口撤了）。

钉住三件事：

1. 侧栏分组由「当前档案的类」驱动（cyber-identity.js 的 ROLE_LABELS 取值：
   individual / merchant / enterprise / verifier / arbitrator），**不再**是
   「主身份 / 其它」两档；
2. 三个**岗位入口（验证者身份 / 仲裁者身份 / 运营复核台）任何身份都留着** ——
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

ROLES = {"master", "individual", "merchant", "enterprise", "verifier", "arbitrator", "ops_reviewer"}
#: 助理身份（子身份）的功能区白名单：一张卡干活要用到的七块，别的都收起来。
ASSISTANT_GROUPS = ["overview", "center", "tasks", "bills", "disputes", "agents", "settings"]
#: 侧栏里保留但不再给任何身份显示的分组 —— 入口退役，功能本身还在。
PARKED_NAV_GROUPS = {"market"}
#: 特权工作面 → 哪些岗位的功能区里有它（运营复核岗本来就是 verifier 类身份）。
PRIVILEGED = {
    "reviews": {"verifier", "ops_reviewer"},
    "verifiers": {"verifier", "ops_reviewer"},
    "arbitration": {"arbitrator"},
}


def _js_array(js: str, name: str) -> list[str]:
    """`var NAME = ["a", "b"];` —— 白名单可以直接写数组，也可以引用另一个常量（助理那三张共用一份）。"""
    m = re.search(r"var " + re.escape(name) + r" = \[([^\]]*)\];", js)
    assert m, f"找不到数组 {name}"
    return re.findall(r'"([^"]+)"', m.group(1))


def _role_groups(js: str) -> dict[str, list[str]]:
    block = js.split("var ROLE_NAV_GROUPS = {", 1)[1].split("};", 1)[0]
    block = re.sub(r"//[^\n]*", "", block)  # 注释里别误收
    out = {}
    for m in re.finditer(r"(\w+): (\[[^\]]*\]|\w+)", block):
        raw = m.group(2)
        out[m.group(1)] = re.findall(r'"([^"]+)"', raw) if raw.startswith("[") else _js_array(js, raw)
    return out


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
    assert set(_always_visible(js)) == {"verifier-id", "arbiter-id", "reviews"}
    tags = _nav_tags(PAGE.read_text(encoding="utf-8"))
    for group in ("verifier-id", "arbiter-id", "reviews"):
        assert group in tags, f"侧栏缺 {group} 这一组"
        assert "hidden" not in tags[group], f"{group} 是岗位入口，不许默认藏起来"


def test_every_nav_group_is_reachable_from_some_role():
    js = BOOT.read_text(encoding="utf-8")
    reachable = set(_always_visible(js)) | PARKED_NAV_GROUPS
    for groups in _role_groups(js).values():
        reachable |= set(groups)
    groups = set(_nav_tags(PAGE.read_text(encoding="utf-8")))
    missing = sorted(groups - reachable)
    assert not missing, f"这些侧栏分组没有任何身份看得到：{missing}"


def test_assistant_function_area_is_exactly_the_seven_work_areas():
    """切到助理身份：功能区只有那七项，身份 · 认证和技能市场都不许再出现。"""
    roles = _role_groups(BOOT.read_text(encoding="utf-8"))
    for role in ("individual", "merchant", "enterprise"):
        assert roles[role] == ASSISTANT_GROUPS, f"{role} 的功能区不是那七项：{roles[role]}"
        for gone in ("identity", "market", "verifier-id", "arbiter-id", "reviews"):
            assert gone not in roles[role], f"{role} 不该把 {gone} 收进功能区"
    # 主身份视角没动：身份 · 认证 + 账单 + 设置。
    assert roles["master"] == ["identity", "bills", "settings"]


def test_switching_identity_never_leaves_you_on_a_hidden_page():
    """换身份后旧页可能已经不在新功能区里（主身份的「身份 · 认证」→ 助理身份）：
    必须换到新功能区能到的第一页，别停在侧栏已经看不见的页上。"""
    js = BOOT.read_text(encoding="utf-8")
    assert "function pageInScope(" in js and "function relandHiddenPage(" in js
    assert "ROLE_NAV_GROUPS[activeNavRole()]" in js, "落点要按新身份的白名单算"
    block = js.split('document.addEventListener("karma-profile-switched"', 1)[1][:400]
    assert "relandHiddenPage()" in block, "换身份时要重新落点"


def test_privileged_work_areas_only_belong_to_their_own_role():
    roles = _role_groups(BOOT.read_text(encoding="utf-8"))
    for name, owners in PRIVILEGED.items():
        for role, groups in roles.items():
            if role in owners:
                assert name in groups, f"{role} 身份看不到 {name}"
            else:
                assert name not in groups, f"{role} 身份不该把 {name} 收进功能区"
