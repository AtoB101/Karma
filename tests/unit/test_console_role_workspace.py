# -*- coding: utf-8 -*-
"""岗位入口 = 真的「切进这个岗位」，不是翻到一页申请表单。

用户口径（2026-10-08）：每个身份都有对应的功能区和操作区，选了身份就该跳到它自己的
地方。子身份（注册代理）本来就是切卡，这条讲的是「选择身份」里的两个岗位入口：

* 选了验证者身份 → 功能区换成验证岗那一套，并落到**验证者网络**（没有能力位才落申请页）；
* 选了仲裁者身份 → 落**仲裁台**同理；
* 再选回主身份或任一子身份卡 → 离开岗位视角，功能区改回按档案的类收窄。

落点只允许有一个来源（cyber-console.js 的 KarmaWorkspace），cyber-identity.js 不许
自己再拼一套，否则「点进去了但侧栏没变」这类毛病会一直复发。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
BOOT = CONSOLE / "scripts/cyber-console.js"
IDENTITY = CONSOLE / "scripts/cyber-identity.js"
PAGE = CONSOLE / "pages/cyber/index.html"


def _role_groups(js: str) -> dict:
    block = js.split("var ROLE_NAV_GROUPS = {", 1)[1].split("};", 1)[0]
    return {
        m.group(1): re.findall(r'"([^"]+)"', m.group(2))
        for m in re.finditer(r"(\w+): \[([^\]]*)\]", block)
    }


def _workspaces(js: str) -> dict:
    block = js.split("var ROLE_WORKSPACES = {", 1)[1].split("};", 1)[0]
    out = {}
    for m in re.finditer(r"(\w+): \{([^}]*)\}", block):
        out[m.group(1)] = dict(re.findall(r"(\w+): \"([^\"]+)\"", m.group(2)))
    return out


def test_each_role_entry_has_a_workspace():
    ws = _workspaces(BOOT.read_text(encoding="utf-8"))
    assert set(ws) == {"verifier", "arbitrator"}
    assert ws["verifier"]["home"] == "verifiers"
    assert ws["verifier"]["apply"] == "verifier-id"
    assert ws["verifier"]["cap"] == "can_view_verifier_network"
    assert ws["arbitrator"]["home"] == "arbitration"
    assert ws["arbitrator"]["apply"] == "arbiter-id"
    assert ws["arbitrator"]["cap"] == "can_operate_arbitration"


def test_workspace_home_is_inside_that_role_function_area():
    """落到工作面，前提是这个工作面本来就属于该岗位的功能区 —— 否则点进去等于空白。"""
    js = BOOT.read_text(encoding="utf-8")
    groups = _role_groups(js)
    for role, ws in _workspaces(js).items():
        assert ws["home"] in groups[role], "%s 的工作面 %s 不在它的功能区里" % (role, ws["home"])


def test_workspace_pages_exist_in_the_page():
    html = PAGE.read_text(encoding="utf-8")
    for page in ("verifier-id", "arbiter-id", "verifiers", "arbitration"):
        assert 'id="%s"' % page in html, "页面里没有 #%s" % page


def test_sidebar_scope_prefers_the_selected_role_over_the_profile_class():
    js = BOOT.read_text(encoding="utf-8")
    body = js.split("function activeNavRole() {", 1)[1].split("\n  }", 1)[0]
    assert body.index("workspaceRole()") < body.index("KarmaIdentitySwitcher"), (
        "岗位视角必须优先于档案的类，否则点了岗位侧栏还是上一张卡的"
    )


def test_role_entry_goes_through_the_one_landing_decider():
    js = IDENTITY.read_text(encoding="utf-8")
    body = js.split("function goRolePage(page) {", 1)[1].split("\n  }", 1)[0]
    assert "KarmaWorkspace.select" in body, "岗位入口要走 KarmaWorkspace，不能自己 switchPage"
    # cyberSwitchPage 只能留作退路，不能是主路径
    assert body.index("KarmaWorkspace.select") < body.index("cyberSwitchPage")


def test_picking_a_profile_leaves_the_role_view():
    js = BOOT.read_text(encoding="utf-8")
    handler = js.split('document.addEventListener("karma-profile-switched"', 1)[1].split("});", 1)[0]
    assert "setWorkspaceRole(\"\")" in handler, "选子身份卡之后必须离开岗位视角"
