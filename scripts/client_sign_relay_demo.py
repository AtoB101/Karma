"""Client-signing + relay demo (R1): a client signs lock() with their own key,
the backend only relays it — no hot wallet.

This is the production client-signing path: the buyer builds + signs the raw
transaction locally, then POSTs it to /v1/bilateral/relay, which broadcasts it.

Usage:
  python scripts/client_sign_relay_demo.py   # reads TESTNET_PRIVATE_KEY from .env
"""
import os
import httpx
from web3 import Web3
from eth_account import Account

RPC = "https://ethereum-sepolia-rpc.publicnode.com"
USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
BILATERAL = "0xe3C011D4C5e9D8D8A8f11990EcCcDC06924640e7"
API = os.environ.get("KARMA_RUNTIME_URL", "http://127.0.0.1:8010").rstrip("/")

LOCK_ABI = [{
    "name": "lock", "type": "function", "stateMutability": "nonpayable",
    "inputs": [{"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}],
    "outputs": [{"name": "billId", "type": "uint256"}],
}]


def main():
    env = {}
    for line in open(".env", encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    buyer = Account.from_key(env["TESTNET_PRIVATE_KEY"])

    w3 = Web3(Web3.HTTPProvider(RPC))
    contract = w3.eth.contract(address=Web3.to_checksum_address(BILATERAL), abi=LOCK_ABI)

    # 1. client builds the lock transaction
    tx = contract.functions.lock(Web3.to_checksum_address(USDC), 5_000_000).build_transaction({
        "from": buyer.address,
        "nonce": w3.eth.get_transaction_count(buyer.address),
        "chainId": w3.eth.chain_id,
    })

    # 2. client signs it locally (no hot wallet / backend key involved)
    signed = buyer.sign_transaction(tx)
    raw_tx = signed.raw_transaction.hex()

    # 3. client sends the signed raw tx to the API; backend only relays
    r = httpx.post(f"{API}/v1/bilateral/relay", json={"raw_tx": raw_tx}, timeout=120)
    print("relay status:", r.status_code, r.text[:300])

    assert r.status_code == 200, "relay failed"
    print("\n[OK] CLIENT-SIGNED RELAY: PASS (buyer signed lock locally, backend broadcast it)")


if __name__ == "__main__":
    main()
