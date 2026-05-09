#!/usr/bin/env python3
"""
Phase 3 hybrid: offchain receipts/bundle/verify + on-chain proofHash/scope + settlement txs.

  python3 scripts/testnet_full_flow.py --output-dir results/ta-hybrid [--send]

With --send, requires TESTNET_* env vars and funded buyer/seller token balances.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from web3 import Web3

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trusted_agent_runtime.demo_payload import build_demo_offchain_bundle
from trusted_agent_runtime.settlement_adapter import SettlementAdapter
from trusted_agent_runtime.testnet_client import (
    account_from_env,
    append_tx_log,
    approve_max,
    bill_id_from_create_receipt,
    connect_web3,
    erc20_token,
    karma_payment,
    lock_party,
    send_contract_tx,
    tx_writeback_record,
)


def _write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_onchain(payload: dict, tx_log: Path | None) -> dict:
    w3 = connect_web3()
    buyer = account_from_env("TESTNET_BUYER_PRIVATE_KEY")
    seller = account_from_env("TESTNET_SELLER_PRIVATE_KEY")
    seller_addr = os.environ.get("TESTNET_SELLER_ADDRESS", "").strip()
    if not seller_addr:
        raise SystemExit("TESTNET_SELLER_ADDRESS required for createBill")
    seller_addr = Web3.to_checksum_address(seller_addr)
    token_addr = os.environ.get("ERC20_TOKEN_ADDRESS", "").strip()
    if not token_addr:
        raise SystemExit("ERC20_TOKEN_ADDRESS required")

    karma = karma_payment(w3)
    token_c = erc20_token(w3, token_addr)
    txs: list[dict] = []

    def log_row(rc, step: str, contract: str, status: str, **kw: object) -> None:
        row = tx_writeback_record(
            w3,
            step=step,
            receipt=rc,
            contract_address=contract,
            settlement_status=status,
            extra={k: v for k, v in kw.items() if v is not None},
        )
        txs.append(row)
        if tx_log:
            append_tx_log(tx_log, row)
        print(step, Web3.to_hex(rc.transactionHash), row["onchain_status"])

    for acct, label in ((buyer, "buyer"), (seller, "seller")):
        rc = approve_max(w3, token_c, acct, karma.address)
        log_row(rc, f"erc20_approve_{label}", token_addr, f"approve_{label}")

    amt = int(os.environ.get("BILL_AMOUNT_WEI", "1000000"))
    bps = int(karma.functions.sellerBondBps().call())
    bond = (amt * bps) // 10_000
    if amt > 0 and bps > 0 and bond == 0:
        bond = 1
    buyer_lock = int(os.environ.get("BUYER_LOCK_WEI", str(max(amt * 5, amt + 1))))
    seller_lock = int(os.environ.get("SELLER_LOCK_WEI", str(max(bond * 5, bond + 1))))

    rc = lock_party(w3, karma, buyer, token_addr, buyer_lock)
    log_row(rc, "lockFunds_buyer", karma.address, "lock_buyer")

    rc = lock_party(w3, karma, seller, token_addr, seller_lock)
    log_row(rc, "lockFunds_seller", karma.address, "lock_seller")

    proof = payload["proof_hash"]
    scope = payload["scope_hex"]
    deadline = int(os.environ.get("BILL_DEADLINE_UNIX", str(int(time.time()) + 7 * 86400)))

    tx = karma.functions.createBill(
        seller_addr,
        Web3.to_checksum_address(token_addr),
        amt,
        Web3.to_bytes(hexstr=scope),
        proof,
        deadline,
    ).build_transaction({"from": buyer.address})
    rc = send_contract_tx(w3, buyer, tx)
    bill_id = bill_id_from_create_receipt(karma, rc)
    log_row(rc, "createBill", karma.address, "bill_created", bill_id=bill_id)

    tx = karma.functions.confirmBill(bill_id).build_transaction({"from": buyer.address})
    rc = send_contract_tx(w3, buyer, tx)
    log_row(rc, "confirmBill", karma.address, "bill_confirmed", bill_id=bill_id)

    tx = karma.functions.requestBillPayout(bill_id).build_transaction({"from": buyer.address})
    rc = send_contract_tx(w3, buyer, tx)
    log_row(rc, "requestBillPayout", karma.address, "payout_requested", bill_id=bill_id)

    return {
        "settlement_mode": os.environ.get("SETTLEMENT_MODE", "hybrid"),
        "bill_id": bill_id,
        "onchain_transactions": txs,
        "chain_id": int(w3.eth.chain_id),
        "noncustodial_contract": karma.address,
        "token": token_addr,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", default="results/trusted-agent-hybrid")
    p.add_argument("--send", action="store_true", help="Submit on-chain txs (requires env + funded wallets)")
    p.add_argument("--tx-log", type=Path, default=None, help="JSONL log path (default: <output-dir>/hybrid_tx_log.jsonl)")
    args = p.parse_args()
    out = Path(args.output_dir)
    tx_log = args.tx_log or (out / "hybrid_tx_log.jsonl")

    payload = build_demo_offchain_bundle()
    _write(out / "task_contract.json", payload["task"])
    _write(out / "receipt_chain.json", payload["receipt_chain"])
    _write(out / "evidence_bundle.json", payload["evidence_bundle"])
    _write(out / "verification_result.json", payload["verification"])

    from trusted_agent_runtime.schemas import EvidenceBundle, TaskContract, VerificationResult

    task = TaskContract(**payload["task"])
    bundle = EvidenceBundle(**payload["evidence_bundle"])
    verify = VerificationResult(**payload["verification"])
    plan = SettlementAdapter().build_offchain_plan(
        task,
        bundle,
        payload["proof_hash"],
        payload["scope_hex"],
        seller=os.environ.get("TESTNET_SELLER_ADDRESS", "0x0000000000000000000000000000000000000000"),
        token=os.environ.get("ERC20_TOKEN_ADDRESS", "0x0000000000000000000000000000000000000000"),
        amount_wei=int(os.environ.get("BILL_AMOUNT_WEI", "1000000")),
        deadline_unix=int(time.time()) + 7 * 86400,
        verify=verify,
    )
    os.environ.setdefault("SETTLEMENT_MODE", "hybrid")
    hybrid: dict = {
        "offchain_plan": plan,
        "bundle_digest": payload["bundle_digest"],
        "karma_proof_hash": payload["proof_hash"],
        "karma_scope_hex": payload["scope_hex"],
    }

    if args.send:
        onchain = _run_onchain(payload, tx_log)
        hybrid["onchain"] = onchain
        hybrid["tx_log_path"] = str(tx_log.resolve())
    else:
        hybrid["onchain"] = {
            "note": "Re-run with --send after setting TESTNET_* env and funding token balances.",
        }

    _write(out / "hybrid_settlement_result.json", hybrid)
    print("OK  hybrid flow artifacts ->", out.resolve())


if __name__ == "__main__":
    main()
