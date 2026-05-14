#!/usr/bin/env python3
"""Buyer creates a bill on NonCustodialAgentPayment (hybrid: proofHash + scopeHash on-chain)."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from web3 import Web3

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trusted_agent_runtime.proof_hash_format import assert_canonical_karma_proof_hash
from trusted_agent_runtime.testnet_client import (
    account_from_env,
    append_tx_log,
    bill_id_from_create_receipt,
    connect_web3,
    karma_payment,
    send_contract_tx,
    tx_writeback_record,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seller", default=None, help="Seller address (default TESTNET_SELLER_ADDRESS)")
    p.add_argument("--token", default=None, help="ERC20 (default ERC20_TOKEN_ADDRESS)")
    p.add_argument("--amount", type=int, default=None, help="Bill principal (default BILL_AMOUNT_WEI)")
    p.add_argument("--proof-hash", default=None, help="String proofHash (default KARMA_PROOF_HASH)")
    p.add_argument("--scope-hex", default=None, help="bytes32 as 0x… hex (default KARMA_SCOPE_HEX)")
    p.add_argument("--deadline", type=int, default=None, help="Unix deadline (default now+7d)")
    p.add_argument("--tx-log", type=Path, default=None)
    p.add_argument(
        "--skip-proof-format-check",
        action="store_true",
        help="Do not validate karma-ta proofHash shape (only for non-hybrid pointers like ipfs://…)",
    )
    args = p.parse_args()

    seller = args.seller or os.environ.get("TESTNET_SELLER_ADDRESS", "").strip()
    token = args.token or os.environ.get("ERC20_TOKEN_ADDRESS", "").strip()
    amount = args.amount if args.amount is not None else int(os.environ.get("BILL_AMOUNT_WEI", "1000000"))
    proof = args.proof_hash or os.environ.get("KARMA_PROOF_HASH", "").strip()
    scope = args.scope_hex or os.environ.get("KARMA_SCOPE_HEX", "").strip()
    if not seller or not token or not proof or not scope:
        raise SystemExit("Need seller, token, proof hash, and scope (flags or env).")
    if not args.skip_proof_format_check:
        try:
            proof = assert_canonical_karma_proof_hash(proof)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    deadline = args.deadline if args.deadline is not None else int(time.time()) + 7 * 86400

    w3 = connect_web3()
    buyer = account_from_env("TESTNET_BUYER_PRIVATE_KEY")
    karma = karma_payment(w3)
    tx = karma.functions.createBill(
        Web3.to_checksum_address(seller),
        Web3.to_checksum_address(token),
        amount,
        Web3.to_bytes(hexstr=scope),
        proof,
        deadline,
    ).build_transaction({"from": buyer.address})
    rc = send_contract_tx(w3, buyer, tx)
    bill_id = bill_id_from_create_receipt(karma, rc)
    print("bill_id:", bill_id)
    print("createBill tx:", Web3.to_hex(rc.transactionHash))
    if args.tx_log:
        append_tx_log(
            args.tx_log,
            tx_writeback_record(
                w3,
                step="createBill",
                receipt=rc,
                contract_address=karma.address,
                settlement_status="bill_created",
                extra={"bill_id": bill_id},
            ),
        )


if __name__ == "__main__":
    main()
