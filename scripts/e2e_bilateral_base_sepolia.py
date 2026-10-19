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

Note on reads: the public Base Sepolia RPC is eventually consistent, so an
eth_call right after a transaction can hit a lagging node and return stale
state. Every post-transaction read below therefore polls with retries.

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

KARMA = "0xF7839e77960f04B68D0Ea635DB3a21738489A6BF"
TIMELOCK = "0x94bd215e391ef625448EC9f14ef50D4fA34D653A"
FEE_BRIDGE = "0x5352efdfFf7B371E2E5EF82F6Df5C8D95ae3cae8"
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
FEE_BPS = 50
ADMIN_KEY = os.getenv("ADMIN_PRIVATE_KEY", "")

SETTLE_DELAY = 60       # seconds after bind before settle()
FINALIZE_WINDOW = 120   # seconds after settle() before finalizeSettle()
AMOUNT = 10_000_000     # 10 mUSDC (6 decimals)
ETH_STIPEND = Web3.to_wei(0.005, "ether")

MOCK_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "MockERC20.sol" / "MockERC20.json"
KARMA_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "KarmaBilateral.sol" / "KarmaBilateral.json"
TIMELOCK_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "AdminTimelock.sol" / "AdminTimelock.json"
FEE_BRIDGE_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "KarmaFeeBridge.sol" / "KarmaFeeBridge.json"


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

def tl_call(w3: Web3, admin, timelock, target: str, data: bytes, gas: int = 3_000_000):
    """Route an admin-only call through the AdminTimelock (schedule + execute)."""
    tx = timelock.functions.schedule(target, 0, data).build_transaction({
        "from": admin.address,
        "nonce": w3.eth.get_transaction_count(admin.address, "pending"),
        "gas": gas,
    })
    signed = admin.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f"timelock schedule reverted: {tx_hash.hex()}")
    action_id = timelock.events.Scheduled().process_receipt(receipt)[0]["args"]["id"]
    tx = timelock.functions.execute(action_id).build_transaction({
        "from": admin.address,
        "nonce": w3.eth.get_transaction_count(admin.address, "pending"),
        "gas": gas,
    })
    signed = admin.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f"timelock execute reverted: {tx_hash.hex()}")
    return receipt


def fund(w3: Web3, admin, to_address: str, value: int):
    tx = {
        "from": admin.address,
        "to": Web3.to_checksum_address(to_address),
        "value": value,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(admin.address, "pending"),
    }
    signed = admin.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)


def latest_ts(w3: Web3) -> int:
    return w3.eth.get_block("latest")["timestamp"]


def poll_until(cond, label: str, timeout: int = 60, interval: int = 5) -> bool:
    """Retry a read until cond() is truthy (handles RPC eventual consistency)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        print(f"\r    waiting for {label}...", end="", flush=True)
        time.sleep(interval)
    print("")
    return cond()


def wait_for_binding(client: KarmaBilateral, binding_id: int, predicate, label: str,
                     timeout: int = 60, interval: int = 5):
    """Poll getBinding until `predicate(binding)` holds (handles RPC lag)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        binding = client.get_binding(binding_id)
        last = binding
        print(f"\r    getBinding -> state={binding.state} "
              f"settleSubmittedAt={binding.settle_submitted_at}",
              end="", flush=True)
        if predicate(binding):
            print("")
            return binding
        time.sleep(interval)
    print("")
    raise TimeoutError(
        f"binding {binding_id} did not reach {label}: "
        f"last state={last.state if last else '?'}"
    )


