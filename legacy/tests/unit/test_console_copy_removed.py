# -*- coding: utf-8 -*-
"""操作台不该显示的文案（用户点名删除，别再被谁加回来）。

- 侧栏 logo 下面的「赛博责任操作台」副标题；
- 侧栏那段「主身份 = 账房」的说明（这里只放连接钱包、刷脸认证、锁仓、授权……）。

用户的原话是「这个文案不需要显示在操作台」。文案属于产品决策，不是可以随手改回来的
样式细节，所以钉成门禁：页面里出现任何一个，CI 直接红。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps" / "console"
PAGE = CONSOLE / "pages" / "cyber" / "index.html"
I18N = CONSOLE / "scripts" / "i18n-cyber.js"

#: 用户点名不要的文案（页面可见文字 + 它的 i18n key + 那块的容器 id）。
BANNED = (
    "赛博责任操作台",
    "赛博责任网络",
    "主身份 = 账房",
    "这里只放连接钱包、刷脸认证、锁仓、授权这几件事",
    "属于每一个身份自己的页面",
    "brand.tagline",
    "nav-scope-note",
)


def test_page_never_shows_the_removed_copy():
    html = PAGE.read_text(encoding="utf-8")
    hit = [b for b in BANNED if b in html]
    assert not hit, "这些文案用户点名不要，别加回操作台：%s" % hit


def test_language_packs_drop_the_removed_copy():
    """8 个语言包都不许再留这条副标题，否则切语言它就冒出来了。"""
    i18n = I18N.read_text(encoding="utf-8")
    assert "brand.tagline" not in i18n
    assert "赛博责任操作台" not in i18n
