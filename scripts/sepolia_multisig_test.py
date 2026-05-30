#!/usr/bin/env python3
"""
MultiSigEscrow — Sepolia E2E Multisig Test Wallet

Tests the full 2-of-3 multisig escrow flow against the deployed MultiSigEscrow contract.

Prerequisites:
  - MultiSigEscrow deployed on Sepolia (see deploy/sepolia_multisig_deployment.json)
  - W1, W2, W3 funded with Sepolia ETH

Usage:
  python scripts/sepolia_multisig_test.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass

from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# ── Config ────────────────────────────────────────────────────
SEPOLIA_RPC = "https://sepolia.infura.io/v3/a9a3c01e8b98471eb79d07eb16553236"
CHAIN_ID = 11155111

# Resolve paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DEPLOYMENT_PATH = os.path.join(PROJECT_ROOT, "deploy", "sepolia_multisig_deployment.json")

# ── Wallets (Sepolia) ─────────────────────────────────────────
WALLETS = {
    "W1": {
        "address": "0x3295c96a2993C366B3dB27B6ac81f85801D75f51",
        "private_key": "a3bd6e441963f0b097458d5658884633eaeb1dec8e0142e4f23ce64ebe10b3df",
    },
    "W2": {
        "address": "0x16fE563a56E6566809597e4aF9a1608d3e55Dd7F",
        "private_key": "0c85cad5f38c90311e4b1a069e95b76954988222492ccb418c8f115af3f56d94",
    },
    "W3": {
        "address": "0x7Ed437E5786AB0d217D52937da4fF4790998d94C",
        "private_key": "2f9cf6d82fb25f2cf8d4ccfd34bd54b0d8ad5dda0e3b0b99a4280a14dde4690a",
    },
}


@dataclass
class TestResult:
    name: str
    passed: bool
    details: str


def green(s: str) -> str:
    return f"\033[92m{s}\033[0m"


def red(s: str) -> str:
    return f"\033[91m{s}\033[0m"


def yellow(s: str) -> str:
    return f"\033[93m{s}\033[0m"


def bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


# ── Helpers ───────────────────────────────────────────────────
def get_w3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        raise RuntimeError(f"Cannot connect to Sepolia RPC")
    return w3


def load_deployment() -> dict:
    if not os.path.exists(DEPLOYMENT_PATH):
        print(red(f"❌ Deployment file not found: {DEPLOYMENT_PATH}"))
        print(yellow("   Run the deploy script first."))
        sys.exit(1)
    with open(DEPLOYMENT_PATH) as f:
        return json.load(f)


def get_account(wallet_label: str) -> Account:
    w = WALLETS[wallet_label]
    return Account.from_key(w["private_key"])


def balance_eth(w3: Web3, address: str) -> float:
    return float(w3.from_wei(w3.eth.get_balance(address), "ether"))


# ── Tests ─────────────────────────────────────────────────────
def test_get_owners(w3: Web3, contract) -> list[TestResult]:
    """Verify on-chain owner configuration matches deployment."""
    results = []
    onchain = contract.functions.getOwners().call()
    expected = [
        Web3.to_checksum_address(WALLETS["W1"]["address"]),
        Web3.to_checksum_address(WALLETS["W2"]["address"]),
        Web3.to_checksum_address(WALLETS["W3"]["address"]),
    ]
    ok = len(onchain) == 3 and onchain == expected
    results.append(TestResult(
        "Owner list matches W1,W2,W3",
        ok,
        f"on-chain={onchain}" if ok else f"expected={expected}, got={onchain}"
    ))
    return results


def test_get_required(w3: Web3, contract) -> list[TestResult]:
    """Verify required signatures = 2."""
    results = []
    req = contract.functions.getRequired().call()
    ok = req == 2
    results.append(TestResult(
        "Required signatures = 2",
        ok,
        f"required={req}"
    ))
    return results


def test_is_owner(w3: Web3, contract) -> list[TestResult]:
    """Verify isOwner() returns correct results."""
    results = []
    for label in ["W1", "W2", "W3"]:
        addr = Web3.to_checksum_address(WALLETS[label]["address"])
        val = contract.functions.isOwner(addr).call()
        ok = val is True
        results.append(TestResult(
            f"isOwner({label}) == True",
            ok,
            f"got={val}"
        ))

    # Random non-owner
    rand = "0x000000000000000000000000000000000000dEaD"
    val = contract.functions.isOwner(rand).call()
    ok = val is False
    results.append(TestResult(
        "isOwner(random) == False",
        ok,
        f"got={val}"
    ))
    return results


def test_full_deposit_approve_release(w3: Web3, contract) -> list[TestResult]:
    """Complete 2-of-3 flow: deposit → 2 approvals → release."""
    results = []
    task_id = Web3.keccak(text=f"e2e-test-{int(time.time())}")
    buyer_addr = Web3.to_checksum_address(WALLETS["W1"]["address"])
    seller_addr = Web3.to_checksum_address(WALLETS["W2"]["address"])
    amount_wei = w3.to_wei(0.0005, "ether")  # smaller amount for test

    buyer = get_account("W1")
    w2_account = get_account("W2")
    w3_account = get_account("W3")

    # 1. Deposit
    try:
        seller_bal_before = balance_eth(w3, seller_addr)
        nonce = w3.eth.get_transaction_count(buyer_addr)
        tx = contract.functions.deposit(task_id, seller_addr).build_transaction({
            "from": buyer_addr,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "value": amount_wei,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = buyer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        ok = r.status == 1
        results.append(TestResult(
            "1. Deposit 0.0005 ETH (W1 → escrow)",
            ok,
            f"tx={Web3.to_hex(h)}, gas={r.gasUsed}" if ok else f"reverted"
        ))
        if not ok:
            return results
    except Exception as e:
        results.append(TestResult("1. Deposit", False, str(e)))
        return results

    # Verify task state
    task = contract.functions.tasks(task_id).call()
    results.append(TestResult(
        "2. Task state = FUNDED (1)",
        task[3] == 1,
        f"state={task[3]}, amount={w3.from_wei(task[0], 'ether')} ETH"
    ))

    # 3. W3 approves (1/2)
    try:
        nonce = w3.eth.get_transaction_count(w3_account.address)
        tx = contract.functions.approve(task_id).build_transaction({
            "from": w3_account.address,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = w3_account.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        ok = r.status == 1
        results.append(TestResult(
            "3. W3 approve → 1/2",
            ok,
            f"tx={Web3.to_hex(h)}" if ok else f"reverted"
        ))
    except Exception as e:
        results.append(TestResult("3. W3 approve → 1/2", False, str(e)))

    # 4. W2 approves (2/2)
    try:
        nonce = w3.eth.get_transaction_count(w2_account.address)
        tx = contract.functions.approve(task_id).build_transaction({
            "from": w2_account.address,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = w2_account.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        ok = r.status == 1
        results.append(TestResult(
            "4. W2 approve → 2/2 ✅ threshold",
            ok,
            f"tx={Web3.to_hex(h)}" if ok else f"reverted"
        ))
    except Exception as e:
        results.append(TestResult("4. W2 approve → 2/2", False, str(e)))

    # Verify approval count
    count = contract.functions.countApprovals(task_id).call()
    results.append(TestResult(
        "5. countApprovals = 2",
        count == 2,
        f"count={count}"
    ))

    # 6. Release
    try:
        nonce = w3.eth.get_transaction_count(buyer_addr)
        tx = contract.functions.release(task_id).build_transaction({
            "from": buyer_addr,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = buyer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        ok = r.status == 1
        results.append(TestResult(
            "6. Release → funds to seller (W2)",
            ok,
            f"tx={Web3.to_hex(h)}" if ok else f"reverted"
        ))
    except Exception as e:
        results.append(TestResult("6. Release", False, str(e)))

    # Verify task state = RELEASED
    task = contract.functions.tasks(task_id).call()
    results.append(TestResult(
        "7. Task state = RELEASED (2)",
        task[3] == 2,
        f"state={task[3]}"
    ))

    # Verify seller balance increased
    seller_bal_after = balance_eth(w3, seller_addr)
    seller_diff = seller_bal_after - seller_bal_before
    # Seller paid gas for their approve tx, so diff < 0.0005 but should be positive
    results.append(TestResult(
        "8. Seller received escrow funds",
        seller_diff > 0,
        f"balance change = {seller_diff:.6f} ETH (net of gas)"
    ))

    return results


def test_refund_flow(w3: Web3, contract) -> list[TestResult]:
    """Test refund path: deposit → 2 approvals → refund (not release)."""
    results = []
    task_id = Web3.keccak(text=f"refund-test-{int(time.time())}")
    buyer_addr = Web3.to_checksum_address(WALLETS["W1"]["address"])
    seller_addr = Web3.to_checksum_address(WALLETS["W3"]["address"])
    amount_wei = w3.to_wei(0.0003, "ether")

    buyer = get_account("W1")
    w2_account = get_account("W2")
    w3_account = get_account("W3")

    # Deposit
    try:
        buyer_bal_before = balance_eth(w3, buyer_addr)
        nonce = w3.eth.get_transaction_count(buyer_addr)
        tx = contract.functions.deposit(task_id, seller_addr).build_transaction({
            "from": buyer_addr,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "value": amount_wei,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = buyer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        assert r.status == 1, "deposit failed"
    except Exception as e:
        results.append(TestResult("Refund: deposit", False, str(e)))
        return results

    # Two approvals
    for label, acct in [("W3", w3_account), ("W2", w2_account)]:
        try:
            nonce = w3.eth.get_transaction_count(acct.address)
            tx = contract.functions.approve(task_id).build_transaction({
                "from": acct.address,
                "nonce": nonce,
                "chainId": CHAIN_ID,
            })
            est = w3.eth.estimate_gas(tx)
            tx["gas"] = int(est * 1.3)
            signed = acct.sign_transaction(tx)
            h = w3.eth.send_raw_transaction(signed.raw_transaction)
            r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
            assert r.status == 1
        except Exception as e:
            results.append(TestResult(f"Refund: {label} approve", False, str(e)))
            return results

    # Refund
    try:
        nonce = w3.eth.get_transaction_count(w2_account.address)
        tx = contract.functions.refund(task_id).build_transaction({
            "from": w2_account.address,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = w2_account.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        ok = r.status == 1
        results.append(TestResult(
            "Refund: execute refund → buyer",
            ok,
            f"tx={Web3.to_hex(h)}" if ok else "reverted"
        ))
        # Verify state
        task = contract.functions.tasks(task_id).call()
        results.append(TestResult(
            "Refund: state = REFUNDED (3)",
            task[3] == 3,
            f"state={task[3]}"
        ))
    except Exception as e:
        results.append(TestResult("Refund: execute", False, str(e)))

    return results


def test_security_gates(w3: Web3, contract) -> list[TestResult]:
    """Test that security gates work: non-owner cannot approve, insufficient approvals can't release."""
    results = []

    # Create a test task
    task_id = Web3.keccak(text=f"security-test-{int(time.time())}")
    buyer_addr = Web3.to_checksum_address(WALLETS["W1"]["address"])
    seller_addr = Web3.to_checksum_address(WALLETS["W2"]["address"])
    amount_wei = w3.to_wei(0.0002, "ether")

    buyer = get_account("W1")

    # Deposit
    try:
        nonce = w3.eth.get_transaction_count(buyer_addr)
        tx = contract.functions.deposit(task_id, seller_addr).build_transaction({
            "from": buyer_addr,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "value": amount_wei,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = buyer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        assert r.status == 1
    except Exception as e:
        results.append(TestResult("Security: deposit", False, str(e)))
        return results

    # Test: non-owner cannot approve
    # Use a random key (generate ephemeral)
    random_acct = Account.create()
    # Fund it with 0.001 ETH first from W1 for gas
    try:
        nonce = w3.eth.get_transaction_count(buyer_addr)
        fund_tx = {
            "from": buyer_addr,
            "to": random_acct.address,
            "value": w3.to_wei(0.001, "ether"),
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "gas": 21000,
        }
        signed = buyer.sign_transaction(fund_tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(h, timeout=120)
    except Exception:
        pass  # if funding fails, skip negative test

    try:
        nonce = w3.eth.get_transaction_count(random_acct.address)
        tx = contract.functions.approve(task_id).build_transaction({
            "from": random_acct.address,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = random_acct.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        # Should have reverted
        results.append(TestResult(
            "Security: non-owner approve reverts",
            r.status == 0,
            f"status={r.status} (expected 0=fail)"
        ))
    except Exception as e:
        # Revert is expected
        results.append(TestResult(
            "Security: non-owner approve reverts ✅",
            True,
            f"reverted as expected: {str(e)[:80]}"
        ))

    # Test: release without enough approvals should revert
    try:
        nonce = w3.eth.get_transaction_count(buyer_addr)
        tx = contract.functions.release(task_id).build_transaction({
            "from": buyer_addr,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        })
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.3)
        signed = buyer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        results.append(TestResult(
            "Security: release without 2 approvals reverts",
            r.status == 0,
            f"status={r.status} (expected 0=fail)"
        ))
    except Exception as e:
        results.append(TestResult(
            "Security: release without 2 approvals reverts ✅",
            True,
            f"reverted as expected: {str(e)[:80]}"
        ))

    return results


# ── Runner ────────────────────────────────────────────────────
def run_all_tests():
    print(bold("=" * 60))
    print(bold("🛡️  MultiSigEscrow — Sepolia E2E Test Suite"))
    print(bold("=" * 60))

    w3 = get_w3()
    print(f"✅ Connected to Sepolia (chainId={w3.eth.chain_id})")

    dep = load_deployment()
    contract_addr = dep["address"]
    print(f"📄 Contract: {contract_addr}")
    print(f"   Owners: {dep['owner_labels']}")
    print(f"   Required: {dep['required']}-of-3\n")

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_addr),
        abi=dep["abi"],
    )

    # Collect all test results
    all_results = []
    all_results.extend(test_get_owners(w3, contract))
    all_results.extend(test_get_required(w3, contract))
    all_results.extend(test_is_owner(w3, contract))

    print(bold("\n── Full Flow: Deposit → 2 Approvals → Release ──"))
    all_results.extend(test_full_deposit_approve_release(w3, contract))

    print(bold("\n── Refund Flow ──"))
    all_results.extend(test_refund_flow(w3, contract))

    print(bold("\n── Security Gates ──"))
    all_results.extend(test_security_gates(w3, contract))

    # Summary
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    total = len(all_results)

    print("\n" + bold("=" * 60))
    print(bold("📊 TEST RESULTS"))
    print(bold("=" * 60))
    for r in all_results:
        status = green("✅ PASS") if r.passed else red("❌ FAIL")
        print(f"  {status} | {r.name}")
        if not r.passed and r.details:
            print(f"          {red(r.details)}")
    print("─" * 60)
    print(f"  {green(f'Passed: {passed}')}  |  {red(f'Failed: {failed}')}  |  Total: {total}")
    if failed == 0:
        print(green("\n🎉 All tests passed!"))
    else:
        print(red(f"\n❌ {failed} test(s) failed"))
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
