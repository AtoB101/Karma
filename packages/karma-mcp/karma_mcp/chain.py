"""
karma_mcp.chain — thin web3.py wrapper around KarmaBilateral.sol.

Reads config from environment:
    KARMA_RPC_URL        JSON-RPC endpoint (required)
    KARMA_PRIVATE_KEY    hex private key, 0x-prefixed (required)
    KARMA_CONTRACT       KarmaBilateral contract address (required)
    KARMA_GAS            gas limit per tx (default 300000)
"""

from __future__ import annotations

import os
from functools import lru_cache

from web3 import Web3

# ── Minimal ABI ───────────────────────────────────────────────────────────────

_ABI = [
    {
        "name": "lock", "type": "function", "stateMutability": "nonpayable",
        "inputs":  [{"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "billId", "type": "uint256"}],
    },
    {
        "name": "bind", "type": "function", "stateMutability": "nonpayable",
        "inputs": [
            {"name": "buyerBillId", "type": "uint256"},
            {"name": "agentBillId", "type": "uint256"},
            {"name": "scopeHash",   "type": "bytes32"},
        ],
        "outputs": [{"name": "bindingId", "type": "uint256"}],
    },
    {
        "name": "settle", "type": "function", "stateMutability": "nonpayable",
        "inputs": [
            {"name": "bindingId", "type": "uint256"},
            {"name": "proofHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "name": "unlock", "type": "function", "stateMutability": "nonpayable",
        "inputs":  [{"name": "billId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "getBill", "type": "function", "stateMutability": "view",
        "inputs":  [{"name": "billId", "type": "uint256"}],
        "outputs": [{
            "name": "", "type": "tuple",
            "components": [
                {"name": "billId",   "type": "uint256"},
                {"name": "owner",    "type": "address"},
                {"name": "token",    "type": "address"},
                {"name": "amount",   "type": "uint256"},
                {"name": "state",    "type": "uint8"},
                {"name": "mintedAt", "type": "uint256"},
            ],
        }],
    },
    {
        "name": "getBinding", "type": "function", "stateMutability": "view",
        "inputs":  [{"name": "bindingId", "type": "uint256"}],
        "outputs": [{
            "name": "", "type": "tuple",
            "components": [
                {"name": "bindingId",        "type": "uint256"},
                {"name": "buyerBillId",      "type": "uint256"},
                {"name": "agentBillId",      "type": "uint256"},
                {"name": "scopeHash",        "type": "bytes32"},
                {"name": "state",            "type": "uint8"},
                {"name": "createdAt",        "type": "uint256"},
                {"name": "settleAfter",      "type": "uint256"},
                {"name": "proofHash",        "type": "bytes32"},
                {"name": "disputedAt",       "type": "uint256"},
                {"name": "disputeInitiator", "type": "address"},
            ],
        }],
    },
    {
        "name": "checkInvariant", "type": "function", "stateMutability": "view",
        "inputs":  [{"name": "token", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    # ERC-20 approve
    {
        "name": "approve", "type": "function", "stateMutability": "nonpayable",
        "inputs":  [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    # events
    {
        "name": "BillMinted", "type": "event",
        "inputs": [
            {"name": "billId", "type": "uint256", "indexed": True},
            {"name": "owner",  "type": "address", "indexed": True},
            {"name": "token",  "type": "address", "indexed": False},
            {"name": "amount", "type": "uint256", "indexed": False},
        ],
    },
    {
        "name": "BillsBound", "type": "event",
        "inputs": [
            {"name": "bindingId",   "type": "uint256", "indexed": True},
            {"name": "buyerBillId", "type": "uint256", "indexed": False},
            {"name": "agentBillId", "type": "uint256", "indexed": False},
            {"name": "scopeHash",   "type": "bytes32", "indexed": False},
        ],
    },
    {
        "name": "BindingSettled", "type": "event",
        "inputs": [
            {"name": "bindingId",   "type": "uint256", "indexed": True},
            {"name": "proofHash",   "type": "bytes32", "indexed": False},
            {"name": "buyerAmount", "type": "uint256", "indexed": False},
            {"name": "agentAmount", "type": "uint256", "indexed": False},
        ],
    },
]

_BILL_STATE    = {0: "MINTED", 1: "BOUND", 2: "BURNED"}
_BINDING_STATE = {0: "ACTIVE", 1: "PENDING", 2: "SETTLED", 3: "DISPUTED", 4: "REFUNDED"}


@lru_cache(maxsize=1)
def _client():
    rpc      = os.environ["KARMA_RPC_URL"]
    pk       = os.environ["KARMA_PRIVATE_KEY"]
    contract = os.environ["KARMA_CONTRACT"]
    gas      = int(os.getenv("KARMA_GAS", "300000"))

    w3      = Web3(Web3.HTTPProvider(rpc))
    account = w3.eth.account.from_key(pk)
    karma   = w3.eth.contract(address=Web3.to_checksum_address(contract), abi=_ABI)
    return w3, account, karma, gas


def _send(fn) -> dict:
    w3, account, _, gas = _client()
    tx = fn.build_transaction({
        "from":  account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas":   gas,
    })
    signed   = account.sign_transaction(tx)
    tx_hash  = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt  = w3.eth.wait_for_transaction_receipt(tx_hash)
    return {"tx_hash": receipt.transactionHash.hex(), "status": receipt.status}


def _approve(token: str, amount: int) -> None:
    w3, account, karma, gas = _client()
    erc20 = w3.eth.contract(address=Web3.to_checksum_address(token), abi=_ABI)
    _send_raw(erc20.functions.approve(karma.address, amount), w3, account, gas)


def _send_raw(fn, w3, account, gas) -> None:
    tx = fn.build_transaction({
        "from":  account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas":   gas,
    })
    signed  = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash)


# ── Public functions called by MCP tools ──────────────────────────────────────

def chain_lock(token: str, amount: int, auto_approve: bool = True) -> dict:
    _, _, karma, _ = _client()
    if auto_approve:
        _approve(token, amount)
    receipt_info = _send(karma.functions.lock(Web3.to_checksum_address(token), amount))

    # parse billId from receipt logs
    w3, _, karma2, _ = _client()
    receipt = w3.eth.get_transaction_receipt(receipt_info["tx_hash"])
    logs    = karma2.events.BillMinted().process_receipt(receipt)
    bill_id = int(logs[0]["args"]["billId"]) if logs else None
    return {**receipt_info, "bill_id": bill_id}


def chain_bind(buyer_bill_id: int, agent_bill_id: int, scope_hash: str) -> dict:
    _, _, karma, _ = _client()
    scope = bytes.fromhex(scope_hash.removeprefix("0x").ljust(64, "0")[:64])
    receipt_info = _send(karma.functions.bind(buyer_bill_id, agent_bill_id, scope))

    w3, _, karma2, _ = _client()
    receipt    = w3.eth.get_transaction_receipt(receipt_info["tx_hash"])
    logs       = karma2.events.BillsBound().process_receipt(receipt)
    binding_id = int(logs[0]["args"]["bindingId"]) if logs else None
    return {**receipt_info, "binding_id": binding_id}


def chain_settle(binding_id: int, proof_hash: str) -> dict:
    _, _, karma, _ = _client()
    proof = bytes.fromhex(proof_hash.removeprefix("0x").ljust(64, "0")[:64])
    return _send(karma.functions.settle(binding_id, proof))


def chain_unlock(bill_id: int) -> dict:
    _, _, karma, _ = _client()
    return _send(karma.functions.unlock(bill_id))


def chain_get_bill(bill_id: int) -> dict:
    _, _, karma, _ = _client()
    r = karma.functions.getBill(bill_id).call()
    return {
        "bill_id":   r[0], "owner": r[1], "token": r[2], "amount": r[3],
        "state":     _BILL_STATE.get(r[4], str(r[4])),
        "minted_at": r[5],
    }


def chain_get_binding(binding_id: int) -> dict:
    _, _, karma, _ = _client()
    r = karma.functions.getBinding(binding_id).call()
    return {
        "binding_id":       r[0], "buyer_bill_id": r[1], "agent_bill_id": r[2],
        "scope_hash":       r[3].hex(), "state": _BINDING_STATE.get(r[4], str(r[4])),
        "created_at":       r[5], "settle_after": r[6],
        "proof_hash":       r[7].hex(), "disputed_at": r[8],
        "dispute_initiator": r[9],
    }


def chain_check_invariant(token: str) -> dict:
    _, _, karma, _ = _client()
    ok = karma.functions.checkInvariant(Web3.to_checksum_address(token)).call()
    return {"token": token, "invariant_ok": ok}
