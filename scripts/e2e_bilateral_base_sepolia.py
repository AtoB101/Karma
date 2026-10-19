#!/usr/bin/env python3
"""KarmaBilateral Base Sepolia happy-path E2E (validates the fixed karma_sdk).

Runs against the already-deployed KarmaBilateral on Base Sepolia and exercises
the Python SDK end-to-end so the earlier SDK bugs (nonce race, gas ceiling,
event ABI missing `anonymous`, getBinding missing settleSubmittedAt) are proven
fixed against a live chain.

Because the official Base Sepolia USDC faucet is hard to obtain, this script
deploys its own open-mint MockERC20 and allowlists it on the existing contract.

Flow:
  deploy MockERC20 -> admin allowlists token + shortens windows ->
  buyer/agent lock 10 each -> bind -> settle (FINALIZING) -> finalize (SETTLED)
  -> assert bills burned + invariant holds + payouts land correctly.

Env:
  ADMIN_PRIVATE_KEY   required: Base Sepolia deployer/admin key
  BUYER_PRIVATE_KEY   optional: buyer key (defaults to a fresh random account)
  AGENT_PRIVATE_KEY   optional: agent key (defaults to a fresh random account)
  BASE_SEPOLIA_RPC    optional: RPC endpoint (default https://sepolia.base.org)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "karma-sdk" / "python"))

from web3 import Web3
from eth_account import Account
from karma_sdk import KarmaBilateral

RPC = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
CHAIN_ID = 84532

KARMA = "0x3D633d55Bb7bDD4Af55a92C0F48dd25B7f06c3A5"
ADMIN_KEY = os.getenv("ADMIN_PRIVATE_KEY", "")

SETTLE_DELAY = 60       # seconds after bind before settle()
FINALIZE_WINDOW = 120   # seconds after settle() before finalizeSettle()
AMOUNT = 10_000_000     # 10 mUSDC (6 decimals)
ETH_STIPEND = Web3.to_wei(0.005, "ether")

MOCK_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "MockERC20.sol" / "MockERC20.json"
KARMA_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "KarmaBilateral.sol" / "KarmaBilateral.json"


def load_artifact(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def send_tx(w3: Web3, acct, fn, gas: int = 2_000_000):
    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "gas": gas,
    })
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f"tx {tx_hash.hex()} reverted")
    return receipt


def fund(w3: Web3, admin, to_address: str, value: int):
    tx = {
        "from": admin.address,
        "to": Web3.to_checksum_address(to_address),
        "value": value,
        "gas": 21000,
        "nonce": w3.eth.get_transaction_count(admin.address, "pending"),
    }
    signed = admin.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)


def countdown(seconds: int, label: str):
    print(f"\n  waiting {seconds}s for {label}...", flush=True)
    while seconds > 0:
        print(f"\r  {seconds:>3}s remaining", end="", flush=True)
        step = min(15, seconds)
        time.sleep(step)
        seconds -= step
    print("")


def main() -> int:
    if not ADMIN_KEY:
        print("Set ADMIN_PRIVATE_KEY env var to the Base Sepolia deployer key.")
        return 2

    w3 = Web3(Web3.HTTPProvider(RPC))
    assert w3.is_connected(), f"RPC unreachable: {RPC}"
    assert w3.eth.chain_id == CHAIN_ID, f"unexpected chain {w3.eth.chain_id}"

    admin = Account.from_key(ADMIN_KEY)
    print(f"chain    {w3.eth.chain_id} ({RPC})")
    print(f"admin    {admin.address}")
    print(f"karma    {KARMA}")

    karma_abi = load_artifact(KARMA_ARTIFACT)["abi"]
    karma = w3.eth.contract(address=Web3.to_checksum_address(KARMA), abi=karma_abi)

    # -- 1. Deploy MockERC20 (open mint; avoids the Base USDC faucet) ------
    mock_artifact = load_artifact(MOCK_ARTIFACT)
    Mock = w3.eth.contract(abi=mock_artifact["abi"], bytecode=mock_artifact["bytecode"]["object"])
    receipt = send_tx(w3, admin, Mock.constructor(), gas=2_000_000)
    mock_addr = receipt["contractAddress"]
    mock = w3.eth.contract(address=mock_addr, abi=mock_artifact["abi"])
    print(f"mock     {mock_addr}")

    # -- 2. Admin: allowlist token + shorten windows for the test ---------
    send_tx(w3, admin, karma.functions.setTokenAllowed(mock_addr, True))
    send_tx(w3, admin, karma.functions.setDisputeWindow(SETTLE_DELAY))
    send_tx(w3, admin, karma.functions.setOptimisticDisputeWindow(FINALIZE_WINDOW))
    print(f"windows  settle_delay={SETTLE_DELAY}s finalize={FINALIZE_WINDOW}s")

    # -- 3. Buyer / agent accounts + funding ------------------------------
    buyer_key = os.getenv("BUYER_PRIVATE_KEY") or Account.create().key.hex()
    agent_key = os.getenv("AGENT_PRIVATE_KEY") or Account.create().key.hex()
    buyer = Account.from_key(buyer_key)
    agent = Account.from_key(agent_key)

    if w3.eth.get_balance(buyer.address) < ETH_STIPEND:
        fund(w3, admin, buyer.address, ETH_STIPEND)
    if w3.eth.get_balance(agent.address) < ETH_STIPEND:
        fund(w3, admin, agent.address, ETH_STIPEND)

    send_tx(w3, admin, mock.functions.mint(buyer.address, AMOUNT))
    send_tx(w3, admin, mock.functions.mint(agent.address, AMOUNT))

    buyer_initial = mock.functions.balanceOf(buyer.address).call()
    agent_initial = mock.functions.balanceOf(agent.address).call()
    print(f"buyer    {buyer.address}")
    print(f"agent    {agent.address}")
    print(f"balances buyer={buyer_initial / 1e6} agent={agent_initial / 1e6} mUSDC")

    # -- 4. Core flow via karma_sdk (the part under test) -----------------
    buyer_k = KarmaBilateral(RPC, buyer_key, KARMA, gas=2_000_000)
    agent_k = KarmaBilateral(RPC, agent_key, KARMA, gas=2_000_000)

    print("\n== lock (approve + lock, separate nonces) ==")
    buyer_bill = buyer_k.lock(mock_addr, AMOUNT, approve=True)
    agent_bill = agent_k.lock(mock_addr, AMOUNT, approve=True)
    print(f"  buyer bill {buyer_bill}, agent bill {agent_bill}")
    assert buyer_k.get_bill(buyer_bill).state == "MINTED"
    assert agent_k.get_bill(agent_bill).state == "MINTED"
    assert buyer_k.check_invariant(mock_addr), "invariant broken after lock"

    print("\n== bind (buyer signs) ==")
    scope = Web3.keccak(text="base-sepolia-e2e")
    binding_id = buyer_k.bind(buyer_bill, agent_bill, scope)
    binding = buyer_k.get_binding(binding_id)
    print(f"  binding {binding_id}, state={binding.state}")
    assert binding.state == "ACTIVE"
    assert binding.settle_submitted_at == 0

    countdown(SETTLE_DELAY + 5, "settle delay")

    print("\n== settle -> FINALIZING ==")
    proof = Web3.keccak(text="ipfs://base-sepolia-proof")
    buyer_k.settle(binding_id, proof)
    binding = buyer_k.get_binding(binding_id)
    print(f"  state={binding.state}, settle_submitted_at={binding.settle_submitted_at}")
    assert binding.state == "FINALIZING"
    assert binding.settle_submitted_at > 0

    countdown(FINALIZE_WINDOW + 5, "finalize window")

    print("\n== finalizeSettle -> SETTLED ==")
    buyer_k.finalize_settle(binding_id)
    binding = buyer_k.get_binding(binding_id)
    print(f"  state={binding.state}")
    assert binding.state == "SETTLED"

    # -- 5. Assertions: bills burned, invariant, payouts ------------------
    assert buyer_k.get_bill(buyer_bill).state == "BURNED"
    assert agent_k.get_bill(agent_bill).state == "BURNED"
    assert buyer_k.check_invariant(mock_addr), "invariant broken after settle"

    buyer_final = mock.functions.balanceOf(buyer.address).call()
    agent_final = mock.functions.balanceOf(agent.address).call()
    assert buyer_final == buyer_initial - AMOUNT, f"buyer payout wrong: {buyer_final}"
    assert agent_final == agent_initial + AMOUNT, f"agent payout wrong: {agent_final}"

    print("\n== RESULT ==")
    print(f"  buyer: {buyer_initial / 1e6} -> {buyer_final / 1e6} mUSDC (paid {AMOUNT / 1e6})")
    print(f"  agent: {agent_initial / 1e6} -> {agent_final / 1e6} mUSDC (earned {AMOUNT / 1e6})")
    print(f"  bills: #{buyer_bill} BURNED, #{agent_bill} BURNED")
    print(f"  invariant: {buyer_k.check_invariant(mock_addr)}")
    print(f"  mock token: {mock_addr}")
    print("\nE2E PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
