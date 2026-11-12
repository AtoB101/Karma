#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一次资金回归的失败写进操作台「站内提醒」（在 karma-api 容器里跑）。

为什么不在公共 API 上开一个入口：那等于让任何人能给任意身份塞提醒。
这个脚本只在服务器容器里跑，走的是服务端自己的落库函数。

用法：

  docker exec -w /app karma-api python /tmp/report_alert.py \
      --identity kid_xxx --summary "dispute: 3 条断言失败" [--report /tmp/report.json]

退出码：0 = 提醒已写入；1 = 写失败（原因打到 stderr）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

def _repo_root() -> str:
    """脚本会被 ``docker cp`` 到 ``/tmp`` 里跑，那个位置推不出仓库根。

    ``/tmp/../..`` 一层层推上去是 ``/``，于是 ``import services`` 会摸到
    site-packages 里那个同名包（真机上就是这样：``ImportError: cannot import name
    'console_notice'``，报警静默失败）。先认环境变量，再试脚本旁边，最后回落到容器
    里的 ``/app``。
    """
    env = (os.environ.get("KARMA_REPO_ROOT") or "").strip()
    if env and os.path.isdir(env):
        return env
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.isdir(os.path.join(here, "services")):
        return here
    return "/app"


REPO_ROOT = _repo_root()
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from db.session import AsyncSessionLocal  # noqa: E402
from services import console_notice  # noqa: E402

KIND = "money_regression_failed"


async def main() -> int:
    ap = argparse.ArgumentParser(description="资金回归失败 -> 操作台站内提醒")
    ap.add_argument("--identity", required=True, help="提醒写给谁（操作台主人的身份 id）")
    ap.add_argument("--summary", required=True, help="一句话说清哪一步没过")
    ap.add_argument("--report", default=None, help="回归报告路径（会摘出失败断言写进 payload）")
    args = ap.parse_args()

    failed = []
    if args.report:
        try:
            with open(args.report, encoding="utf-8") as fh:
                rep = json.load(fh)
            for name, sc in (rep.get("scenarios") or {}).items():
                for c in sc.get("checks") or []:
                    if not c.get("ok"):
                        failed.append({"scenario": name, "check": c.get("name"),
                                       "detail": c.get("detail")})
        except Exception as exc:  # noqa: BLE001
            print("读报告失败（不影响写提醒）：%s" % exc, file=sys.stderr)

    async with AsyncSessionLocal() as db:
        row = await console_notice.add_notice(
            db,
            karma_identity_id=args.identity,
            kind=KIND,
            payload={
                "summary": args.summary,
                "failed_checks": failed[:8],
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        await db.commit()
        print("notice written id=%s kind=%s" % (row.id, row.kind))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
