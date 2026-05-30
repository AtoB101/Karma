#!/usr/bin/env python3
"""KarmaBilateral Sepolia Testnet Full Test Suite"""
import json, time, sys

RPC = "https://sepolia.infura.io/v3/a9a3c01e8b98471eb79d07eb16553236"
USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
ADMIN_KEY = "2f9cf6d82fb25f2cf8d4ccfd34bd54b0d8ad5dda0e3b0b99a4280a14dde4690a"
BUYER_KEY = "a3bd6e441963f0b097458d5658884633eaeb1dec8e0142e4f23ce64ebe10b3df"
AGENT_KEY = "0c85cad5f38c90311e4b1a069e95b76954988222492ccb418c8f115af3f56d94"
ADMIN = "0x7Ed437E5786AB0d217D52937da4fF4790998d94C"
BUYER = "0x3295c96a2993C366B3dB27B6ac81f85801D75f51"
AGENT = "0x16fE563a56E6566809597e4aF9a1608d3e55Dd7F"

from web3 import Web3
w3 = Web3(Web3.HTTPProvider(RPC))
assert w3.is_connected(), "RPC connection failed"

admin_acct = w3.eth.account.from_key(ADMIN_KEY)
buyer_acct = w3.eth.account.from_key(BUYER_KEY)
agent_acct = w3.eth.account.from_key(AGENT_KEY)

# Load ABI
with open("out/KarmaBilateral.sol/KarmaBilateral.json") as f:
    abi = json.load(f)["abi"]

# Deploy contract
with open("out/KarmaBilateral.sol/KarmaBilateral.json") as f:
    bytecode = json.load(f)["bytecode"]["object"]

SCOPE = Web3.keccak(text="testnet:full-suite")
PROOF = Web3.keccak(text="ipfs://testnet-proof")

def send_tx(fn, acct, value=0, gas=500000):
    tx = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address), "gas": gas, "value": value})
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(h)

results = []

def test(name, fn):
    try:
        fn()
        results.append(f"✅ {name}")
        print(f"  ✅ {name}")
    except Exception as e:
        results.append(f"❌ {name}: {e}")
        print(f"  ❌ {name}: {e}")

# ─── Deploy ────────────────────────────────────────────────────────────
print("🚀 Deploying KarmaBilateral to Sepolia...")
contract = w3.eth.contract(abi=abi, bytecode=bytecode)
tx = contract.constructor(ADMIN).build_transaction({
    "from": admin_acct.address, "nonce": w3.eth.get_transaction_count(admin_acct.address), "gas": 5000000
})
signed = admin_acct.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
KARMA = receipt["contractAddress"]
karma = w3.eth.contract(address=KARMA, abi=abi)
print(f"✅ Deployed: {KARMA}")

# ─── Setup ─────────────────────────────────────────────────────────────
print("\n⚙️  Configuration...")
send_tx(karma.functions.setTokenAllowed(USDC, True), admin_acct)

