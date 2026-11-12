#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""链上核对：把资金回归报告里的期望逐条对到链上交易回执上。

回归脚本（money_path_regression.py）证明的是「产品说钱动了」；这一支证明**钱真的动了**：
读那笔交易的 receipt，在 ERC20 的 Transfer 日志里找出「谁 -> 谁、多少」，
和期望里的方向、金额、钱包逐项比对。

用法（在有 RPC 的机器上跑，生产上就是 karma-api 容器里）：

  python scripts/regression/chain_assert.py --report /tmp/report.json \
      --buyer-wallet 0xBuyer --seller-wallet 0xSeller --out /tmp/chain.json

退出码：0 = 全部对上；1 = 有对不上的（明细写在 --out 的 JSON 里）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from config.settings import settings  # noqa: E402

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
EPS = 1e-6


def _addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def main() -> int:
    ap = argparse.ArgumentParser(description="链上核对资金回归的期望")
    ap.add_argument("--report", required=True, help="money_path_regression.py 出的报告 JSON")
    ap.add_argument("--out", default=None, help="核对结果 JSON 落盘路径")
    ap.add_argument("--rpc", default=None, help="覆盖 settings.testnet_rpc_url")
    ap.add_argument("--token", default=None, help="覆盖 settings.erc20_token_address")
    ap.add_argument("--buyer-wallet", default=None)
    ap.add_argument("--seller-wallet", default=None)
    args = ap.parse_args()

    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)

    rpc = args.rpc or settings.testnet_rpc_url
    token = (args.token or settings.erc20_token_address or "").lower()
    wallets = {"buyer": (args.buyer_wallet or "").lower(),
               "seller": (args.seller_wallet or "").lower()}
    if not rpc or not token:
        print("缺 RPC 或代币地址：无法做链上核对", file=sys.stderr)
        return 1

    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))

    results = []
    for exp in report.get("chain_expectations") or []:
        item = {"label": exp.get("label"), "task_id": exp.get("task_id"),
                "tx_hash": exp.get("tx_hash"), "ok": False}
        tx = exp.get("tx_hash")
        if not tx:
            item["error"] = "报告里没有 tx_hash（结算行没回写链上交易）"
            results.append(item)
            continue
        try:
            rcpt = w3.eth.get_transaction_receipt(tx)
        except Exception as exc:  # noqa: BLE001
            item["error"] = "读不到回执：%s" % str(exc)[:200]
            results.append(item)
            continue
        item["status"] = rcpt["status"]
        item["block"] = rcpt["blockNumber"]
        want = exp.get("transfer") or {}
        frm = (want.get("from") or wallets.get(want.get("from_role") or "", "")).lower()
        to = (want.get("to") or wallets.get(want.get("to_role") or "", "")).lower()
        amount = float(want.get("amount_usdc") or 0.0)
        transfers = []
        for lg in rcpt["logs"]:
            if (lg["address"] or "").lower() != token:
                continue
            topics = lg["topics"]
            if not topics or ("0x" + topics[0].hex().lstrip("0x")).lower() != TRANSFER_TOPIC:
                continue
            if len(topics) < 3:
                continue
            src, dst = _addr(topics[1].hex()), _addr(topics[2].hex())
            try:
                value = int(lg["data"].hex(), 16) / 1e6
            except Exception:  # noqa: BLE001
                continue
            transfers.append({"from": src, "to": dst, "amount_usdc": value})
        item["transfers"] = transfers
        hit = [t for t in transfers
               if (not frm or t["from"] == frm)
               and (not to or t["to"] == to)
               and abs(t["amount_usdc"] - amount) <= EPS]
        item["ok"] = rcpt["status"] == 1 and bool(hit)
        if rcpt["status"] != 1:
            item["error"] = "交易失败（status=%s）" % rcpt["status"]
        elif not hit:
            item["error"] = "没找到期望的转账：%s -> %s %s（实际 %s）" % (
                frm or "*", to or "*", amount, transfers)
        results.append(item)

    ok = all(r["ok"] for r in results) if results else False
    out = {"ok": ok, "token": token, "results": results}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
