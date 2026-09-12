"""操作结果必须写在「看得见」的地方。

线上实测发现：点「增加锁仓额度」后，钱包真的弹了 approve + commit，但结果文字
被写在 `<details class="conn-settings">`（默认收起的「连接设置」）里面的
`[data-api-status]` 上 —— 用户什么都没看到。报错也一样被吞在折叠面板里，
于是只能得到「点了没反应」的体验。
这些断言把「反馈栏必须在顶栏、必须在折叠面板外」钉住。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = ROOT / "apps/console/pages/cyber/index.html"
CONSOLE_JS = ROOT / "apps/console/scripts/cyber-console.js"
I18N_JS = ROOT / "apps/console/scripts/i18n-cyber.js"


def test_action_status_is_not_hidden_in_the_collapsed_panel():
    html = INDEX_HTML.read_text(encoding="utf-8")
    start = html.index('<details class="conn-settings">')
    end = html.index("</details>", start)
    assert "data-api-status" not in html[start:end], "操作反馈又被塞回收起的「连接设置」里了"
    assert html.index("data-api-status") < start, "反馈栏要在顶栏（折叠面板之前）"


def test_chain_errors_are_translated_into_something_the_user_can_act_on():
    js = CONSOLE_JS.read_text(encoding="utf-8")
    assert "function humanTxError(" in js
    block = js[js.index("function humanTxError(") : js.index("function fmtNum(")]
    assert "insufficient funds" in block, "手续费不够要说人话"
    assert "4001" in block, "用户自己取消也要有话说"
    assert "InsufficientAllowance" in block
    assert js.count("setApiStatus(humanTxError(e), true)") >= 3, "链上失败都要走人话翻译"


def test_capacity_refresh_reports_the_numbers():
    js = CONSOLE_JS.read_text(encoding="utf-8")
    assert "api.status_refreshed" in js
    tail = js[js.index("api.status_refreshed") : js.index("api.status_refreshed") + 400]
    assert "总锁仓" in tail and "fmtNum(locked)" in tail, (
        "刷新完要直接写出总锁仓数字，用户才知道锁进去没有"
    )
    i18n = I18N_JS.read_text(encoding="utf-8")
    assert i18n.count('"api.status_refreshed"') >= 2, "中英文都要有这条文案"


def test_overview_numbers_follow_the_v2_allowance():
    """v2 是非托管的：钱留在用户钱包，capacity 台账恒为 0。

    实测：用户在线上锁了 10 USDC（链上 approve + commit 都成功、后端也登记了），
    总览「锁仓 USDC」却还是 0.00 —— 因为那几个数字只读 v1 台账。
    """
    js = CONSOLE_JS.read_text(encoding="utf-8")
    block = js[js.index("async function refreshCapacity(") : js.index("async function releaseCapacityAction(")]
    assert "loadEscrowInfo(id, true)" in block, "刷新额度必须同时问链上授权"
    assert "committed_usdc" in block
    assert "Math.max(locked, committed)" in block, "台账和链上授权取大者，别被台账骗到"
    assert '["[data-bind=total_locked_usdc]", locked]' in block
