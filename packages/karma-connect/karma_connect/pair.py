# -*- coding: utf-8 -*-
"""karma-pair —— 配对这件事不该让 LLM 在中间转达一串码。

agent 报的码要经过「模型读工具结果 -> 模型复述 -> 用户手抄」三次转手，任何一次都可能
走样；走样之后服务端只会回一句 ``pairing code not found``，看不出是哪一步坏的。

这个命令直接用同一份 MCP 工具实现（``karma_openclaw.pairing_tools``），把「申请 -> 批准
-> 领凭据」拆成用户看得见的三步：

    karma-pair start                  # 出码，打印链接
    (在操作台输码 -> 核对 -> 批准)
    karma-pair status                 # 看批准了没
    karma-pair claim                  # 批准即交付，凭据落到本机、立刻能用（不用重启）

凭据落盘位置和其它实现共用：``~/.karma/agent.env``（KARMA_AGENT_ENV_PATH 可覆盖）。
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

DEFAULT_RUNTIME_URL = "https://karma-network.ai"


def _ensure_importable() -> None:
    """把 karma-openclaw 挂上 sys.path —— 没 pip install 过也能跑。"""
    if importlib.util.find_spec("karma_openclaw") is not None:
        return
    here = Path(__file__).resolve()
    for candidate in (here.parents[3] / "karma-openclaw", here.parents[2] / "karma-openclaw"):
        if (candidate / "karma_openclaw" / "__init__.py").is_file():
            sys.path.insert(0, str(candidate))
            return


def _tools():
    _ensure_importable()
    from karma_openclaw import pairing_tools

    return pairing_tools


def _default_runtime_url() -> None:
    os.environ.setdefault("KARMA_RUNTIME_URL", DEFAULT_RUNTIME_URL)


def _dump(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    sys.stdout.flush()


async def cmd_start(args) -> int:
    pt = _tools()
    out = await pt.karma_pairing_start(
        agent_name=args.agent_name,
        requested_side=args.side or "",
        requested_vertical=args.vertical or "",
    )
    _dump(out)
    if not out.get("ok"):
        print("\n没有拿到码。先看上面的 detail —— 最常见的两种：", file=sys.stderr)
        print("  · 'All connection attempts failed' -> KARMA_RUNTIME_URL 没配，打到 localhost 了",
              file=sys.stderr)
        print("  · 'Rate limit exceeded' -> 一分钟内请求超过 10 次，等一会儿再来",
              file=sys.stderr)
        return 1
    print("\n把上面的 user_code 填进操作台（或直接打开 verification_uri 那条链接）。",
          file=sys.stderr)
    print("批准之后直接跑：karma-pair claim（不用带码 —— 批准就是交付）", file=sys.stderr)
    return 0


async def cmd_status(args) -> int:
    pt = _tools()
    out = await pt.karma_pairing_status(user_code=args.user_code or "")
    _dump(out)
    return 0 if out.get("ok") else 1


async def cmd_local_status(args) -> int:
    pt = _tools()
    out = await pt.karma_pairing_local_status()
    _dump(out)
    return 0


async def cmd_claim(args) -> int:
    pt = _tools()
    out = await pt.karma_pairing_claim(
        handoff_code=args.handoff_code,
        user_code=args.user_code or "",
    )
    _dump(out)
    if out.get("ok"):
        print("\n凭据已落到本机，正在跑的 agent 不用重启就能用。", file=sys.stderr)
        return 0
    print("\n没领到。看上面的 ask_owner：多半是主人还没批准，或者他点过「签发交接码」"
          "那就得把码带在命令行里。", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="karma-pair",
        description="Pair this machine with Karma without handing codes to an LLM.")
    parser.add_argument("--runtime-url", default=None,
                        help="Karma node (default %s)" % DEFAULT_RUNTIME_URL)
    sub = parser.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("start", help="open a pairing request and print the code")
    start.add_argument("--agent-name", default="", help="what this agent calls itself")
    start.add_argument("--side", default="", choices=["", "buyer", "seller"])
    start.add_argument("--vertical", default="")
    start.set_defaults(func=lambda a: _run(a, cmd_start))

    status = sub.add_parser("status", help="where is this pairing now")
    status.add_argument("--user-code", default="")
    status.set_defaults(func=lambda a: _run(a, cmd_status))

    local = sub.add_parser("local-status", help="what this machine is holding")
    local.set_defaults(func=lambda a: _run(a, cmd_local_status))

    claim = sub.add_parser("claim", help="pick up the credentials the owner already approved")
    claim.add_argument("handoff_code", nargs="?", default="",
                       help="only if the owner additionally issued a handoff code")
    claim.add_argument("--user-code", default="")
    claim.set_defaults(func=lambda a: _run(a, cmd_claim))
    return parser


def _run(args, func):
    return asyncio.run(func(args))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.runtime_url:
        os.environ["KARMA_RUNTIME_URL"] = args.runtime_url
    _default_runtime_url()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
