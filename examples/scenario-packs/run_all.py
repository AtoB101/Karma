#!/usr/bin/env python3
"""
Karma 场景包 · 五个场景依次跑一遍
===================================

    python run_all.py --wallets wallets.json
    python run_all.py --only 02-food-delivery 05-cross-border-ecommerce

一个场景失败不会拖累其他场景（各自独立子进程）。最后给一张汇总表：
每个场景跑到了哪个状态、task_id 是多少、总共花了多少秒。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ORDER = [
    "01-data-api",
    "02-food-delivery",
    "03-ride-hailing",
    "04-hotel-booking",
    "05-cross-border-ecommerce",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="依次跑完所有 Karma 场景包")
    ap.add_argument("--base", default=os.environ.get("KARMA_BASE_URL", "https://karma-network.ai"))
    ap.add_argument("--wallets", default=None)
    ap.add_argument("--only", nargs="*", default=None, help="只跑指定场景目录")
    args = ap.parse_args()

    packs = [p for p in (args.only or ORDER) if (HERE / p / "scenario.json").is_file()]
    if not packs:
        raise SystemExit("没有找到场景包目录")
    wallets = ["--wallets", args.wallets] if args.wallets else []

    rows = []
    for pack in packs:
        scenario = json.loads((HERE / pack / "scenario.json").read_text(encoding="utf-8"))
        print("\n" + "=" * 72, flush=True)
        print("▶ %s  (%s)  %s USDC" % (pack, scenario["scene_id"], scenario["amount_usdc"]), flush=True)
        print("=" * 72, flush=True)
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, str(HERE / "run_scenario.py"), pack, "--base", args.base] + wallets,
            cwd=str(HERE),
        )
        took = time.time() - t0
        rows.append(
            {
                "pack": pack,
                "scene_id": scenario["scene_id"],
                "rc": proc.returncode,
                "ok": proc.returncode == 0,
                "seconds": round(took, 1),
            }
        )

    print("\n" + "=" * 72)
    print("汇总")
    print("=" * 72)
    for r in rows:
        print("  %-28s %-24s %s  %5.1fs" % (r["pack"], r["scene_id"], "✔ 跑通" if r["ok"] else "✘ 未跑通", r["seconds"]))
    failed = [r["pack"] for r in rows if not r["ok"]]
    print("")
    if failed:
        print("未跑通：" + ", ".join(failed))
        return 1
    print("五个场景全部跑通 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
