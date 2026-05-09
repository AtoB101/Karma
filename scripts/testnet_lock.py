#!/usr/bin/env python3
"""Lock logical funds on NonCustodialAgentPayment (buyer or seller). Requires prior ERC20 approve."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from web3 import Web3

from trusted_agent_runtime.testnet_client import (
    account_from_env,
    append_tx_log,
    approve_max,
    connect_web3,
    erc20_token,
    karma_payment,
    lock_party,
    tx_writeback_record,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--party", choices=("buyer", "seller"), required=True)
    p.add_argument("--amount", type=int, required=True, help="Lock amount (wei / smallest unit)")
    p.add_argument("--tx-log", type=Path, default=None, help="Append JSONL tx records")
    args = p.parse_args()

    env_key = "TESTNET_BUYER_PRIVATE_KEY" if args.party == "buyer" else "TESTNET_SELLER_PRIVATE_KEY"
    acct = account_from_env(env_key)
    w3 = connect_web3()
    karma = karma_payment(w3)
    token_addr = os.environ.get("ERC20_TOKEN_ADDRESS", "").strip()
    token_c = erc20_token(w3, token_addr)

    rc_approve = approve_max(w3, token_c, acct, karma.address)
    print("approve tx:", Web3.to_hex(rc_approve.transactionHash))
    if args.tx_log:
        append_tx_log(
            args.tx_log,
            tx_writeback_record(
                w3,
                step="erc20_approve",
                receipt=rc_approve,
                contract_address=token_addr,
                settlement_status="approve_protocol",
            ),
        )

    rc_lock = lock_party(w3, karma, acct, token_addr, args.amount)
    print("lockFunds tx:", Web3.to_hex(rc_lock.transactionHash))
    if args.tx_log:
        append_tx_log(
            args.tx_log,
            tx_writeback_record(
                w3,
                step="lockFunds",
                receipt=rc_lock,
                contract_address=karma.address,
                settlement_status=f"lock_{args.party}",
            ),
        )


if __name__ == "__main__":
    main()
