#!/usr/bin/env python3
"""Buyer confirms a pending bill."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from web3 import Web3

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trusted_agent_runtime.testnet_client import (
    account_from_env,
    append_tx_log,
    connect_web3,
    karma_payment,
    send_contract_tx,
    tx_writeback_record,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bill-id", type=int, required=True)
    p.add_argument("--tx-log", type=Path, default=None)
    args = p.parse_args()

    w3 = connect_web3()
    buyer = account_from_env("TESTNET_BUYER_PRIVATE_KEY")
    karma = karma_payment(w3)
    tx = karma.functions.confirmBill(args.bill_id).build_transaction({"from": buyer.address})
    rc = send_contract_tx(w3, buyer, tx)
    print("confirmBill tx:", Web3.to_hex(rc.transactionHash))
    if args.tx_log:
        append_tx_log(
            args.tx_log,
            tx_writeback_record(
                w3,
                step="confirmBill",
                receipt=rc,
                contract_address=karma.address,
                settlement_status="bill_confirmed",
                extra={"bill_id": args.bill_id},
            ),
        )


if __name__ == "__main__":
    main()
