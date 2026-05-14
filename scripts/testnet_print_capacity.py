#!/usr/bin/env python3
"""Print buyer/seller AccountState and whether createBill would hit CapacityInsufficient (0x56daf627)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from web3 import Web3

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trusted_agent_runtime.testnet_client import (
    account_from_env,
    connect_web3,
    describe_create_bill_capacity_shortfall,
    karma_payment,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seller", default=None, help="Seller address (default TESTNET_SELLER_ADDRESS)")
    p.add_argument("--token", default=None, help="ERC20 (default ERC20_TOKEN_ADDRESS)")
    p.add_argument("--amount", type=int, default=None, help="Bill principal wei (default BILL_AMOUNT_WEI)")
    p.add_argument(
        "--buyer-address",
        default=None,
        help="Buyer address for read-only state (default derived from TESTNET_BUYER_PRIVATE_KEY)",
    )
    args = p.parse_args()

    seller = args.seller or os.environ.get("TESTNET_SELLER_ADDRESS", "").strip()
    token = args.token or os.environ.get("ERC20_TOKEN_ADDRESS", "").strip()
    amount = args.amount if args.amount is not None else int(os.environ.get("BILL_AMOUNT_WEI", "1000000"))
    if not seller or not token:
        raise SystemExit("Need seller and token (flags or env).")

    w3 = connect_web3()
    karma = karma_payment(w3)
    if args.buyer_address:
        buyer = Web3.to_checksum_address(args.buyer_address.strip())
    else:
        buyer = account_from_env("TESTNET_BUYER_PRIVATE_KEY").address

    ok, msg = describe_create_bill_capacity_shortfall(
        w3,
        karma,
        buyer=buyer,
        seller=seller,
        token=token,
        amount=amount,
    )
    print(msg)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
