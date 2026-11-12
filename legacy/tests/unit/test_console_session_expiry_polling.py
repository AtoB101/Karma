"""会话过期后操作台不能再拿废 token 轮询（2026-10-13 审计发现）。

线上实测：一次会话过期，单个端点一小时能刷出约 250 条匿名 401，把安全报表里的
auth_failure_spike 顶成噪声。根因是 ``markExpired()`` 不清 token，
``console-sync.js`` 的 ``refreshAll()`` 仍判 ``authed=true``，``startAuto`` 里那个
``setInterval`` 照跑。这个文件只钉死修好的接线：过期停表、重连恢复。
"""
from __future__ import annotations

from pathlib import Path

CONSOLE = Path(__file__).resolve().parents[2] / "apps" / "console"


def _sync_js() -> str:
    return (CONSOLE / "scripts" / "console-sync.js").read_text(encoding="utf-8")


def test_session_expiry_stops_the_polling_timer():
    sync = _sync_js()
    marker = 'document.addEventListener("karma-session-expired"'
    assert marker in sync, "console-sync.js 必须监听 karma-session-expired"
    window = sync[sync.index(marker) : sync.index(marker) + 600]
    assert "stopAuto()" in window, (
        "会话过期必须停掉定时轮询，否则会拿废 token 每 15 秒撞一串 401"
    )


def test_reconnecting_a_wallet_resumes_the_polling_timer():
    sync = _sync_js()
    marker = '["karma-wallet-connected", "karma-session-restored"]'
    assert marker in sync, "console-sync.js 必须监听重连事件"
    window = sync[sync.index(marker) : sync.index(marker) + 800]
    assert "startAuto(" in window, (
        "重新连上钱包后要把定时刷新恢复回来，否则页面不再自动更新"
    )