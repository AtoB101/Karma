# -*- coding: utf-8 -*-
"""karma-pair 的接线测试 —— 不打网络，只守「参数 -> 工具调用」这一步别接错。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from karma_connect import pair  # noqa: E402


def test_default_runtime_url_is_baked_in(monkeypatch):
    """不设 KARMA_RUNTIME_URL 时必须是公网节点，不能落到 localhost:8000。"""
    monkeypatch.delenv("KARMA_RUNTIME_URL", raising=False)
    pair._default_runtime_url()
    import os

    assert os.environ["KARMA_RUNTIME_URL"] == "https://karma-network.ai"


def test_an_explicit_runtime_url_wins(monkeypatch):
    monkeypatch.setenv("KARMA_RUNTIME_URL", "http://127.0.0.1:9000")
    pair._default_runtime_url()
    import os

    assert os.environ["KARMA_RUNTIME_URL"] == "http://127.0.0.1:9000"


def test_start_parses_the_agent_identity():
    args = pair.build_parser().parse_args(["start", "--agent-name", "claw-001", "--side", "seller"])
    assert args.agent_name == "claw-001"
    assert args.side == "seller"


def test_claim_takes_the_handoff_code_positionally():
    args = pair.build_parser().parse_args(["claim", "7P2K-9RVX"])
    assert args.handoff_code == "7P2K-9RVX"


def test_start_failure_exits_nonzero(monkeypatch, capsys):
    """工具返回 ok=false 时必须非零退出，否则脚本里 `|| exit` 抓不住。"""
    import asyncio

    class FakeTools:
        @staticmethod
        async def karma_connect(**_kwargs):
            return {"ok": False, "error": "pairing_request_failed", "detail": "nope"}

    monkeypatch.setattr(pair, "_tools", lambda: FakeTools)
    args = pair.build_parser().parse_args(["start", "--agent-name", "x"])
    assert asyncio.run(pair.cmd_start(args)) == 1


def test_start_parses_no_open_flag():
    args = pair.build_parser().parse_args(["start", "--agent-name", "x", "--no-open"])
    assert args.no_open is True


def test_start_opens_verification_uri_on_success(monkeypatch, capsys):
    """成功拿到 verification_uri 时要自动弹出主人批准页。"""
    import asyncio

    opened = []

    class FakeTools:
        @staticmethod
        async def karma_connect(**_kwargs):
            return {
                "ok": True,
                "user_code": "K4QP-3M2X",
                "verification_uri": "https://karma-network.ai/console/?pair=K4QP-3M2X",
            }

    monkeypatch.setattr(pair, "_tools", lambda: FakeTools)
    monkeypatch.setattr(pair.webbrowser, "open", lambda uri, new=0: opened.append(uri) or True)
    args = pair.build_parser().parse_args(["start", "--agent-name", "x"])
    assert asyncio.run(pair.cmd_start(args)) == 0
    assert opened == ["https://karma-network.ai/console/?pair=K4QP-3M2X"]


def test_start_tells_the_tool_not_to_auto_open(monkeypatch, capsys):
    """CLI 自己负责弹窗，工具侧必须关掉自动打开，避免开两个标签页。"""
    import asyncio

    seen = {}

    class FakeTools:
        @staticmethod
        async def karma_connect(**kwargs):
            seen.update(kwargs)
            return {
                "ok": True,
                "user_code": "K4QP-3M2X",
                "verification_uri": "https://karma-network.ai/console/?pair=K4QP-3M2X",
            }

    monkeypatch.setattr(pair, "_tools", lambda: FakeTools)
    monkeypatch.setattr(pair.webbrowser, "open", lambda uri, new=0: True)
    args = pair.build_parser().parse_args(["start", "--agent-name", "x", "--no-open"])
    assert asyncio.run(pair.cmd_start(args)) == 0
    assert seen.get("open_approval_page") is False


def test_start_skips_open_when_no_open(monkeypatch, capsys):
    """--no-open 要关掉自动弹窗口。"""
    import asyncio

    opened = []

    class FakeTools:
        @staticmethod
        async def karma_connect(**_kwargs):
            return {
                "ok": True,
                "user_code": "K4QP-3M2X",
                "verification_uri": "https://karma-network.ai/console/?pair=K4QP-3M2X",
            }

    monkeypatch.setattr(pair, "_tools", lambda: FakeTools)
    monkeypatch.setattr(pair.webbrowser, "open", lambda uri, new=0: opened.append(uri) or True)
    args = pair.build_parser().parse_args(["start", "--agent-name", "x", "--no-open"])
    assert asyncio.run(pair.cmd_start(args)) == 0
    assert opened == []
