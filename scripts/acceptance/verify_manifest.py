#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deployment-manifest.json 核对器 —— 把「线上跑的是什么」变成可判定的东西。

上线前置条件第 8 条要求「deployment-manifest.json + verify-manifest.sh 与链上一致」。
在它之前，「线上用的是哪个合约地址」只写在服务器 .env 里，谁也不知道它和链上是不是
一回事 —— 只有出事那天才会发现配错了。

三项对齐，从便宜到贵：

  1. 清单自己：结构、必填字段、地址格式、地址有没有重复（离线）
  2. 运行环境：清单 pin 的地址和发布环境里的绑定变量是不是同一批（--env-exec）
  3. 链上：chain_id 对不对、合约地址上到底有没有代码、运营钱包有没有钱（--onchain）

第 3 项对 EOA 查的是**余额**而不是「有没有代码」：结算运营钱包是个钱包，没有代码是
对的，但余额为 0 就等于结算永远发不出去 —— 这正是一条上线前置条件。

只判能判的：环境里没有这个变量就记 SKIP，不猜。探不到链记 SKIP 并退 3（是网络问题，
不是「一致」也不是「不一致」）。

用法:
  verify-manifest.sh [--onchain] [--rpc URL] [--env-exec CMD] [--manifest PATH] [--skip-env]

退出码: 0 = 全过；1 = 有不一致；3 = 链上探不到
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

# RPC 提供方会拒掉 python-urllib 的默认 UA（publicnode 直接 403，实测），必须自带一个。
USER_AGENT = "karma-manifest-verify/1"
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
KINDS = ("contract", "eoa")


class Unreachable(Exception):
    """链上探不到：网络、限流、RPC 挂了。不是「不一致」，别把它判成失败。"""


def out(line: str) -> None:
    print(line, flush=True)


def norm_address(value) -> str:
    return str(value or "").strip().lower()


