"""操作台首页 = 订单状态图。

用户原话：「把总览改为 订单可视状态图，买方显示买的订单，卖方显示卖方订单；
订单完成争议时间后就不再显示」。这一组是静态接线检查：泳道、退场规则、
买/卖视角的线必须一直连着，别下次改版又把首页改回一堆重复的面板。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
HTML = CONSOLE / "pages/cyber/index.html"
ORDERS_JS = CONSOLE / "scripts/cyber-orders.js"
CONSOLE_JS = CONSOLE / "scripts/cyber-console.js"
I18N_JS = CONSOLE / "scripts/i18n-cyber.js"
GATE_SH = ROOT / "scripts/acceptance/console_last_mile_gate.sh"
APP_PY = ROOT / "api/app.py"


def test_first_page_is_the_order_board():
    html = HTML.read_text(encoding="utf-8")
    for needle in (
        'id="order-board-card"',
        'id="order-board"',
        'id="order-totals"',
        'id="order-sync"',
        'id="order-refresh"',
        'id="order-empty"',
        'data-order-side="all"',
        'data-order-side="out"',
        'data-order-side="in"',
    ):
        assert needle in html, f"订单状态图缺少 {needle}"
    # 侧栏：主项「订单」+ 买方 / 卖方两个子项
    assert 'data-group="overview"' in html
    assert html.count('data-page="overview"') >= 3, "订单页要有主项 + 两个子项"
    assert 'data-i18n="nav.overview">订单<' in html
    assert "cyber-orders.js" in html, "页面必须加载订单状态图脚本"
    assert "cyber-orders.js" in GATE_SH.read_text(encoding="utf-8"), "门禁脚本要把它算进来"


def test_the_duplicated_panels_stay_gone():
    """总览原来那四块和功能页重复，用户点名说多余 —— 删掉就别再长回来。"""
    html = HTML.read_text(encoding="utf-8")
    for gone in ("快捷操作", "责任状态流", "API 数据预览", "最近需要处理", "data-sync-table=\"tasks\""):
        assert gone not in html, f"「{gone}」是重复面板，不该再出现"
    # 调试用的 settlement 输出还在，只是收进了「连接设置」折叠面板。
    assert "data-settlement-preview" in html
    settings_at = html.index("conn-settings-body")
    assert html.index("data-settlement-preview") > settings_at


def test_buyer_and_seller_views_share_one_switch():
    """买方订单 / 卖方订单 只切视角，不改数据源 —— 侧栏子项和卡片上的按钮必须对齐。"""
    html = HTML.read_text(encoding="utf-8")
    assert 'data-sub="buy"' in html and 'data-sub="sell"' in html
    console = CONSOLE_JS.read_text(encoding="utf-8")
    assert 'window.KarmaOrders.setSide(subKey === "buy" ? "out" : subKey === "sell" ? "in" : "all")' in console
    orders = ORDERS_JS.read_text(encoding="utf-8")
    assert "direction" in orders and 'state.side !== "all" && e.direction !== state.side' in orders
    i18n = I18N_JS.read_text(encoding="utf-8")
    for key in ('"sub.orders.buy"', '"sub.orders.sell"', '"ord.title"', '"ord.all"', '"ord.buy"', '"ord.sell"'):
        assert i18n.count(key) >= 2, f"{key} 中英文都要有"


def test_finished_orders_leave_the_board_after_the_dispute_window():
    """「订单完成争议时间后就不再显示」——退场判定必须挂在可争议期上。"""
    orders = ORDERS_JS.read_text(encoding="utf-8")
    assert 'if (phase === "closed")' in orders
    assert "disputeWindowMs(entry)" in orders
    assert "Date.now() - ts <= disputeWindowMs(entry) ? \"done\" : null" in orders, (
        "过了可争议期的已完成单必须返回 null（退场），而不是留在图上"
    )
    assert "dispute_window_hours" in orders, "窗口要读后端给的值，不能写死"
    # 后端把窗口暴露出来，前端才不会猜。
    app_py = APP_PY.read_text(encoding="utf-8")
    assert '"dispute_window_hours": int(settings.dispute_window_hours or 0)' in app_py


def test_the_board_is_only_orders_not_money_moves():
    """锁仓凭证是资金动作，不是订单，别混进订单图里添乱。"""
    orders = ORDERS_JS.read_text(encoding="utf-8")
    assert 'var ORDER_KINDS = { settlement: 1, binding: 1, voucher: 1 };' in orders


def test_board_keeps_itself_fresh_without_a_manual_refresh():
    orders = ORDERS_JS.read_text(encoding="utf-8")
    for name in (
        "karma-wallet-connected",
        "karma-session-restored",
        "karma-profile-switched",
        "karma-capacity-changed",
        "karma-alloc-changed",
        "karma-agent-connected",
    ):
        assert name in orders, f"订单图要跟着 {name} 刷新"
    assert 'ev.detail.page !== PAGE' in orders, "只在订单页被显示时重读"
    assert "global.KarmaOrders = { load: load, setSide: setSide, paintSides: paintSides, state: state }" in orders


def test_launch_guide_steps_aside_once_the_owner_is_set_up():
    """三步都做完了，起步引导就该收起，把版面让给订单图。"""
    console = CONSOLE_JS.read_text(encoding="utf-8")
    assert "const allDone = locked > 0 && allocDone && onboarded.length > 0;" in console
    assert "card.hidden = allDone;" in console
    html = HTML.read_text(encoding="utf-8")
    for step in ("launch-lock-state", "launch-alloc-state", "launch-sdk-state"):
        assert step in html, f"起步引导的 {step} 不能被删（没配置完的人还要看）"