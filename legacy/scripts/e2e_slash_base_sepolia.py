#!/usr/bin/env python3
"""P0-2: VerifierRegistry slash really moves tokens (Base Sepolia).

The audit found registerVerifier recorded stake as a number and slash() did
not transfer anything. Staking was already proven real in the attestation E2E;
this script proves the penalty side: slash() actually moves the staking token
from the registry to the configured slash recipient and deactivates a verifier
that falls below the minimum stake.

Deploys a fresh VerifierRegistry + MockERC20 so the already-deployed stack is
left untouched.

Env:
  ADMIN_PRIVATE_KEY   required: Base Sepolia deployer/admin key
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from web3 import Web3
from eth_account import Account

_NONCES: dict = {}


def _nonce(w3, acct):
    key = acct.address.lower()
    n = _NONCES.get(key)
    if n is None:
        n = w3.eth.get_transaction_count(acct.address, "pending")
    _NONCES[key] = n + 1
    return n

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "karma-sdk" / "python"))

RPC = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
CHAIN_ID = 84532
ADMIN_KEY = os.getenv("ADMIN_PRIVATE_KEY", "")

MIN_STAKE = 1_000_000    # 1 mUSDC (6 decimals)
ETH_STIPEND = Web3.to_wei(0.002, "ether")

OUT = ROOT / "karma-core" / "contracts" / "out"


def load(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def send_tx(w3, acct, fn, gas=3_000_000):
    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": _nonce(w3, acct),
        "gas": gas,
    })
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f"tx {tx_hash.hex()} reverted")
    return receipt


def fund(w3, admin, to, value):
    tx = {
        "from": admin.address,
        "to": Web3.to_checksum_address(to),
        "value": value,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
        "nonce": _nonce(w3, admin),
    }
    signed = admin.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(h, timeout=120)


def _wait_until(cond, label, timeout=60, interval=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        print(f"\r  waiting {label}...", end="", flush=True)
        time.sleep(interval)
    print("")
    if not cond():
        raise TimeoutError(f"timed out waiting for {label}")


def main() -> int:
    if not ADMIN_KEY:
        print("Set ADMIN_PRIVATE_KEY env var.")
        return 2

    w3 = Web3(Web3.HTTPProvider(RPC))
    assert w3.is_connected()
    assert w3.eth.chain_id == CHAIN_ID
    admin = Account.from_key(ADMIN_KEY)
    print(f"chain    {w3.eth.chain_id} ({RPC})")
    print(f"admin    {admin.address}")

    # 1. fresh MockERC20 + fresh VerifierRegistry
    mock_artifact = load(OUT / "MockERC20.sol" / "MockERC20.json")
    Mock = w3.eth.contract(abi=mock_artifact["abi"], bytecode=mock_artifact["bytecode"]["object"])
    mock_addr = send_tx(w3, admin, Mock.constructor())["contractAddress"]
    mock = w3.eth.contract(address=mock_addr, abi=mock_artifact["abi"])

    reg_artifact = load(OUT / "VerifierRegistry.sol" / "VerifierRegistry.json")
    Reg = w3.eth.contract(abi=reg_artifact["abi"], bytecode=reg_artifact["bytecode"]["object"])
    reg_addr = send_tx(w3, admin, Reg.constructor(admin.address))["contractAddress"]
    registry = w3.eth.contract(address=reg_addr, abi=reg_artifact["abi"])

    send_tx(w3, admin, registry.functions.setStakingConfig(mock_addr, MIN_STAKE, 0))
    print(f"mock     {mock_addr}")
    print(f"registry {reg_addr}")

    # 2. distinct slash recipient (proof funds land where configured)
    treasury = Account.create()
    send_tx(w3, admin, registry.functions.setSlashRecipient(treasury.address))
    print(f"treasury {treasury.address}")

    # 3. one active verifier with real stake
    verifier = Account.create()
    if w3.eth.get_balance(verifier.address) < ETH_STIPEND:
        fund(w3, admin, verifier.address, ETH_STIPEND)
    send_tx(w3, admin, registry.functions.registerVerifier(verifier.address, "https://v1.e2e.karma", 0))
    send_tx(w3, admin, mock.functions.mint(verifier.address, MIN_STAKE))
    send_tx(w3, verifier, mock.functions.approve(reg_addr, MIN_STAKE))
    send_tx(w3, verifier, registry.functions.stake(MIN_STAKE))
    _wait_until(lambda: registry.functions.isActiveVerifier(verifier.address).call(), "verifier active")
    print(f"verifier {verifier.address} active, stake={MIN_STAKE}")

    # 4. record balances, then slash the full stake
    stake_before = registry.functions.verifiers(verifier.address).call()[3]
    treasury_before = mock.functions.balanceOf(treasury.address).call()
    registry_before = mock.functions.balanceOf(reg_addr).call()
    assert stake_before == MIN_STAKE

    send_tx(w3, admin, registry.functions.slash(verifier.address, MIN_STAKE, "false-attestation-e2e"))
    _wait_until(lambda: registry.functions.verifiers(verifier.address).call()[3] == 0, "stake zeroed")
    _wait_until(lambda: not registry.functions.isActiveVerifier(verifier.address).call(), "verifier deactivated")

    info = registry.functions.verifiers(verifier.address).call()
    treasury_after = mock.functions.balanceOf(treasury.address).call()
    registry_after = mock.functions.balanceOf(reg_addr).call()

    # 5. real token movement + deactivation checks
    assert info[3] == 0, f"stake should be 0, got {info[3]}"
    assert info[7] == MIN_STAKE, f"slashedAmount should be {MIN_STAKE}, got {info[7]}"
    assert treasury_after - treasury_before == MIN_STAKE, "treasury did not receive slashed stake"
    assert registry_before - registry_after == MIN_STAKE, "registry did not release slashed stake"

    print(f"slash    stake 0, slashed={info[7]}, active={registry.functions.isActiveVerifier(verifier.address).call()}")
    print(f"move     treasury +{(treasury_after - treasury_before)/1e6} mUSDC, registry -{(registry_before - registry_after)/1e6} mUSDC")

    print("\nP0-2 SLASH E2E PASSED")
    print(f"  registry={reg_addr}")
    print(f"  mock={mock_addr}")
    print(f"  treasury={treasury.address}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