def load_env(env_exec: str) -> dict:
    if not env_exec:
        return dict(os.environ)
    try:
        proc = subprocess.run(env_exec, shell=True, capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001 - 任何启动失败都要说清楚
        raise SystemExit("FAIL  --env-exec could not run: %s" % exc)
    env: dict = {}
    for line in (proc.stdout or "").splitlines():
        key, sep, value = line.partition("=")
        if sep and ENV_NAME_RE.match(key.strip()):
            env[key.strip()] = value
    if not env:
        raise SystemExit("FAIL  --env-exec produced no KEY=VALUE lines")
    return env


def load_manifest(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit("FAIL  no manifest at %s" % path)
    except json.JSONDecodeError as exc:
        raise SystemExit("FAIL  %s is not valid JSON: %s" % (path, exc))


def check_shape(manifest) -> int:
    """结构检查。返回失败条数（0 表示通过）。"""
    if not isinstance(manifest, dict):
        out("FAIL  manifest is not a JSON object")
        return 1
    fails = 0
    if not isinstance(manifest.get("manifest_version"), int):
        out("FAIL  manifest_version missing or not an int")
        fails += 1
    chain_id = manifest.get("chain_id")
    if not isinstance(chain_id, int) or chain_id <= 0:
        out("FAIL  chain_id missing or not a positive int")
        fails += 1
    if not manifest.get("network"):
        out("FAIL  network missing")
        fails += 1
    contracts = manifest.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        out("FAIL  contracts missing or empty")
        return fails + 1

    seen: dict = {}
    for name in sorted(contracts):
        entry = contracts[name]
        if not isinstance(entry, dict):
            out("FAIL  contracts.%s is not an object" % name)
            fails += 1
            continue
        addr = norm_address(entry.get("address"))
        if not ADDRESS_RE.match(addr):
            out("FAIL  contracts.%s.address is not a 20-byte hex address (%r)"
                % (name, entry.get("address")))
            fails += 1
        elif addr in seen:
            out("FAIL  contracts.%s reuses the address of contracts.%s" % (name, seen[addr]))
            fails += 1
        else:
            seen[addr] = name
        if entry.get("kind") not in KINDS:
            out("FAIL  contracts.%s.kind must be one of %s (got %r)"
                % (name, "/".join(KINDS), entry.get("kind")))
            fails += 1
        env_name = entry.get("env")
        if not isinstance(env_name, str) or not ENV_NAME_RE.match(env_name):
            out("FAIL  contracts.%s.env is not a valid env var name (%r)" % (name, env_name))
            fails += 1

    if fails == 0:
        out("PASS  manifest structure OK (%d contracts, chain %s)" % (len(contracts), chain_id))
    return fails


def check_env(manifest: dict, env: dict) -> int:
    """清单 pin 的值 vs 发布环境里的绑定变量。读不到就 SKIP，不猜。"""
    fails = 0
    compared = 0
    for field, var in sorted((manifest.get("chain_bindings") or {}).items()):
        got = env.get(var)
        if got is None:
            out("SKIP  %s not in this environment - cannot compare" % var)
            continue
        compared += 1
        if str(manifest.get(field)).strip().lower() != str(got).strip().lower():
            out("FAIL  %s = %s but the manifest pins %s = %s"
                % (var, str(got).strip(), field, manifest.get(field)))
            fails += 1

    for name in sorted((manifest.get("contracts") or {})):
        entry = manifest["contracts"][name]
        if not isinstance(entry, dict):
            continue
        var = entry.get("env")
        if not var:
            continue
        got = env.get(var)
        if got is None:
            out("SKIP  %s (contracts.%s) not in this environment - cannot compare" % (var, name))
            continue
        compared += 1
        if norm_address(got) != norm_address(entry.get("address")):
            out("FAIL  %s = %s but the manifest pins contracts.%s = %s"
                % (var, str(got).strip(), name, entry.get("address")))
            fails += 1

    if fails == 0:
        out("PASS  release env matches the manifest (%d binding(s) compared)" % compared)
    return fails


def rpc_call(rpc_url: str, method: str, params: list, timeout: int = 25):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        rpc_url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise Unreachable("%s -> HTTP %s" % (method, exc.code))
    except Exception as exc:  # noqa: BLE001
        raise Unreachable("%s -> %s" % (method, exc))
    if payload.get("error"):
        raise Unreachable("%s -> RPC error %s" % (method, payload["error"]))
    return payload.get("result")


def check_onchain(manifest: dict, rpc_url: str) -> int:
    """链上事实：chain_id / 合约有没有代码 / 钱包有没有钱。"""
    fails = 0
    chain_id = manifest.get("chain_id")
    got = int(rpc_call(rpc_url, "eth_chainId", []), 16)
    if got != chain_id:
        out("FAIL  chain id mismatch: the manifest pins %s, %s reports %s" % (chain_id, rpc_url, got))
        fails += 1
    else:
        out("PASS  chain id matches the manifest (%s)" % chain_id)

    for name in sorted((manifest.get("contracts") or {})):
        entry = manifest["contracts"][name]
        if not isinstance(entry, dict):
            continue
        addr = entry.get("address")
        if entry.get("kind") == "contract":
            code = rpc_call(rpc_url, "eth_getCode", [addr, "latest"]) or "0x"
            size = max(0, len(code) - 2) // 2
            if size == 0:
                out("FAIL  contracts.%s (%s) has no code on chain %s" % (name, addr, chain_id))
                fails += 1
            else:
                out("PASS  contracts.%s has %d bytes of code on chain %s" % (name, size, chain_id))
        else:
            balance = rpc_call(rpc_url, "eth_getBalance", [addr, "latest"]) or "0x0"
            wei = int(balance, 16)
            if wei == 0:
                out("FAIL  contracts.%s (%s) is an EOA with 0 wei - it cannot pay for settlement txs"
                    % (name, addr))
                fails += 1
            else:
                out("PASS  contracts.%s funded with %.6f ETH on chain %s"
                    % (name, wei / 1e18, chain_id))

    if fails == 0:
        out("PASS  on-chain state matches the manifest")
    return fails


def default_manifest_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))          # scripts/acceptance
    root = os.path.dirname(os.path.dirname(here))              # repo root
    return os.path.join(root, "deployment-manifest.json")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="verify deployment-manifest.json against env and chain")
    ap.add_argument("--manifest", default=os.environ.get("KARMA_DEPLOYMENT_MANIFEST") or default_manifest_path())
    ap.add_argument("--env-exec", default="")
    ap.add_argument("--onchain", action="store_true")
    ap.add_argument("--rpc", default="")
    ap.add_argument("--skip-env", action="store_true")
    args = ap.parse_args(argv)

    manifest = load_manifest(args.manifest)
    fails = check_shape(manifest)
    if fails:
        out("MANIFEST: FAIL")
        return 1

    if not args.skip_env:
        fails += check_env(manifest, load_env(args.env_exec))

    if args.onchain:
        rpc_url = args.rpc or manifest.get("rpc_url") or ""
        if not rpc_url:
            out("SKIP  no rpc_url in the manifest and no --rpc given")
        else:
            try:
                fails += check_onchain(manifest, rpc_url)
            except Unreachable as exc:
                out("SKIP  on-chain probe could not reach %s (%s)" % (rpc_url, exc))
                # 链上探不到不该掩盖已经查出来的不一致：环境对不上就是 FAIL，
                # 只是「链上这一项没查成」而已。
                if fails:
                    out("MANIFEST: FAIL")
                    return 1
                out("MANIFEST: UNREACHABLE")
                return 3

    out("MANIFEST: %s" % ("FAIL" if fails else "OK"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
