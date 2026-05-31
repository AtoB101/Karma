#!/usr/bin/env python3
"""Karma Testnet mUSDC Faucet — dispense 100 mUSDC to any Sepolia address.

Usage:
  python3 scripts/faucet.py 0xYourAddress
  python3 scripts/faucet.py 0xYourAddress --amount 200  # 200 mUSDC

Admin wallet must be funded with mUSDC and Sepolia ETH for gas.
"""

import sys, os
from web3 import Web3

RPC = os.environ.get("SEPOLIA_RPC", "https://sepolia.infura.io/v3/a9a3c01e8b98471eb79d07eb16553236")
USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
ADMIN_KEY = os.environ.get("FAUCET_KEY", "")

if not ADMIN_KEY:
    ADMIN_KEY = "2f9cf6d82fb25f2cf8d4ccfd34bd54b0d8ad5dda0e3b0b99a4280a14dde4690a"

USDC_ABI = [
    {"name":"transfer","type":"function","inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"outputs":[{"name":"","type":"bool"}]},
    {"name":"balanceOf","type":"function","inputs":[{"name":"a","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},
]

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/faucet.py 0xAddress [--amount 100]")
        sys.exit(1)

    to = sys.argv[1]
    amount = 100  # default 100 mUSDC
    if "--amount" in sys.argv:
        idx = sys.argv.index("--amount")
        amount = int(sys.argv[idx + 1])

    w3 = Web3(Web3.HTTPProvider(RPC))
    admin = w3.eth.account.from_key(ADMIN_KEY)
    usdc = w3.eth.contract(address=USDC, abi=USDC_ABI)

    # Check balances
    eth = w3.eth.get_balance(admin.address)
    bal = usdc.functions.balanceOf(admin.address).call()
    needed = amount * 1_000_000

    if bal < needed:
        print(f"❌ Insufficient mUSDC: have {bal/1e6}, need {amount}")
        sys.exit(1)

    # Send
    tx = usdc.functions.transfer(Web3.to_checksum_address(to), needed).build_transaction({
        "from": admin.address,
        "nonce": w3.eth.get_transaction_count(admin.address),
        "gas": 100000,
    })
    signed = admin.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=60)

    if receipt.status == 1:
        print(f"✅ Sent {amount} mUSDC to {to}")
        print(f"   TX: https://sepolia.etherscan.io/tx/{h.hex()}")
    else:
        print(f"❌ Transaction failed: {h.hex()}")

if __name__ == "__main__":
    main()
