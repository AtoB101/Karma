"""Local end-to-end test for KarmaBilateral bilateral settlement loop.

Deploys MockERC20 + KarmaBilateral on a local anvil, then runs the full loop:
  buyer.lock -> agent.lock -> bind -> settle -> finalizeSettle
and asserts USDC actually moves to each party.

Run with anvil on :8545 (chain id 31337).
"""
import json
import os
import sys

from web3 import Web3
from eth_account import Account

RPC = os.environ.get("RPC", "http://localhost:8545")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# anvil default accounts
KEYS = {
    "admin":  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    "buyer":  "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "agent":  "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
}

w3 = Web3(Web3.HTTPProvider(RPC))
assert w3.is_connected(), "anvil not reachable"

acct = {k: Account.from_key(v) for k, v in KEYS.items()}
addr = {k: a.address for k, a in acct.items()}


def load_artifact(name: str):
    p = os.path.join(ROOT, "out", f"{name}.sol", f"{name}.json")
    with open(p, encoding="utf-8") as f:
        art = json.load(f)
    return art["abi"], art["bytecode"]["object"]


def deploy(abi, bytecode, ctor_args, signer_key):
    c = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = c.constructor(*ctor_args).build_transaction({
        "from": addr[signer_key],
        "nonce": w3.eth.get_transaction_count(addr[signer_key]),
    })
    signed = acct[signer_key].sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h)
    return w3.eth.contract(address=r.contractAddress, abi=abi)


def tx(signer_key, fn):
    t = fn.build_transaction({
        "from": addr[signer_key],
        "nonce": w3.eth.get_transaction_count(addr[signer_key]),
    })
    s = acct[signer_key].sign_transaction(t)
    h = w3.eth.send_raw_transaction(s.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(h)


def warp(seconds: int):
    w3.provider.make_request("evm_increaseTime", [seconds])
    w3.provider.make_request("evm_mine", [])


def main():
    mock_abi, mock_bc = load_artifact("MockERC20")
    kb_abi, kb_bc = load_artifact("KarmaBilateral")

    token = deploy(mock_abi, mock_bc, [], "admin")
    kb = deploy(kb_abi, kb_bc, [addr["admin"]], "admin")

    # allowlist + mint
    tx("admin", kb.functions.setTokenAllowed(token.address, True))
    UNIT = 10**6  # 6 decimals
    AMOUNT = 1000 * UNIT  # 1000 mUSDC each
    tx("admin", token.functions.mint(addr["buyer"], 10 * AMOUNT))
    tx("admin", token.functions.mint(addr["agent"], 10 * AMOUNT))

    PENALTY = AMOUNT // 10  # seller stakes 10% penalty, not the full order
    # approve
    tx("buyer", token.functions.approve(kb.address, AMOUNT))
    tx("agent", token.functions.approve(kb.address, PENALTY))

    b_before = token.functions.balanceOf(addr["buyer"]).call()
    a_before = token.functions.balanceOf(addr["agent"]).call()

    # 1. asymmetric lock: buyer locks full order, seller locks penalty only
    r = tx("buyer", kb.functions.lock(token.address, AMOUNT))
    buyer_bill = _bill_id(r, kb, "BillMinted")
    r = tx("agent", kb.functions.lock(token.address, PENALTY))
    agent_bill = _bill_id(r, kb, "BillMinted")

    # escrow holds buyer's full payment + seller's penalty
    escrow_after_lock = token.functions.balanceOf(kb.address).call()
    assert escrow_after_lock == AMOUNT + PENALTY, f"escrow should hold AMOUNT+PENALTY, has {escrow_after_lock}"

    # 2. bind
    scope = Web3.keccak(text="karma-e2e-scope")
    r = tx("buyer", kb.functions.bind(buyer_bill, agent_bill, scope))
    binding = _binding_id(r, kb, "BillsBound")

    # 3. settle (after settle delay 30m)
    warp(1800)
    proof = Web3.keccak(text="delivery-proof")
    tx("buyer", kb.functions.settle(binding, proof))

    # 4. finalize (after 24h dispute window)
    warp(86400)
    tx("agent", kb.functions.finalizeSettle(binding))

    b_after = token.functions.balanceOf(addr["buyer"]).call()
    a_after = token.functions.balanceOf(addr["agent"]).call()
    escrow_after = token.functions.balanceOf(kb.address).call()

    # no feeBridge => fee 0. Buyer's full amount is the payment to the seller;
    # seller's penalty returns to them. Escrow drained to 0.
    assert escrow_after == 0, f"escrow should be drained, has {escrow_after}"
    assert b_after == b_before - AMOUNT, f"buyer should have paid {AMOUNT}, delta={b_before - b_after}"
    assert a_after == a_before + AMOUNT, f"seller should have received {AMOUNT}, delta={a_after - a_before}"

    # invariant: supply == locked == 0 after both bills burned
    supply = kb.functions.totalBillSupply(token.address).call()
    locked = kb.functions.totalLocked(token.address).call()
    assert supply == 0 and locked == 0, f"invariant broken: supply={supply} locked={locked}"

    print("=" * 60)
    print("  E2E BILATERAL LOOP: PASS")
    print("=" * 60)
    print(f"  token      : {token.address}")
    print(f"  bilateral  : {kb.address}")
    print(f"  buyerBill  : {buyer_bill}")
    print(f"  agentBill  : {agent_bill}")
    print(f"  binding    : {binding}")
    print(f"  buyer  +{(b_after - b_before) / UNIT:.2f} mUSDC")
    print(f"  agent  +{(a_after - a_before) / UNIT:.2f} mUSDC")
    print(f"  supply={supply} locked={locked} (invariant holds)")
    return 0


def _bill_id(receipt, kb, event):
    logs = kb.events[event]().process_receipt(receipt)
    return logs[0]["args"]["billId"]


def _binding_id(receipt, kb, event):
    logs = kb.events[event]().process_receipt(receipt)
    return logs[0]["args"]["bindingId"]


if __name__ == "__main__":
    sys.exit(main())
