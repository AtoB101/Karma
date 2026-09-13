"""收付中心：页面接线（静态检查 + 与后端真实对接）。

用户在操作台看到的是「一个身份的收付台账」，所以这里钉三件事：

1. 主身份视角必须有总览 + 支出明细 + 收入明细；切子身份只换作用域与内容。
2. 每一行都能点开详情；确认区 / 争议区独立成块，按订单状态分色。
3. 页面调的就是 /v1/payments/ledger —— 后端接口不存在的话，这里会先炸。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps" / "console"
HTML = CONSOLE / "pages" / "cyber" / "index.html"
JS = CONSOLE / "scripts" / "cyber-payments.js"
CLIENT = CONSOLE / "scripts" / "karma-public-api.js"
GATE = ROOT / "scripts" / "acceptance" / "console_last_mile_gate.sh"

CENTER_NODES = (
    'id="pay-scope-note"',
    'id="pay-stats"',
    'id="pay-substats"',
    'data-bind="pay_income"',
    'data-bind="pay_expense"',
    'data-bind="pay_inflight"',
    'data-bind="pay_pending_income"',
    'data-bind="pay_locked"',
    'data-bind="pay_sub_income"',
    'id="pay-list"',
    'data-pay-tab="out"',
    'data-pay-tab="in"',
    'id="pay-zone-confirm"',
    'id="pay-confirm-list"',
    'id="pay-zone-dispute"',
    'id="pay-dispute-list"',
    'id="pay-detail"',
    'id="pay-refresh"',
)


def test_center_page_carries_overview_two_ledgers_and_two_zones():
    html = HTML.read_text(encoding="utf-8")
    for node in CENTER_NODES:
        assert node in html, f"收付中心缺少 {node}"
    assert "支出明细" in html and "收入明细" in html
    assert "确认区" in html and "争议区" in html
    assert "../../scripts/cyber-payments.js" in html, "收付中心脚本必须被页面加载"
    # 原来的「发起收付」两个表单不能丢，只是收进折叠里。
    for keep in (
        'id="pc-seller"',
        'id="pc-amount"',
        'id="btn-create-paycode"',
        'id="pc-voucher"',
        'id="btn-accept-paycode"',
    ):
        assert keep in html, f"发起收付的表单少了 {keep}"
    assert 'id="pc-seller-profile"' in html, "收款要能选记到哪个子身份"


def test_script_calls_the_ledger_api_and_follows_the_identity_scope():
    js = JS.read_text(encoding="utf-8")
    assert "getPaymentLedger" in js, "页面必须调 /v1/payments/ledger"
    assert "getPaymentEntry" in js, "点开详情要拿单笔详情"
    assert "profile_id" in js, "子身份视角要把 profile_id 传给后端"
    assert "KarmaIdentitySwitcher" in js, "视角必须跟全局身份切换器走"
    for evt in (
        "karma-page-shown",
        "karma-profile-switched",
        "karma-wallet-connected",
        "karma-alloc-changed",
        "karma-capacity-changed",
    ):
        assert evt in js, f"收付中心没有跟着 {evt} 刷新"
    # 状态要能翻成中文，不能把后端的 raw status 直接糊到屏幕上。
    for label in ("已结算", "争议中", "已交付待确认", "锁仓中"):
        assert label in js, f"缺少状态中文名 {label}"
    assert "STATUS_LABELS" in js
    # 三种视角分区：收入 / 支出 / 确认 / 争议。
    for cls in ("pay-phase-", "pay-status-", "pay-dir-", "pay-role-"):
        assert cls in js, f"缺少分区样式钩子 {cls}"


def test_api_client_exposes_the_ledger_endpoints():
    client = CLIENT.read_text(encoding="utf-8")
    assert "/v1/payments/ledger" in client
    assert "/v1/payments/entries/" in client
    assert "getPaymentLedger," in client and "getPaymentEntry," in client
    # 接单时要把子身份一并上报，否则子身份的收入无从归属。
    assert "seller_profile_id" in client


def test_gate_checks_the_new_script():
    gate = GATE.read_text(encoding="utf-8")
    assert "scripts/cyber-payments.js" in gate, "门禁要确认文件存在"
    loop = [ln for ln in gate.splitlines() if ln.strip().startswith("for js in")]
    assert loop and "cyber-payments.js" in loop[0], "门禁要 node --check 它"
