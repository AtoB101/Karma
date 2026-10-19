#!/usr/bin/env python3
"""P0-3: end-to-end fee bridge settlement on Base Sepolia.

Deploys a fresh KarmaBilateral + MockERC20 + VerifierRegistry + KarmaFeeBridge,
wires a 0.5% fee with the 3/3/2/2 split (treasury / verifier pool / buyback /
developer), runs lock -> bind -> settle -> finalize, and asserts the fee and
its four-way split landed exactly.

Fully isolated: deploys its own KarmaBilateral so shared testnet state is not
disturbed. Windows are set to 0 for a fast single-block settlement.

Env:
  ADMIN_PRIVATE_KEY   Base Sepolia deployer/admin key
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from web3 import Web3
from eth_account import Account

ROOT = Path(__file__).resolve().parents[1]
RPC = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
CHAIN_ID = 84532
ADMIN_KEY = os.getenv("ADMIN_PRIVATE_KEY", "")

AMOUNT = 10_000_000          # 10 mUSDC per side (6 decimals)
ETH_STIPEND = Web3.to_wei(0.002, "ether")
FEE_BPS = 50                 # 0.5%
SPLIT = (3, 3, 2, 2)         # treasury / verifier / buyback / developer out of 10

OUT = ROOT / "karma-core" / "contracts" / "out"
PER_TX_GAS_CAP = 16_777_216  # Base Azul (EIP-7825) per-tx gas ceiling


def load(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def send_tx(w3, acct, fn, gas=3_000_000):
    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "gas": gas,
    })
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
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
        "nonce": w3.eth.get_transaction_count(admin.address, "pending"),
    }
    signed = admin.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(h, timeout=120)


def deploy(w3, acct, artifact, *ctor_args, gas=None):
    c = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    if gas is None:
        gas = c.constructor(*ctor_args).estimate_gas({"from": acct.address})
        gas = min(int(gas * 1.1), PER_TX_GAS_CAP)
    return send_tx(w3, acct, c.constructor(*ctor_args), gas=gas)["contractAddress"]


def poll_until(cond, label, timeout=120, interval=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if cond():
                return
        except Exception:
            pass
        print(f"\r    waiting for {label}...", end="", flush=True)
        time.sleep(interval)
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

    karma_artifact = load(OUT / "KarmaBilateral.sol" / "KarmaBilateral.json")
    mock_artifact = load(OUT / "MockERC20.sol" / "MockERC20.json")
    reg_artifact = load(OUT / "VerifierRegistry.sol" / "VerifierRegistry.json")
    bridge_artifact = load(OUT / "KarmaFeeBridge.sol" / "KarmaFeeBridge.json")

    # 1. fresh stack
    karma_addr = deploy(w3, admin, karma_artifact, admin.address)
    mock_addr = deploy(w3, admin, mock_artifact)
    reg_addr = deploy(w3, admin, reg_artifact, admin.address)
    bridge_addr = deploy(w3, admin, bridge_artifact, admin.address)
    print(f"karma    {karma_addr}")
    print(f"mock     {mock_addr}")
    print(f"registry {reg_addr}")
    print(f"bridge   {bridge_addr}")

    karma = w3.eth.contract(address=Web3.to_checksum_address(karma_addr), abi=karma_artifact["abi"])
    mock = w3.eth.contract(address=Web3.to_checksum_address(mock_addr), abi=mock_artifact["abi"])
    registry = w3.eth.contract(address=Web3.to_checksum_address(reg_addr), abi=reg_artifact["abi"])
    bridge = w3.eth.contract(address=Web3.to_checksum_address(bridge_addr), abi=bridge_artifact["abi"])

    # 2. wire
    treasury, buyback, developer = (Account.create().address for _ in range(3))
    send_tx(w3, admin, karma.functions.setTokenAllowed(mock_addr, True))
    send_tx(w3, admin, karma.functions.setSettleDelay(0))           # no settle delay
    send_tx(w3, admin, karma.functions.setOptimisticDisputeWindow(0)) # no finalize window
    send_tx(w3, admin, bridge.functions.setCore(karma_addr))
    send_tx(w3, admin, bridge.functions.setToken(mock_addr))
    send_tx(w3, admin, bridge.functions.setFeeBps(FEE_BPS))
    send_tx(w3, admin, bridge.functions.setSplit(*SPLIT))
    send_tx(w3, admin, bridge.functions.setDestinations(treasury, reg_addr, buyback, developer))
    send_tx(w3, admin, karma.functions.setFeeBridge(bridge_addr))
    print(f"split    treasury={treasury} verifier={reg_addr} buyback={buyback} developer={developer}")

    # 3. participants
    buyer, agent = Account.create(), Account.create()
    for a in (buyer, agent):
        if w3.eth.get_balance(a.address) < ETH_STIPEND:
            fund(w3, admin, a.address, ETH_STIPEND)
        send_tx(w3, admin, mock.functions.mint(a.address, AMOUNT))
        send_tx(w3, a, mock.functions.approve(karma_addr, AMOUNT))
    print(f"buyer    {buyer.address}")
    print(f"agent    {agent.address}")

    # 4. lock + bind
    def _lock(acct):
        receipt = send_tx(w3, acct, karma.functions.lock(mock_addr, AMOUNT))
        return int(karma.events.BillMinted().process_receipt(receipt)[0]["args"]["billId"])

    buyer_bill = _lock(buyer)
    agent_bill = _lock(agent)
    bind_receipt = send_tx(w3, buyer, karma.functions.bind(buyer_bill, agent_bill, Web3.keccak(text="scope")))
    binding_id = int(karma.events.BillsBound().process_receipt(bind_receipt)[0]["args"]["bindingId"])
    print(f"binding  {binding_id}, state={karma.functions.getBinding(binding_id).call()[4]}")

    # 5. settle + finalize
    send_tx(w3, buyer, karma.functions.settle(binding_id, Web3.keccak(text="proof")))
    poll_until(lambda: karma.functions.getBinding(binding_id).call()[4] == 2, "FINALIZING")
    send_tx(w3, admin, karma.functions.finalizeSettle(binding_id))
    poll_until(lambda: karma.functions.getBinding(binding_id).call()[4] == 3, "SETTLED")
    print("final    state=3 (SETTLED)")

    # 6. verify fee + split
    total = 2 * AMOUNT
    fee = (total * FEE_BPS) // 10_000
    t_amt = (fee * SPLIT[0]) // 10
    v_amt = (fee * SPLIT[1]) // 10
    b_amt = (fee * SPLIT[2]) // 10
    d_amt = fee - t_amt - v_amt - b_amt

    print(f"fee      {fee / 1e6:.6f} mUSDC of GMV {total / 1e6:.6f}")
    poll_until(lambda: bridge.functions.totalFeesCollected().call() == fee, "totalFeesCollected")
    poll_until(lambda: bridge.functions.totalGmvRecorded().call() == total, "totalGmvRecorded")
    poll_until(lambda: mock.functions.balanceOf(treasury).call() == t_amt, "treasury split")
    poll_until(lambda: mock.functions.balanceOf(reg_addr).call() == v_amt, "verifier split")
    poll_until(lambda: mock.functions.balanceOf(buyback).call() == b_amt, "buyback split")
    poll_until(lambda: mock.functions.balanceOf(developer).call() == d_amt, "developer split")
    print(f"split    treasury={t_amt / 1e6:.6f} verifier={v_amt / 1e6:.6f} buyback={b_amt / 1e6:.6f} developer={d_amt / 1e6:.6f}")

    poll_until(lambda: mock.functions.balanceOf(buyer.address).call() == 0, "buyer balance 0")
    poll_until(lambda: mock.functions.balanceOf(agent.address).call() == total - fee, "agent payout")
    poll_until(lambda: karma.functions.checkInvariant(mock_addr).call() is True, "checkInvariant")

    print("\nP0-3 FEE BRIDGE E2E PASSED")
    print(f"  karma={karma_addr}")
    print(f"  bridge={bridge_addr}")
    print(f"  registry={reg_addr}")
    print(f"  mock={mock_addr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
