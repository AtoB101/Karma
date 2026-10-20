#!/usr/bin/env python3
"""KarmaBilateral Base Sepolia dispute + refund E2E (against the deployed stack).

Two independent on-chain flows, both through the already-deployed contracts:

  A) Dispute:  lock -> bind -> settle -> dispute (DISPUTED) -> agent evidence
               -> 100% resolve rejected (SplitOutsideRange) -> 50/50 bounded
               resolveDispute via AdminTimelock -> SETTLED.
  B) Refund:   lock -> bind -> wait settleTimeout -> refundOnTimeout -> REFUNDED.

Because the redeployed stack's admin is the AdminTimelock, every admin-only
call (allowlist, window config, resolveDispute) goes through schedule+execute.

Env:
  ADMIN_PRIVATE_KEY   required: Base Sepolia deployer/admin key (timelock owner)
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

_NONCES: dict = {}


def _nonce(w3, acct):
    key = acct.address.lower()
    n = _NONCES.get(key)
    if n is None:
        n = w3.eth.get_transaction_count(acct.address, "pending")
    _NONCES[key] = n + 1
    return n
from karma_sdk import KarmaBilateral

RPC = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
CHAIN_ID = 84532
KARMA = "0x8718AD6B0c62687a591F41A8d4a5f72d20f4a611"
TIMELOCK = "0xD2e0f34bE2302DF8CE6F282229dba903e1A96DDB"
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
ADMIN_KEY = os.getenv("ADMIN_PRIVATE_KEY", "")

SETTLE_DELAY = 60       # bind -> settle
DISPUTE_WINDOW = 120    # settle -> dispute deadline
EVIDENCE_WINDOW = 60    # dispute -> resolveDispute deadline
SETTLE_TIMEOUT = 60     # bind -> refundOnTimeout deadline
AMOUNT = 10_000_000     # 10 mUSDC (6 decimals)
ETH_STIPEND = Web3.to_wei(0.0005, "ether")

MOCK_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "MockERC20.sol" / "MockERC20.json"
KARMA_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "KarmaBilateral.sol" / "KarmaBilateral.json"
TIMELOCK_ARTIFACT = ROOT / "karma-core" / "contracts" / "out" / "AdminTimelock.sol" / "AdminTimelock.json"


def load_artifact(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def send_tx(w3: Web3, acct, fn, gas: int = 2_000_000):
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


def fund(w3: Web3, admin, to_address: str, value: int):
    tx = {
        "from": admin.address,
        "to": Web3.to_checksum_address(to_address),
        "value": value,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
        "nonce": _nonce(w3, admin),
    }
    signed = admin.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)


def tl_call(w3: Web3, admin, timelock, target: str, data: bytes, gas: int = 3_000_000):
    """Route an admin-only call through the AdminTimelock (schedule + execute)."""
    tx = timelock.functions.schedule(target, 0, data).build_transaction({
        "from": admin.address,
        "nonce": _nonce(w3, admin),
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
        "nonce": _nonce(w3, admin),
        "gas": gas,
    })
    signed = admin.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f"timelock execute reverted: {tx_hash.hex()}")
    return receipt


def poll_until(cond, label: str, timeout: int = 60, interval: int = 5) -> bool:
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
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        binding = client.get_binding(binding_id)
        last = binding
        print(f"\r    getBinding -> state={binding.state}", end="", flush=True)
        if predicate(binding):
            print("")
            return binding
        time.sleep(interval)
    print("")
    raise TimeoutError(
        f"binding {binding_id} did not reach {label}: last state={last.state if last else '?'}"
    )


def countdown(seconds: int, label: str):
    print(f"\n  waiting {seconds}s for {label}...", flush=True)
    while seconds > 0:
        print(f"\r  {seconds:>3}s remaining", end="", flush=True)
        step = min(15, seconds)
        time.sleep(step)
        seconds -= step
    print("")


def new_party(w3, admin, mock, mock_addr, amount):
    key = Account.create().key.hex()
    acct = Account.from_key(key)
    if w3.eth.get_balance(acct.address) < ETH_STIPEND:
        fund(w3, admin, acct.address, ETH_STIPEND)
    send_tx(w3, admin, mock.functions.mint(acct.address, amount))
    return acct


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

    karma = w3.eth.contract(address=Web3.to_checksum_address(KARMA), abi=load_artifact(KARMA_ARTIFACT)["abi"])
    timelock = w3.eth.contract(address=Web3.to_checksum_address(TIMELOCK), abi=load_artifact(TIMELOCK_ARTIFACT)["abi"])

    # -- Mock token + windows -----------------------------------------------
    mock_artifact = load_artifact(MOCK_ARTIFACT)
    Mock = w3.eth.contract(abi=mock_artifact["abi"], bytecode=mock_artifact["bytecode"]["object"])
    receipt = send_tx(w3, admin, Mock.constructor(), gas=2_000_000)
    mock_addr = receipt["contractAddress"]
    mock = w3.eth.contract(address=mock_addr, abi=mock_artifact["abi"])
    print(f"mock     {mock_addr}")

    tl_call(w3, admin, timelock, KARMA, karma.functions.setTokenAllowed(mock_addr, True)._encode_transaction_data())
    tl_call(w3, admin, timelock, KARMA, karma.functions.setSettleDelay(SETTLE_DELAY)._encode_transaction_data())
    tl_call(w3, admin, timelock, KARMA, karma.functions.setOptimisticDisputeWindow(DISPUTE_WINDOW)._encode_transaction_data())
    tl_call(w3, admin, timelock, KARMA, karma.functions.setEvidenceWindow(EVIDENCE_WINDOW)._encode_transaction_data())
    tl_call(w3, admin, timelock, KARMA, karma.functions.setSettleTimeout(SETTLE_TIMEOUT)._encode_transaction_data())
    print(f"windows  settle_delay={SETTLE_DELAY}s dispute={DISPUTE_WINDOW}s evidence={EVIDENCE_WINDOW}s refund_timeout={SETTLE_TIMEOUT}s")

    # ======================================================================
    #  Flow A: dispute -> resolveDispute (buyer wins 100%)
    # ======================================================================
    print("\n================= FLOW A: DISPUTE =================")
    buyer = new_party(w3, admin, mock, mock_addr, AMOUNT)
    agent = new_party(w3, admin, mock, mock_addr, AMOUNT)
    buyer_k = KarmaBilateral(RPC, buyer.key.hex(), KARMA, gas=2_000_000)
    agent_k = KarmaBilateral(RPC, agent.key.hex(), KARMA, gas=2_000_000)

    buyer_bill = buyer_k.lock(mock_addr, AMOUNT, approve=True)
    agent_bill = agent_k.lock(mock_addr, AMOUNT, approve=True)
    print(f"locked buyer bill {buyer_bill}, agent bill {agent_bill}")
    assert poll_until(lambda: buyer_k.get_bill(buyer_bill).state == "MINTED", "buyer bill MINTED")
    assert poll_until(lambda: agent_k.get_bill(agent_bill).state == "MINTED", "agent bill MINTED")

    scope = Web3.keccak(text="base-sepolia-dispute-e2e")
    binding_id = buyer_k.bind(buyer_bill, agent_bill, scope)
    binding = wait_for_binding(buyer_k, binding_id, lambda b: b.state == "ACTIVE", "ACTIVE")
    print(f"binding {binding_id}, state={binding.state}")

    countdown(SETTLE_DELAY + 5, "settle delay")
    buyer_k.settle(binding_id, Web3.keccak(text="ipfs://settle-proof"))
    binding = wait_for_binding(buyer_k, binding_id, lambda b: b.state == "FINALIZING", "FINALIZING")
    print(f"settled -> state={binding.state}")

    # Buyer disputes immediately (inside the 120s dispute window).
    buyer_k.dispute(binding_id, Web3.keccak(text="ipfs://buyer-evidence"))
    binding = wait_for_binding(buyer_k, binding_id, lambda b: b.state == "DISPUTED", "DISPUTED")
    print(f"disputed -> state={binding.state}")

    # finalizeSettle must be frozen while DISPUTED.
    try:
        buyer_k.finalize_settle(binding_id)
        print("  ERROR: finalizeSettle succeeded during DISPUTED")
        return 1
    except Exception as exc:
        print(f"  finalizeSettle during DISPUTED correctly rejected ({type(exc).__name__})")

    # Agent submits counter-evidence within the evidence window.
    agent_k.submit_arbitration_evidence(binding_id, Web3.keccak(text="ipfs://agent-counter-evidence"))
    binding = wait_for_binding(agent_k, binding_id, lambda b: b.state == "DISPUTED", "DISPUTED")
    print(f"agent evidence submitted -> state={binding.state}")

    # Wait for the evidence window, then admin resolves via timelock.
    countdown(EVIDENCE_WINDOW + 5, "evidence window")

    # P1-5 SECURITY: with evidence from both sides, a 100% buyer award is
    # forbidden (SplitOutsideRange) so governance cannot unilaterally wipe out
    # a party. Verify the constraint is enforced on-chain.
    try:
        tl_call(w3, admin, timelock, KARMA, karma.functions.resolveDispute(binding_id, 10_000)._encode_transaction_data())
        print("  ERROR: 100% resolve was not rejected")
        return 1
    except RuntimeError:
        print("  100% resolve correctly rejected (SplitOutsideRange)")

    # A bounded 50/50 split is valid and settles.
    tl_call(w3, admin, timelock, KARMA, karma.functions.resolveDispute(binding_id, 5_000)._encode_transaction_data())
    binding = wait_for_binding(buyer_k, binding_id, lambda b: b.state == "SETTLED", "SETTLED")
    print(f"resolved -> state={binding.state}")
    assert binding.state == "SETTLED"
    assert poll_until(lambda: buyer_k.get_bill(buyer_bill).state == "BURNED", "buyer bill BURNED")
    assert poll_until(lambda: agent_k.get_bill(agent_bill).state == "BURNED", "agent bill BURNED")
    assert poll_until(lambda: mock.functions.balanceOf(buyer.address).call() == AMOUNT, "buyer 50% back")
    assert poll_until(lambda: mock.functions.balanceOf(agent.address).call() == AMOUNT, "agent 50% back")
    assert poll_until(lambda: buyer_k.check_invariant(mock_addr), "invariant after dispute")
    print(f"FLOW A PASSED: 100% rejected, 50/50 resolves; buyer {AMOUNT/1e6}, agent {AMOUNT/1e6}, invariant=True")

    # ======================================================================
    #  Flow B: refundOnTimeout
    # ======================================================================
    print("\n================= FLOW B: REFUND =================")
    buyer2 = new_party(w3, admin, mock, mock_addr, AMOUNT)
    agent2 = new_party(w3, admin, mock, mock_addr, AMOUNT)
    buyer2_k = KarmaBilateral(RPC, buyer2.key.hex(), KARMA, gas=2_000_000)
    agent2_k = KarmaBilateral(RPC, agent2.key.hex(), KARMA, gas=2_000_000)

    b2_bill = buyer2_k.lock(mock_addr, AMOUNT, approve=True)
    a2_bill = agent2_k.lock(mock_addr, AMOUNT, approve=True)
    scope2 = Web3.keccak(text="base-sepolia-refund-e2e")
    binding2_id = buyer2_k.bind(b2_bill, a2_bill, scope2)
    binding2 = wait_for_binding(buyer2_k, binding2_id, lambda b: b.state == "ACTIVE", "ACTIVE")
    print(f"binding {binding2_id}, state={binding2.state}")

    countdown(SETTLE_TIMEOUT + 5, "settle timeout")
    buyer2_k.refund_on_timeout(binding2_id)
    binding2 = wait_for_binding(buyer2_k, binding2_id, lambda b: b.state == "REFUNDED", "REFUNDED")
    print(f"refunded -> state={binding2.state}")
    assert binding2.state == "REFUNDED"
    assert poll_until(lambda: buyer2_k.get_bill(b2_bill).state == "BURNED", "refund buyer bill BURNED")
    assert poll_until(lambda: agent2_k.get_bill(a2_bill).state == "BURNED", "refund agent bill BURNED")
    assert poll_until(lambda: mock.functions.balanceOf(buyer2.address).call() == AMOUNT, "buyer refunded")
    assert poll_until(lambda: mock.functions.balanceOf(agent2.address).call() == AMOUNT, "agent refunded")
    assert poll_until(lambda: buyer2_k.check_invariant(mock_addr), "invariant after refund")
    print(f"FLOW B PASSED: buyer {AMOUNT/1e6}, agent {AMOUNT/1e6}, invariant=True")

    print("\nDISPUTE + REFUND E2E PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
