"""Mobile wallet connect: on a phone the only path that can work is "let the
wallet open this page" - a phone browser has no extension to detect.

These assertions pin the *ordering* of the connect modal, because the ordering
was the bug: it led with browser-extension download links, so tapping MetaMask
on a phone opened the extension store page and nothing ever connected.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTH_JS = ROOT / "apps/console/scripts/console-wallet-auth.js"


def _src() -> str:
    return AUTH_JS.read_text(encoding="utf-8")


def _render_body() -> str:
    src = _src()
    start = src.index("function renderBody()")
    end = src.index("/* ------------------------------------------------------------- SIWE login")
    return src[start:end]


def test_mobile_lists_wallet_deeplinks_before_extension_installs():
    body = _render_body()
    assert "html += MOBILE_UA ? mobileSection + installsSection : installsSection + mobileSection;" in body, (
        "手机上「唤起钱包 App」不再排在「安装浏览器插件」之前：点 MetaMask 只会跳插件下载页"
    )
    assert body.index("var mobileSection =") < body.index("var installsSection =")
    assert body.index("用手机钱包打开本页") < body.index("安装钱包（浏览器插件）")


def test_mobile_renders_deeplinks_as_full_width_rows_not_tiny_chips():
    body = _render_body()
    assert "kw-item kw-open-wallet" in body
    assert "esc(w.deep(url))" in body
    assert "mobileSection += '<div class=\"kw-list\">';" in body


def test_extension_installs_are_collapsed_on_mobile():
    body = _render_body()
    assert "<details class=\"kw-more\">" in body
    assert "在电脑上使用？安装浏览器插件" in body


def test_a_detected_wallet_connects_without_an_extra_pick():
    src = _src()
    connect = src[src.index("function connect()") : src.index("function disconnect()")]
    assert "list.length === 1) return connectWith(list[0])" in connect
    assert "!MOBILE_UA" not in connect, (
        "钱包 App 内置浏览器里还要再挑一次钱包，用户会以为点了没反应"
    )


def test_catalog_keeps_a_deeplink_for_every_mobile_wallet():
    src = _src()
    catalog = src[src.index("var CATALOG = [") : src.index("/* ---------------------------------------------------------------- modal CSS */")]
    assert catalog.count("deep: function") >= 6
    for name in (
        "MetaMask",
        "OKX Wallet",
        "Coinbase Wallet",
        "imToken",
        "TokenPocket",
        "Trust Wallet",
    ):
        assert f'name: "{name}"' in catalog


def test_wechat_like_in_app_browsers_get_a_banner_and_a_copy_fallback():
    src = _src()
    assert "micromessenger" in src, "微信内置浏览器拦掉了钱包唤起，必须单独识别"
    body = _render_body()
    assert 'class="kw-app"' in body
    assert 'data-kw-copy="' in body
    assert "在浏览器打开" in body


def test_copy_button_is_actually_wired_to_a_clipboard_handler():
    src = _src()
    assert "function copyText(" in src
    assert 'closest("[data-kw-copy]")' in src
    assert "navigator.clipboard.writeText" in src
    assert "document.execCommand" in src, "老浏览器/非 https 下 clipboard API 不可用，要有兜底"
