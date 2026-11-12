"""助理任务执行看板（任务执行页）。

用户原话：小爱助理功能区里的「任务执行」应该回答「它正在叫 agent 做什么」——
订单、任务内容、金额和进度一目了然；而不是把后台的结算流转英文状态机
（create → pending → lock → start …）直接摊给用户看。

钉住三件事：
1. 任务页只画友好看板，开发者结算流转测试块默认彻底隐藏。
2. 看板数据来自收付台账，任务内容按需读合同；读不到就退回服务类型，不编造。
3. 页面脚本被门禁和版本串管住。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps" / "console"
HTML = CONSOLE / "pages" / "cyber" / "index.html"
JS = CONSOLE / "scripts" / "cyber-assistant-tasks.js"
CSS = CONSOLE / "styles" / "cyber-console.css"
GATE = ROOT / "scripts" / "acceptance" / "console_last_mile_gate.sh"


def test_task_page_has_a_friendly_board_and_hides_the_dev_flow():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="assistant-task-list"' in html
    assert 'id="assistant-task-board"' in html
    assert 'id="assistant-task-status"' in html
    assert 'id="assistant-task-refresh"' in html
    assert 'id="settlement-flow-dev"' in html
    dev = re.search(r'<details[^>]*id="settlement-flow-dev"[^>]*>', html)
    assert dev and "hidden" in dev.group(0), "结算流转测试块必须默认隐藏"


def test_assistant_task_script_uses_the_ledger_and_contract_source():
    js = JS.read_text(encoding="utf-8")
    assert "getPaymentLedger" in js, "任务看板必须读收付台账"
    assert "getContract" in js, "任务内容要按 task_id 读合同"
    assert "KarmaIdentitySwitcher" in js, "任务看板必须跟当前助理身份走"
    assert "KarmaOrderFlow" in js, "服务类型文案只认一份来源"
    for evt in (
        "karma-page-shown",
        "karma-profile-switched",
        "karma-wallet-connected",
        "karma-capacity-changed",
        "karma-agent-connected",
    ):
        assert evt in js, f"任务看板没有跟着 {evt} 刷新"
    # 用户口径：卡片只讲人话，不把 client_agent_id / worker_agent_id 这类后台标识摊出来。
    assert "client_agent_id" not in js
    assert "worker_agent_id" not in js


def test_assistant_scope_hides_the_settlement_flow_nav_entry():
    console_js = (CONSOLE / "scripts" / "cyber-console.js").read_text(encoding="utf-8")
    assert (
        "document.querySelectorAll('[data-page=\"tasks\"][data-sub=\"flow\"]')" in console_js
    ), "结算流转子项要在助理视角下收起来"
    assert 'b.classList.toggle("nav-scope-hidden", assistant)' in console_js


def test_dev_flow_hidden_rule_is_explicit_in_css():
    css = CSS.read_text(encoding="utf-8")
    assert "#settlement-flow-dev[hidden]" in css, "details 的隐藏规则要显式写死"


def test_gate_tracks_the_new_assistant_task_script():
    gate = GATE.read_text(encoding="utf-8")
    assert "scripts/cyber-assistant-tasks.js" in gate, "门禁要确认新脚本存在"
    assert "cyber-assistant-tasks.js" in gate, "门禁要 node --check 新脚本"
