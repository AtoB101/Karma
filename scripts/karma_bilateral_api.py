"""Minimal standalone KarmaBilateral API server — zero BFF dependency.

Start: KARMA_BILATERAL_ADDRESS=0x... python3 karma_bilateral_api.py
Port:  8822 (default)
"""

import os, hashlib, json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

RPC = os.environ.get("TESTNET_RPC_URL", "https://sepolia.infura.io/v3/")
KARMA = os.environ.get("KARMA_BILATERAL_ADDRESS", "")
USDC = os.environ.get("ERC20_TOKEN_ADDRESS", "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF")
KEY = os.environ.get("TESTNET_PRIVATE_KEY", "")

from web3 import Web3
w3 = Web3(Web3.HTTPProvider(RPC))

with open("out/KarmaBilateral.sol/KarmaBilateral.json") as f:
    ABI = json.load(f)["abi"]

account = w3.eth.account.from_key(KEY) if KEY else None
contract = w3.eth.contract(address=KARMA, abi=ABI) if KARMA else None

app = FastAPI(title="KarmaBilateral API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def send(fn, gas=500000):
    tx = fn.build_transaction({"from": account.address, "nonce": w3.eth.get_transaction_count(account.address), "gas": gas})
    return w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction))

class LockRequest(BaseModel):
    token: str
    amount: int
    role: str = "buyer"

class BindRequest(BaseModel):
    buyer_bill_id: int
    agent_bill_id: int
    scope_hash: str

class SettleRequest(BaseModel):
    binding_id: int
    proof_hash: str

@app.post("/v1/bilateral/lock")
async def lock(body: LockRequest):
    if not contract: raise HTTPException(503, "not configured")
    token = body.token or USDC
    # approve first
    usdc = w3.eth.contract(address=token, abi=[{"name":"approve","type":"function","inputs":[{"name":"s","type":"address"},{"name":"a","type":"uint256"}],"outputs":[{"name":"","type":"bool"}]}])
    allow = usdc.functions.allowance(account.address, KARMA).call()
    if allow < body.amount:
        send(usdc.functions.approve(KARMA, body.amount))
    r = send(contract.functions.lock(token, body.amount))
    try:
        bill_id = contract.events.BillMinted().process_receipt(r)[0]["args"]["billId"]
    except:
        bill_id = 0
    bill = contract.functions.getBill(bill_id).call()
    return {"bill_id": bill_id, "owner": bill[1], "token": bill[2], "amount": bill[3], "state": ["MINTED","BOUND","BURNED"][bill[4]]}

@app.post("/v1/bilateral/bind")
async def bind(body: BindRequest):
    if not contract: raise HTTPException(503, "not configured")
    r = send(contract.functions.bind(body.buyer_bill_id, body.agent_bill_id, bytes.fromhex(body.scope_hash.replace("0x",""))))
    try:
        bid = contract.events.BillsBound().process_receipt(r)[0]["args"]["bindingId"]
    except:
        bid = 0
    b = contract.functions.getBinding(bid).call()
    return {"binding_id": bid, "buyer_bill_id": b[1], "agent_bill_id": b[2], "state": ["ACTIVE","FINALIZING","SETTLED","DISPUTED","REFUNDED"][b[4]]}

@app.post("/v1/bilateral/settle")
async def settle(body: SettleRequest):
    if not contract: raise HTTPException(503, "not configured")
    send(contract.functions.settle(body.binding_id, bytes.fromhex(body.proof_hash.replace("0x",""))))
    return _status(body.binding_id)

@app.post("/v1/bilateral/finalize/{binding_id}")
async def finalize(binding_id: int):
    if not contract: raise HTTPException(503, "not configured")
    send(contract.functions.finalizeSettle(binding_id))
    return _status(binding_id)

@app.get("/v1/bilateral/status/{binding_id}")
async def status(binding_id: int):
    if not contract: raise HTTPException(503, "not configured")
    return _status(binding_id)

def _status(bid):
    b = contract.functions.getBinding(bid).call()
    bb = contract.functions.getBill(b[1]).call()
    ab = contract.functions.getBill(b[2]).call()
    return {
        "binding_id": bid,
        "state": ["ACTIVE","FINALIZING","SETTLED","DISPUTED","REFUNDED"][b[4]],
        "bill_states": [
            {"bill_id": bb[0], "owner": bb[1], "amount": bb[3], "state": ["MINTED","BOUND","BURNED"][bb[4]]},
            {"bill_id": ab[0], "owner": ab[1], "amount": ab[3], "state": ["MINTED","BOUND","BURNED"][ab[4]]},
        ],
        "can_settle": b[4] == 0,
        "can_dispute": b[4] == 1,
        "can_finalize": b[4] == 1,
        "usdc_locked": bb[3] + ab[3],
        "settle_after": b[6],
    }

@app.get("/health")
async def health():
    return {"status": "ok", "contract": KARMA, "rpc": RPC[:50]}


@app.post("/faucet/{address}")
async def faucet(address: str):
    """Send 100 mUSDC to a Sepolia address. For testnet onboarding."""
    usdc = w3.eth.contract(address=USDC, abi=[{"name":"transfer","type":"function","inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"outputs":[{"name":"","type":"bool"}]},{"name":"balanceOf","type":"function","inputs":[{"name":"a","type":"address"}],"outputs":[{"name":"","type":"uint256"}]}])
    bal = usdc.functions.balanceOf(account.address).call()
    amt = 100_000_000  # 100 mUSDC
    if bal < amt:
        raise HTTPException(503, "Faucet dry — admin needs more mUSDC")
    tx = usdc.functions.transfer(Web3.to_checksum_address(address), amt).build_transaction({
        "from": account.address, "nonce": w3.eth.get_transaction_count(account.address), "gas": 100000,
    })
    signed = account.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=60)
    return {"ok": True, "amount": "100 mUSDC", "to": address, "tx": h.hex()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8822"))
    uvicorn.run(app, host="0.0.0.0", port=port)
