"""
karma_sdk.client — KarmaBilateral Python client.

Three-line integration:
    from karma_sdk import KarmaBilateral
    k = KarmaBilateral(rpc_url, private_key, contract_address)
    bill = k.lock("0xUSDC_ADDRESS", 100_000_000)   # 100 USDC (6 decimals)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# web3.py is the only runtime dependency
try:
    from web3 import Web3
    from web3.contract import Contract
    from web3.types import TxReceipt
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "web3 is required: pip install web3"
    ) from exc

# ── ABI (minimal — only the three core methods + events) ─────────────────────

# ── Custom Exceptions ────────────────────────────────────────────────────────

class TransactionError(Exception):
    """Transaction failed (revert, gas, or build failure)."""

class NonceError(TransactionError):
    """Nonce mismatch — likely due to pending transactions."""

class BalanceError(TransactionError):
    """Insufficient ETH or token balance."""

class InvalidStateError(Exception):
    """Contract state does not permit this operation."""

class TimeoutError(Exception):
    """Operation timed out (e.g., waiting for receipt)."""


_ABI = [
    # lock
    {
        "name": "lock",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "token",  "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "billId", "type": "uint256"}],
    },
    # bind
    {
        "name": "bind",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "buyerBillId", "type": "uint256"},
            {"name": "agentBillId", "type": "uint256"},
            {"name": "scopeHash",   "type": "bytes32"},
        ],
        "outputs": [{"name": "bindingId", "type": "uint256"}],
    },
    # settle
    {
        "name": "settle",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "bindingId", "type": "uint256"},
            {"name": "proofHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    # unlock (pre-bind withdrawal)
    {
        "name": "unlock",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "billId", "type": "uint256"}],
        "outputs": [],
    },
    # views
    {
        "name": "getBill",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "billId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "billId",   "type": "uint256"},
                    {"name": "owner",    "type": "address"},
                    {"name": "token",    "type": "address"},
                    {"name": "amount",   "type": "uint256"},
                    {"name": "state",    "type": "uint8"},
                    {"name": "mintedAt", "type": "uint256"},
                ],
            }
        ],
    },
    {
        "name": "getBinding",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "bindingId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "bindingId",       "type": "uint256"},
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
            }
        ],
    },
    {
        "name": "checkInvariant",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "token", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    # ERC-20 approve helper ABI (used internally)
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount",  "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    # events
    {
        "name": "BillMinted",
        "type": "event",
        "inputs": [
            {"name": "billId", "type": "uint256", "indexed": True},
            {"name": "owner",  "type": "address", "indexed": True},
            {"name": "token",  "type": "address", "indexed": False},
            {"name": "amount", "type": "uint256", "indexed": False},
        ],
    },
    {
        "name": "BillsBound",
        "type": "event",
        "inputs": [
            {"name": "bindingId",   "type": "uint256", "indexed": True},
            {"name": "buyerBillId", "type": "uint256", "indexed": False},
            {"name": "agentBillId", "type": "uint256", "indexed": False},
            {"name": "scopeHash",   "type": "bytes32", "indexed": False},
        ],
    },
    {
        "name": "BindingSettled",
        "type": "event",
        "inputs": [
            {"name": "bindingId",   "type": "uint256", "indexed": True},
            {"name": "proofHash",   "type": "bytes32", "indexed": False},
            {"name": "buyerAmount", "type": "uint256", "indexed": False},
            {"name": "agentAmount", "type": "uint256", "indexed": False},
        ],
    },
]

# ── Bill / Binding state constants ────────────────────────────────────────────

BILL_STATE  = {0: "MINTED", 1: "BOUND", 2: "BURNED"}
BINDING_STATE = {0: "ACTIVE", 1: "PENDING", 2: "SETTLED", 3: "DISPUTED", 4: "REFUNDED"}


@dataclass
class BillToken:
    bill_id:   int
    owner:     str
    token:     str
    amount:    int
    state:     str
    minted_at: int


@dataclass
class Binding:
    binding_id:       int
    buyer_bill_id:    int
    agent_bill_id:    int
    scope_hash:       bytes
    state:            str
    created_at:       int
    settle_after:     int
    proof_hash:       bytes
    disputed_at:      int
    dispute_initiator: str


class KarmaBilateral:
    """
    Minimal client for KarmaBilateral.sol.

    Usage::

        from karma_sdk import KarmaBilateral
        k = KarmaBilateral(rpc_url, private_key, contract_address)
        bill_id    = k.lock(usdc_address, 100_000_000)
        binding_id = k.bind(buyer_bill_id, agent_bill_id, scope_hash)
        k.settle(binding_id, proof_hash)
    """

    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        contract_address: str,
        gas: int = 300_000,
    ) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._account = self.w3.eth.account.from_key(private_key)
        self._contract: Contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=_ABI,
        )
        self.gas = gas

    # ── Core three methods ────────────────────────────────────────────────────

    def lock(self, token: str, amount: int, approve: bool = True) -> int:
        """
        Lock `amount` of `token` and mint a Bill Token.

        Args:
            token:   ERC-20 contract address (must be allowlisted in KarmaBilateral)
            amount:  Amount in token base units (e.g. 100_000_000 for 100 USDC)
            approve: If True, automatically sends an ERC-20 approve tx first

        Returns:
            billId of the newly minted Bill Token
        """
        if approve:
            self._approve(token, amount)

        receipt = self._send(self._contract.functions.lock(
            Web3.to_checksum_address(token),
            amount,
        ))
        logs = self._contract.events.BillMinted().process_receipt(receipt)
        return int(logs[0]["args"]["billId"])

    def bind(
        self,
        buyer_bill_id: int,
        agent_bill_id: int,
        scope_hash: bytes | str,
    ) -> int:
        """
        Bilaterally bind a buyer Bill and an agent Bill.

        Args:
            buyer_bill_id: Bill Token ID held by the demand side
            agent_bill_id: Bill Token ID held by the supply side
            scope_hash:    32-byte task scope hash (bytes or 0x hex string)

        Returns:
            bindingId of the created Binding
        """
        scope = _to_bytes32(scope_hash)
        receipt = self._send(self._contract.functions.bind(
            buyer_bill_id,
            agent_bill_id,
            scope,
        ))
        logs = self._contract.events.BillsBound().process_receipt(receipt)
        return int(logs[0]["args"]["bindingId"])

    def settle(self, binding_id: int, proof_hash: bytes | str) -> TxReceipt:
        """
        Settle a Binding: verify proof, burn both Bills, release USDC.

        Args:
            binding_id: Binding to settle (must be ACTIVE or PENDING)
            proof_hash: 32-byte proof / evidence hash

        Returns:
            Transaction receipt
        """
        proof = _to_bytes32(proof_hash)
        return self._send(self._contract.functions.settle(binding_id, proof))

    # ── Convenience methods ───────────────────────────────────────────────────

    def unlock(self, bill_id: int) -> TxReceipt:
        """Withdraw a MINTED (unbound) Bill Token and reclaim locked funds."""
        return self._send(self._contract.functions.unlock(bill_id))

    def get_bill(self, bill_id: int) -> BillToken:
        raw = self._contract.functions.getBill(bill_id).call()
        return BillToken(
            bill_id=raw[0], owner=raw[1], token=raw[2], amount=raw[3],
            state=BILL_STATE.get(raw[4], str(raw[4])), minted_at=raw[5],
        )

    def get_binding(self, binding_id: int) -> Binding:
        raw = self._contract.functions.getBinding(binding_id).call()
        return Binding(
            binding_id=raw[0], buyer_bill_id=raw[1], agent_bill_id=raw[2],
            scope_hash=raw[3], state=BINDING_STATE.get(raw[4], str(raw[4])),
            created_at=raw[5], settle_after=raw[6], proof_hash=raw[7],
            disputed_at=raw[8], dispute_initiator=raw[9],
        )

    def check_invariant(self, token: str) -> bool:
        """Returns True if totalBillSupply[token] == totalLocked[token]."""
        return self._contract.functions.checkInvariant(
            Web3.to_checksum_address(token)
        ).call()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _approve(self, token: str, amount: int) -> None:
        erc20 = self.w3.eth.contract(
            address=Web3.to_checksum_address(token), abi=_ABI
        )
        self._send(erc20.functions.approve(self._contract.address, amount))

    def _send(self, fn, value: int = 0) -> TxReceipt:
        """Send transaction with error handling."""
        try:
            tx = fn.build_transaction({
                "from":  self._account.address,
                "nonce": self.w3.eth.get_transaction_count(self._account.address),
                "gas":   self.gas,
                "value": value,
            })
        except Exception as e:
            raise TransactionError(f"build_transaction failed: {e}") from e

        try:
            signed  = self._account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status != 1:
                raise TransactionError(f"tx {tx_hash.hex()} reverted")
            return receipt
        except ValueError as e:
            if "nonce" in str(e).lower():
                raise NonceError(str(e)) from e
            if "insufficient funds" in str(e).lower():
                raise BalanceError(str(e)) from e
            raise TransactionError(str(e)) from e
        except Exception as e:
            raise TransactionError(f"send failed: {e}") from e

    def get_nonce(self) -> int:
        return self.w3.eth.get_transaction_count(self._account.address)

    def get_balance(self, token: str | None = None) -> int:
        """Get ETH balance or ERC-20 token balance."""
        if token is None:
            return self.w3.eth.get_balance(self._account.address)
        erc20 = self.w3.eth.contract(
            address=Web3.to_checksum_address(token),
            abi=[{"name":"balanceOf","type":"function","inputs":[{"name":"a","type":"address"}],"outputs":[{"name":"","type":"uint256"}]}]
        )
        return erc20.functions.balanceOf(self._account.address).call()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_bytes32(value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = bytes.fromhex(value.removeprefix("0x"))
    if len(value) != 32:
        raise ValueError(f"Expected 32-byte hash, got {len(value)} bytes")
    return value
