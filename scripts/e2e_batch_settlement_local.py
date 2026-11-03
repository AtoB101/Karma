"""Local end-to-end test for SettlementBatch + KarmaBilateral.settleOperator.

Deploys MockERC20 + KarmaBilateral + SettlementBatch on a local anvil, then:
  N x (buyer.lock -> agent.lock -> bind) -> batchSettle -> batchFinalize
and asserts every binding settles and USDC actually moves.

Run with anvil on :8545 (chain id 31337).
"""
import json
import os
import sys

from web3 import Web3
from eth_account import Account

RPC = os.environ.get("RPC", "http://localhost:8545")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "karma-core", "contracts", "out")

KEYS = {
    "admin": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    "buyer": "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "agent": "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    "operator": "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
}

w3 = Web3(Web3.HTTPProvider(RPC))
assert w3.is_connected(), "anvil not reachable"
acct = {k: Account.from_key(v) for k, v in KEYS.items()}
addr = {k: a.address for k, a in acct.items()}


def load_artifact(name: str):
    p = os.path.join(CONTRACTS, f"{name}.sol", f"{name}.json")
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


def event_arg(receipt, contract, event_name: str, arg: str):
    return contract.events[event_name]().process_receipt(receipt)[0]["args"][arg]


def main():
    mock_abi, mock_bc = load_artifact("MockERC20")
    kb_abi, kb_bc = load_artifact("KarmaBilateral")
    batch_abi, batch_bc = load_artifact("SettlementBatch")

    token = deploy(mock_abi, mock_bc, [], "admin")
    kb = deploy(kb_abi, kb_bc, [addr["admin"]], "admin")
    batch = deploy(batch_abi, batch_bc, [addr["admin"], kb.address], "admin")

    tx("admin", kb.functions.setTokenAllowed(token.address, True))
    tx("admin", kb.functions.setSettleOperator(batch.address))
    tx("admin", batch.functions.setOperator(addr["operator"]))

    UNIT = 10**6
    AMOUNT = 100 * UNIT       # buyer locks full order
    PENALTY = 10 * UNIT       # seller locks penalty only

    tx("admin", token.functions.mint(addr["buyer"], 20 * AMOUNT))
    tx("admin", token.functions.mint(addr["agent"], 20 * AMOUNT))
    tx("buyer", token.functions.approve(kb.address, 20 * AMOUNT))
    tx("agent", token.functions.approve(kb.address, 20 * AMOUNT))

    b_before = token.functions.balanceOf(addr["buyer"]).call()
    a_before = token.functions.balanceOf(addr["agent"]).call()

    bindings = []
    N = 3
    scope = Web3.keccak(text="karma-batch-scope")
    proof = Web3.keccak(text="delivery-proof")
    for _ in range(N):
        r = tx("buyer", kb.functions.lock(token.address, AMOUNT))
        buyer_bill = event_arg(r, kb, "BillMinted", "billId")
        r = tx("agent", kb.functions.lock(token.address, PENALTY))
        agent_bill = event_arg(r, kb, "BillMinted", "billId")
        r = tx("buyer", kb.functions.bind(buyer_bill, agent_bill, scope))
        bindings.append(event_arg(r, kb, "BillsBound", "bindingId"))

    warp(1800)  # settle delay

    # operator submits one batch tx (single nonce) for all N bindings
    items = [(binding_id, proof) for binding_id in bindings]
    r = tx("operator", batch.functions.batchSettle(items))

    for binding_id in bindings:
        b = kb.functions.getBinding(binding_id).call()
        assert b[4] == 2, f"binding {binding_id} should be FINALIZING, state={b[4]}"

    warp(86400)  # optimistic dispute window

    r = tx("operator", batch.functions.batchFinalize(bindings))

    for binding_id in bindings:
        b = kb.functions.getBinding(binding_id).call()
        assert b[4] == 3, f"binding {binding_id} should be SETTLED, state={b[4]}"

    b_after = token.functions.balanceOf(addr["buyer"]).call()
    a_after = token.functions.balanceOf(addr["agent"]).call()
    escrow = token.functions.balanceOf(kb.address).call()
    supply = kb.functions.totalBillSupply(token.address).call()
    locked = kb.functions.totalLocked(token.address).call()

    assert escrow == 0, f"escrow should drain to 0, has {escrow}"
    assert b_after == b_before - N * AMOUNT, f"buyer delta wrong: {b_after - b_before}"
    assert a_after == a_before + N * AMOUNT, f"agent delta wrong: {a_after - a_before}"
    assert supply == 0 and locked == 0, f"invariant broken: supply={supply} locked={locked}"

    print("=" * 60)
    print("  E2E BATCH SETTLEMENT LOOP: PASS")
    print("=" * 60)
    print(f"  token    : {token.address}")
    print(f"  bilateral: {kb.address}")
    print(f"  batch    : {batch.address}")
    print(f"  operator : {addr['operator']}")
    print(f"  bindings : {bindings}")
    print(f"  settled  : {N}/{N} (single batchSettle + batchFinalize tx)")
    print(f"  buyer  {(b_after - b_before) / UNIT:+.2f} mUSDC")
    print(f"  agent  {(a_after - a_before) / UNIT:+.2f} mUSDC")
    print(f"  supply={supply} locked={locked} (invariant holds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
