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
    """刷新完必须把「总锁仓」数字直接写出来。

    这条原来钉的是核心包里的 api.status_refreshed 键。后来刷新提示改成了整句模板
    （要带数字和时间，还要控住各语言的语序），那个键就没人用了 —— 断言于是长期红着，
    而它真正想守的东西（刷新后看得见总锁仓数字）其实一直成立。现在直接钉那句模板。
    """
    js = CONSOLE_JS.read_text(encoding="utf-8")
    marker = "额度已刷新 · 总锁仓 {0}"
    assert marker in js, "刷新完要报出总锁仓数字"
    tail = js[js.index(marker) : js.index(marker) + 400]
    assert "fmtNum(locked)" in tail, "刷新完要直接写出总锁仓数字，用户才知道锁进去没有"
    # 这句是拼出来的（带数字/时间），五份文案表都得有；少一份，切到那门语言就掉回中文。
    for pack in ("en", "ja", "ko", "es-AR", "es-SV"):
        text = (ROOT / "apps/console/scripts/i18n-phrase" / (pack + ".js")).read_text(
            encoding="utf-8"
        )
        assert "额度已刷新" in text, pack + " 缺「额度已刷新」，刷新提示会掉回中文"


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


def test_overview_refreshes_itself_after_connecting():
    """实测：连上钱包后总览还是 0.00，非得手点一次「刷新额度」才变。

    必须挂在这两个事件上；不能挂 karma-capacity-changed（那是 refreshCapacity
    自己派发的，会绕成死循环）。
    """
    js = CONSOLE_JS.read_text(encoding="utf-8")
    start = js.index('"karma-agent-connected"')
    end = js.index('["karma-wallet-connected", "karma-session-restored"]')
    assert "refreshCapacity()" not in js[start:end], (
        "含 karma-capacity-changed 的那组监听里不能刷额度 —— 那个事件就是它自己派发的，会死循环"
    )
    assert "refreshCapacity()" in js[end : end + 400]