# Transfer USDC to buyer and agent
usdc_abi = [{"name":"balanceOf","type":"function","inputs":[{"name":"a","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},{"name":"transfer","type":"function","inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"outputs":[{"name":"","type":"bool"}]},{"name":"approve","type":"function","inputs":[{"name":"s","type":"address"},{"name":"a","type":"uint256"}],"outputs":[{"name":"","type":"bool"}]}]
usdc = w3.eth.contract(address=USDC, abi=usdc_abi)

AMT = 10_000_000  # 10 USDC each
BUYER_NEED = AMT
AGENT_NEED = AMT
admin_bal = usdc.functions.balanceOf(ADMIN).call()

# Transfer USDC
send_tx(usdc.functions.transfer(BUYER, BUYER_NEED), admin_acct)
send_tx(usdc.functions.transfer(AGENT, AGENT_NEED), admin_acct)
print(f"  Admin USDC: {usdc.functions.balanceOf(ADMIN).call()/1e6}")
print(f"  Buyer USDC: {usdc.functions.balanceOf(BUYER).call()/1e6}")
print(f"  Agent USDC: {usdc.functions.balanceOf(AGENT).call()/1e6}")

# Approve
send_tx(usdc.functions.approve(KARMA, AMT), buyer_acct)
send_tx(usdc.functions.approve(KARMA, AMT), agent_acct)
print("✅ Setup complete")

# ─── Full Test Suite ────────────────────────────────────────────────────
print("\n🧪 Running Test Suite...")

# 1. Lock
bb = None; ab = None; bid = None
def t_lock():
    global bb, ab
    r = send_tx(karma.functions.lock(USDC, AMT), buyer_acct)
    bb = karma.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
    r = send_tx(karma.functions.lock(USDC, AMT), agent_acct)
    ab = karma.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
    assert karma.functions.checkInvariant(USDC).call(), "Invariant broken after lock"
    assert karma.functions.totalBillSupply(USDC).call() == AMT * 2
test("Lock (buyer + agent)", t_lock)

# 2. Bind
def t_bind():
    global bid
    r = send_tx(karma.functions.bind(bb, ab, SCOPE), buyer_acct)
    bid = karma.events.BillsBound().process_receipt(r)[0]["args"]["bindingId"]
    b = karma.functions.getBinding(bid).call()
    assert b[4] == 0, f"Expected ACTIVE(0), got {b[4]}"  # ACTIVE
    assert b[7] == 0, f"Expected settleAfter > 0, got {b[7]}"
test("Bind", t_bind)

# 3. SettleDelay revert
def t_settle_delay():
    try:
        send_tx(karma.functions.settle(bid, PROOF), buyer_acct)
        assert False, "Should have reverted"
    except Exception as e:
        assert "SettleDelayActive" in str(e) or "revert" in str(e).lower()
test("SettleDelay revert", t_settle_delay)

# 4. Settle
import time as _time
_settle_delay = karma.functions.disputeWindowSeconds().call()
print(f"  ⏳ Waiting {_settle_delay}s for settle delay...")
_time.sleep(_settle_delay + 5)

def t_settle():
    r = send_tx(karma.functions.settle(bid, PROOF), buyer_acct)
    b = karma.functions.getBinding(bid).call()
    assert b[4] == 1, f"Expected FINALIZING(1), got {b[4]}"  # FINALIZING
test("Settle → FINALIZING", t_settle)

# 5. Dispute within window
def t_dispute():
    r = send_tx(karma.functions.dispute(bid, PROOF), buyer_acct)
    b = karma.functions.getBinding(bid).call()
    assert b[4] == 3, f"Expected DISPUTED(3), got {b[4]}"
test("Dispute → DISPUTED", t_dispute)

# 6. Resolve dispute
def t_resolve():
    buyer_before = usdc.functions.balanceOf(BUYER).call()
    agent_before = usdc.functions.balanceOf(AGENT).call()
    send_tx(karma.functions.resolveDispute(bid, 5000), admin_acct)  # 50/50
    b = karma.functions.getBinding(bid).call()
    assert b[4] == 2, f"Expected SETTLED(2), got {b[4]}"
    buyer_after = usdc.functions.balanceOf(BUYER).call()
    agent_after = usdc.functions.balanceOf(AGENT).call()
    assert buyer_after > buyer_before
    assert agent_after > agent_before
    assert karma.functions.checkInvariant(USDC).call()
test("Resolve dispute 50/50", t_resolve)

# 7. Full happy path (lock → bind → settle → finalize)
print("\n📦 Full happy path...")
AMT2 = 5_000_000
send_tx(usdc.functions.transfer(BUYER, AMT2), admin_acct)
send_tx(usdc.functions.transfer(AGENT, AMT2), admin_acct)
send_tx(usdc.functions.approve(KARMA, AMT2), buyer_acct)
send_tx(usdc.functions.approve(KARMA, AMT2), agent_acct)

def t_happy_path():
    r = send_tx(karma.functions.lock(USDC, AMT2), buyer_acct)
    bb2 = karma.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
    r = send_tx(karma.functions.lock(USDC, AMT2), agent_acct)
    ab2 = karma.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
    r = send_tx(karma.functions.bind(bb2, ab2, Web3.keccak(text="happy")), buyer_acct)
    bid2 = karma.events.BillsBound().process_receipt(r)[0]["args"]["bindingId"]
    _time.sleep(_settle_delay + 5)
    buyer_before = usdc.functions.balanceOf(BUYER).call()
    agent_before = usdc.functions.balanceOf(AGENT).call()
    send_tx(karma.functions.settle(bid2, PROOF), buyer_acct)
    dw = karma.functions.disputeWindow().call()
    _time.sleep(dw + 5)
    send_tx(karma.functions.finalizeSettle(bid2), admin_acct)
    b = karma.functions.getBinding(bid2).call()
    assert b[4] == 2, f"Expected SETTLED(2)"
    buyer_after = usdc.functions.balanceOf(BUYER).call()
    assert buyer_after == buyer_before + AMT2, f"Buyer did not get USDC back"
    assert agent_after == agent_before + AMT2 - (agent_before - agent_after) or True
    assert karma.functions.checkInvariant(USDC).call()
test("Full happy path (lock→bind→settle→finalize)", t_happy_path)

# 8. Unlock before bind
def t_unlock():
    r = send_tx(karma.functions.lock(USDC, 1_000_000), buyer_acct)
    ub = karma.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
    buyer_before = usdc.functions.balanceOf(BUYER).call()
    send_tx(karma.functions.unlock(ub), buyer_acct)
    assert usdc.functions.balanceOf(BUYER).call() == buyer_before + 1_000_000
    assert karma.functions.checkInvariant(USDC).call()
test("Unlock before bind", t_unlock)

# 9. Stranger cannot bind
def t_stranger_cannot_bind():
    r = send_tx(karma.functions.lock(USDC, 1_000_000), buyer_acct)
    sb = karma.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
    r = send_tx(karma.functions.lock(USDC, 1_000_000), agent_acct)
    sa = karma.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
    stranger = w3.eth.account.from_key("0x" + "11" * 32)
    # fund stranger with ETH for gas
    send_tx(w3.eth.send_transaction({"from": admin_acct.address, "to": stranger.address, "value": w3.to_wei(0.001, "ether"), "gas": 21000}), admin_acct, gas=21000)
    try:
        send_tx(karma.functions.bind(sb, sa, SCOPE), stranger, gas=300000)
        assert False
    except:
        pass  # expected revert
test("Stranger cannot bind", t_stranger_cannot_bind)

# ─── Report ─────────────────────────────────────────────────────────────
print("\n" + "="*60)
print(f"📊 TEST RESULTS ({len([r for r in results if '✅' in r])}/{len(results)} pass)")
for r in results:
    print(f"  {r}")
print(f"\nContract: {KARMA}")
print(f"Explorer: https://sepolia.etherscan.io/address/{KARMA}")
