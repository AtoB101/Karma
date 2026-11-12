#!/usr/bin/env bash
# 入口包装。真正的核对逻辑在 verify_manifest.py（JSON + JSON-RPC，纯标准库，无依赖）。
#
# 为什么要有这个包装：文档和上线清单里写的是 verify-manifest.sh，人照着敲的是这个名字。
# 为什么是 python：链上那一项要发 JSON-RPC、解析 JSON、做地址大小写归一下面还得比对，
# 用 shell 写这些只会更脆。
#
# 解释器要**真能跑起来**才算数：Windows 上的 python3 可能是 Store 占位程序，
# `command -v` 找得到、一执行就报错。所以这里逐个真跑一次 import 再选。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in python3 python; do
  if command -v "$candidate" > /dev/null 2>&1 \
     && "$candidate" -c 'import json, urllib.request' > /dev/null 2>&1; then
    exec "$candidate" "$HERE/verify_manifest.py" "$@"
  fi
done

echo "FAIL  no usable python3/python interpreter found" >&2
exit 1