def wait_for_finalize_target(client: KarmaBilateral, binding_id: int,
                             timeout: int = 60, interval: int = 5) -> int:
    """Poll finalizeAfter until it returns a non-zero timestamp."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        target = client.finalize_after(binding_id)
        if target and target > 0:
            return target
        time.sleep(interval)
    raise TimeoutError(f"finalizeAfter stayed 0 for binding {binding_id}")


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

    timelock_abi = load_artifact(TIMELOCK_ARTIFACT)["abi"]
    timelock = w3.eth.contract(address=Web3.to_checksum_address(TIMELOCK), abi=timelock_abi)

    fee_bridge_abi = load_artifact(FEE_BRIDGE_ARTIFACT)["abi"]
    fee_bridge = w3.eth.contract(address=Web3.to_checksum_address(FEE_BRIDGE), abi=fee_bridge_abi)

    # -- 1. Deploy MockERC20 (open mint; avoids the Base USDC faucet) ------
    mock_artifact = load_artifact(MOCK_ARTIFACT)
    Mock = w3.eth.contract(abi=mock_artifact["abi"], bytecode=mock_artifact["bytecode"]["object"])
    receipt = send_tx(w3, admin, Mock.constructor(), gas=2_000_000)
    mock_addr = receipt["contractAddress"]
    mock = w3.eth.contract(address=mock_addr, abi=mock_artifact["abi"])
    print(f"mock     {mock_addr}")

    # -- 2. Admin: allowlist token + shorten windows for the test ---------
    tl_call(w3, admin, timelock, KARMA, karma.functions.setTokenAllowed(mock_addr, True)._encode_transaction_data())
    tl_call(w3, admin, timelock, KARMA, karma.functions.setDisputeWindow(SETTLE_DELAY)._encode_transaction_data())
    tl_call(w3, admin, timelock, KARMA, karma.functions.setOptimisticDisputeWindow(FINALIZE_WINDOW)._encode_transaction_data())
    print(f"windows  settle_delay={SETTLE_DELAY}s finalize={FINALIZE_WINDOW}s")

    # Settle charges a 0.5% fee via the fee bridge; point its settlement token
    # at the mock for this run and restore USDC before exiting.
    tl_call(w3, admin, timelock, FEE_BRIDGE, fee_bridge.functions.setToken(mock_addr)._encode_transaction_data())
    fee = (2 * AMOUNT * FEE_BPS) // 10_000

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
    assert poll_until(lambda: buyer_k.get_bill(buyer_bill).state == "MINTED",
                      "buyer bill MINTED")
    assert poll_until(lambda: agent_k.get_bill(agent_bill).state == "MINTED",
                      "agent bill MINTED")
    assert poll_until(lambda: buyer_k.check_invariant(mock_addr), "invariant after lock")

    print("\n== bind (buyer signs) ==")
    scope = Web3.keccak(text="base-sepolia-e2e")
    binding_id = buyer_k.bind(buyer_bill, agent_bill, scope)
    binding = wait_for_binding(buyer_k, binding_id, lambda b: b.state == "ACTIVE",
                               label="ACTIVE")
    print(f"  binding {binding_id}, state={binding.state}")
    assert binding.state == "ACTIVE"
    assert binding.settle_submitted_at == 0

    countdown(SETTLE_DELAY + 5, "settle delay")

    print("\n== settle -> FINALIZING ==")
    proof = Web3.keccak(text="ipfs://base-sepolia-proof")
    settle_receipt = buyer_k.settle(binding_id, proof)
    print(f"  settle tx={settle_receipt.transactionHash.hex()} "
          f"status={settle_receipt.status}")
    binding = wait_for_binding(buyer_k, binding_id, lambda b: b.state == "FINALIZING",
                               label="FINALIZING")
    print(f"  state={binding.state}, settle_submitted_at={binding.settle_submitted_at}")
    assert binding.state == "FINALIZING"
    assert binding.settle_submitted_at > 0

    countdown(FINALIZE_WINDOW + 5, "finalize window")

    print("\n== finalizeSettle -> SETTLED ==")
    target = wait_for_finalize_target(buyer_k, binding_id)
    print(f"  finalize_after={target}, latest_block_ts={latest_ts(w3)}")
    # Absorb small block-timestamp skew between RPC nodes.
    while latest_ts(w3) < target:
        print(f"\r  waiting: block ts {latest_ts(w3)} < {target}", end="", flush=True)
        time.sleep(10)
    print("")
    binding = wait_for_binding(buyer_k, binding_id, lambda b: b.state == "FINALIZING",
                               label="FINALIZING (pre-finalize)")
    fees_before = fee_bridge.functions.totalFeesCollected().call()
    gmv_before = fee_bridge.functions.totalGmvRecorded().call()
    finalize_receipt = buyer_k.finalize_settle(binding_id)
    print(f"  finalize tx={finalize_receipt.transactionHash.hex()} "
          f"status={finalize_receipt.status}")
    binding = wait_for_binding(buyer_k, binding_id, lambda b: b.state == "SETTLED",
                               label="SETTLED")
    print(f"  state={binding.state}")
    assert binding.state == "SETTLED"

    # -- 5. Assertions: bills burned, invariant, payouts ------------------
    assert poll_until(lambda: buyer_k.get_bill(buyer_bill).state == "BURNED",
                      "buyer bill BURNED")
    assert poll_until(lambda: agent_k.get_bill(agent_bill).state == "BURNED",
                      "agent bill BURNED")
    assert poll_until(lambda: buyer_k.check_invariant(mock_addr), "invariant after settle")
    assert poll_until(lambda: mock.functions.balanceOf(buyer.address).call() == buyer_initial - AMOUNT,
                      "buyer payout")
    assert poll_until(lambda: mock.functions.balanceOf(agent.address).call() == agent_initial + AMOUNT - fee,
                      "agent payout")
    assert poll_until(lambda: fee_bridge.functions.totalFeesCollected().call() == fees_before + fee,
                      "fee bridge collected fee")
    assert poll_until(lambda: fee_bridge.functions.totalGmvRecorded().call() == gmv_before + 2 * AMOUNT,
                      "fee bridge recorded GMV")

    buyer_final = mock.functions.balanceOf(buyer.address).call()
    agent_final = mock.functions.balanceOf(agent.address).call()

    # Restore the fee bridge settlement token to USDC.
    tl_call(w3, admin, timelock, FEE_BRIDGE, fee_bridge.functions.setToken(USDC)._encode_transaction_data())

    print("\n== RESULT ==")
    print(f"  buyer: {buyer_initial / 1e6} -> {buyer_final / 1e6} mUSDC (paid {AMOUNT / 1e6})")
    print(f"  agent: {agent_initial / 1e6} -> {agent_final / 1e6} mUSDC (earned {(AMOUNT - fee) / 1e6})")
    print(f"  fee: {fee / 1e6} mUSDC (0.5% of {2 * AMOUNT / 1e6} mUSDC pool)")
    print(f"  bills: #{buyer_bill} BURNED, #{agent_bill} BURNED")
    print(f"  invariant: {buyer_k.check_invariant(mock_addr)}")
    print(f"  mock token: {mock_addr}")
    print("\nE2E PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
