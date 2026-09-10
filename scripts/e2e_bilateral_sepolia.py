"""Deploy the NEW KarmaBilateral to Sepolia and run a real cross-agent E2E.

Buyer (W1) locks the full order; seller (W2) locks the 10% penalty; then
bind -> settle -> finalizeSettle releases the buyer's payment to the seller.
"""
import json
import time

from web3 import Web3
from eth_account import Account

RPC = "https://ethereum-sepolia-rpc.publicnode.com"
USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
BUYER_KEY = "a3bd6e441963f0b097458d5658884633eaeb1dec8e0142e4f23ce64ebe10b3df"
SELLER_KEY = "0c85cad5f38c90311e4b1a069e95b76954988222492ccb418c8f115af3f56d94"

w3 = Web3(Web3.HTTPProvider(RPC))
assert w3.is_connected()
print("chain", w3.eth.chain_id)

buyer = Account.from_key(BUYER_KEY)
seller = Account.from_key(SELLER_KEY)

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "mint", "outputs": [], "type": "function"},
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
]
usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)


def send(account, fn, value=0):
    tx = fn.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": w3.eth.chain_id,
        "value": value,
    })
    signed = account.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(h)


# ── 1. Deploy KarmaBilateral (new asymmetric version) ──
art = json.load(open("out/KarmaBilateral.sol/KarmaBilateral.json", encoding="utf-8"))
kb = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
# seller deploys (has enough ETH) and is admin
admin = seller
tx = kb.constructor(admin.address).build_transaction({
    "from": admin.address,
    "nonce": w3.eth.get_transaction_count(admin.address),
    "chainId": w3.eth.chain_id,
})
signed = admin.sign_transaction(tx)
h = w3.eth.send_raw_transaction(signed.raw_transaction)
r = w3.eth.wait_for_transaction_receipt(h)
kb = w3.eth.contract(address=r.contractAddress, abi=art["abi"])
print("deployed KarmaBilateral:", kb.address)

# ── 2. Wire: allow token + zero the windows for a fast E2E ──
send(admin, kb.functions.setTokenAllowed(Web3.to_checksum_address(USDC), True))
send(admin, kb.functions.setDisputeWindow(0))            # settle delay = 0
send(admin, kb.functions.setOptimisticDisputeWindow(0))  # dispute window = 0

# ── 3. Fund seller with penalty + approve both ──
UNIT = 10**6
AMOUNT = 100 * UNIT      # buyer locks 100 mUSDC (full order)
PENALTY = 10 * UNIT      # seller locks 10 mUSDC (10% penalty)
send(admin, usdc.functions.mint(seller.address, PENALTY))
send(buyer, usdc.functions.approve(kb.address, AMOUNT))
send(seller, usdc.functions.approve(kb.address, PENALTY))

b_before = usdc.functions.balanceOf(buyer.address).call()
s_before = usdc.functions.balanceOf(seller.address).call()

# ── 4. lock buyer + seller ──
r = send(buyer, kb.functions.lock(Web3.to_checksum_address(USDC), AMOUNT))
bb = kb.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
r = send(seller, kb.functions.lock(Web3.to_checksum_address(USDC), PENALTY))
ab = kb.events.BillMinted().process_receipt(r)[0]["args"]["billId"]

# ── 5. bind ──
scope = Web3.keccak(text="karma-sepolia-cross-agent")
r = send(buyer, kb.functions.bind(bb, ab, scope))
binding = kb.events.BillsBound().process_receipt(r)[0]["args"]["bindingId"]

# ── 6. settle -> finalize ──
proof = Web3.keccak(text="hermes-delivered-to-claw")
send(seller, kb.functions.settle(binding, proof))
send(buyer, kb.functions.finalizeSettle(binding))

b_after = usdc.functions.balanceOf(buyer.address).call()
s_after = usdc.functions.balanceOf(seller.address).call()
escrow = usdc.functions.balanceOf(kb.address).call()

assert escrow == 0, f"escrow not drained: {escrow}"
assert b_after == b_before - AMOUNT, f"buyer should pay {AMOUNT}, delta={b_before - b_after}"
assert s_after == s_before + AMOUNT, f"seller should receive {AMOUNT}, delta={s_after - s_before}"

print("=" * 60)
print("  SEPOLIA CROSS-AGENT E2E: PASS")
print("=" * 60)
print("  bilateral :", kb.address)
print("  buyerBill :", bb, " agentBill:", ab, " binding:", binding)
print(f"  buyer  {b_before/UNIT:.2f} -> {b_after/UNIT:.2f} mUSDC  (paid {AMOUNT/UNIT:.0f})")
print(f"  seller {s_before/UNIT:.2f} -> {s_after/UNIT:.2f} mUSDC  (received {AMOUNT/UNIT:.0f})")
print("  escrow    :", escrow, "(drained)")
