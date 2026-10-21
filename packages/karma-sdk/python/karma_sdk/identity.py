"""karma_sdk.identity — KarmaIdentityRegistry client (bounded sub-agent authorization).

Master flow (master wallet signs)::

    from karma_sdk import KarmaBilateral, KarmaIdentityRegistry

    karma = KarmaBilateral(rpc, master_key, KARMA_ADDR)
    ident = KarmaIdentityRegistry(rpc, master_key, IDENTITY_ADDR)

    ident.register_identity(master_agent_id)
    bill = karma.lock(usdc, 3_000_000)                 # establish free balance
    ident.add_sub_agent(sub_wallet, sub_agent_id)
    # allowance = cumulative budget, per_tx_limit = per-transaction cap
    ident.set_sub_agent_bounds(sub_wallet, 2_000_000, 1_000_000, expires_at=0)

Sub-agent flow (sub wallet signs)::

    sub_karma = KarmaBilateral(rpc, sub_key, KARMA_ADDR)
    bill = sub_karma.lock_for(usdc, 1_000_000, master_address)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from web3 import Web3
from web3.contract import Contract
from web3.types import TxReceipt

from .client import (
    BalanceError,
    NonceError,
    TransactionError,
    _to_bytes32,
)

_IDENTITY_ABI = [
    {
        "name": "registerIdentity",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "masterAgentId", "type": "bytes32"}],
        "outputs": [],
    },
    {
        "name": "addSubAgent",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "subWallet", "type": "address"},
            {"name": "subAgentId", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "name": "removeSubAgent",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "subWallet", "type": "address"}],
        "outputs": [],
    },
    {
        "name": "setSubAgentBounds",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "subWallet", "type": "address"},
            {"name": "allowance", "type": "uint256"},
            {"name": "perTxLimit", "type": "uint256"},
            {"name": "expiresAt", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "name": "isAuthorized",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "subWallet", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "getSubAgents",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "master", "type": "address"}],
        "outputs": [
            {
                "name": "active",
                "type": "tuple[]",
                "components": [
                    {"name": "subWallet", "type": "address"},
                    {"name": "subAgentId", "type": "bytes32"},
                    {"name": "master", "type": "address"},
                    {"name": "allowance", "type": "uint256"},
                    {"name": "perTxLimit", "type": "uint256"},
                    {"name": "expiresAt", "type": "uint256"},
                    {"name": "status", "type": "uint8"},
                    {"name": "addedAt", "type": "uint256"},
                    {"name": "removedAt", "type": "uint256"},
                ],
            }
        ],
    },
    {
        "name": "getIdentity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "master", "type": "address"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "masterWallet", "type": "address"},
                    {"name": "masterAgentId", "type": "bytes32"},
                    {"name": "registered", "type": "bool"},
                ],
            }
        ],
    },
    {
        "name": "getMasterOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "subWallet", "type": "address"}],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "name": "getMaster",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "subAgentId", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "address"}],
    },
]


@dataclass
class SubAgent:
    sub_wallet: str
    sub_agent_id: bytes
    master: str
    allowance: int
    per_tx_limit: int
    expires_at: int
    status: int
    added_at: int
    removed_at: int


@dataclass
class Identity:
    master_wallet: str
    master_agent_id: bytes
    registered: bool


class KarmaIdentityRegistry:
    """Minimal client for KarmaIdentityRegistry.sol — bounded sub-agent grants."""

    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        contract_address: str,
        gas: int = 2_000_000,
    ) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._account = self.w3.eth.account.from_key(private_key)
        self._contract: Contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=_IDENTITY_ABI,
        )
        self.gas = gas
        self._nonce: Optional[int] = None

    # ── Master mutations ─────────────────────────────────────────────────────

    def register_identity(self, master_agent_id: bytes | str) -> TxReceipt:
        """Register the signing wallet as a master identity."""
        return self._send(self._contract.functions.registerIdentity(
            _to_bytes32(master_agent_id)
        ))

    def add_sub_agent(self, sub_wallet: str, sub_agent_id: bytes | str) -> TxReceipt:
        """Add an active sub-agent wallet under the signing master."""
        return self._send(self._contract.functions.addSubAgent(
            Web3.to_checksum_address(sub_wallet),
            _to_bytes32(sub_agent_id),
        ))

    def set_sub_agent_bounds(
        self,
        sub_wallet: str,
        allowance: int,
        per_tx_limit: int,
        expires_at: int = 0,
    ) -> TxReceipt:
        """Set a sub-agent spending envelope: budget, per-tx cap, expiry."""
        return self._send(self._contract.functions.setSubAgentBounds(
            Web3.to_checksum_address(sub_wallet),
            allowance,
            per_tx_limit,
            expires_at,
        ))

    def remove_sub_agent(self, sub_wallet: str) -> TxReceipt:
        """Deactivate a sub-agent (reverts if it holds bound balance)."""
        return self._send(self._contract.functions.removeSubAgent(
            Web3.to_checksum_address(sub_wallet)
        ))

    # ── Views ─────────────────────────────────────────────────────────────────

    def is_authorized(self, sub_wallet: str, amount: int) -> bool:
        """True when `sub_wallet` may currently spend `amount` for its master."""
        return self._contract.functions.isAuthorized(
            Web3.to_checksum_address(sub_wallet), amount
        ).call()

    def get_sub_agents(self, master: str) -> list[SubAgent]:
        raw = self._contract.functions.getSubAgents(
            Web3.to_checksum_address(master)
        ).call()
        return [self._to_sub_agent(item) for item in raw]

    def get_identity(self, master: str) -> Identity:
        raw = self._contract.functions.getIdentity(
            Web3.to_checksum_address(master)
        ).call()
        return Identity(master_wallet=raw[0], master_agent_id=bytes(raw[1]), registered=raw[2])

    def get_master_of(self, sub_wallet: str) -> str:
        return self._contract.functions.getMasterOf(
            Web3.to_checksum_address(sub_wallet)
        ).call()

    def get_master(self, sub_agent_id: bytes | str) -> str:
        return self._contract.functions.getMaster(_to_bytes32(sub_agent_id)).call()

    # ── Internal helpers (mirror KarmaBilateral) ──────────────────────────────

    @staticmethod
    def _to_sub_agent(raw: tuple) -> SubAgent:
        return SubAgent(
            sub_wallet=raw[0], sub_agent_id=bytes(raw[1]), master=raw[2],
            allowance=raw[3], per_tx_limit=raw[4], expires_at=raw[5],
            status=raw[6], added_at=raw[7], removed_at=raw[8],
        )

    def _next_nonce(self) -> int:
        if self._nonce is None:
            self._nonce = self.w3.eth.get_transaction_count(self._account.address, "pending")
        nonce = self._nonce
        self._nonce += 1
        return nonce

    def _estimate_gas(self, fn, nonce: int, value: int) -> int:
        try:
            estimated = fn.estimate_gas({
                "from": self._account.address,
                "nonce": nonce,
                "value": value,
            })
            return int(estimated * 1.3)
        except Exception:
            return self.gas

    def _send(self, fn, value: int = 0) -> TxReceipt:
        last_nonce_error: Exception | None = None
        for _ in range(2):
            nonce = self._next_nonce()
            try:
                tx = fn.build_transaction({
                    "from": self._account.address,
                    "nonce": nonce,
                    "gas": self._estimate_gas(fn, nonce, value),
                    "value": value,
                })
            except Exception as e:
                raise TransactionError(f"build_transaction failed: {e}") from e

            try:
                signed = self._account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                if receipt.status != 1:
                    raise TransactionError(f"tx {tx_hash.hex()} reverted")
                return receipt
            except ValueError as e:
                message = str(e).lower()
                if "nonce" in message:
                    last_nonce_error = e
                    self._nonce = None
                    continue
                if "insufficient funds" in message:
                    raise BalanceError(str(e)) from e
                raise TransactionError(str(e)) from e
            except Exception as e:
                raise TransactionError(f"send failed: {e}") from e

        raise NonceError(str(last_nonce_error)) from last_nonce_error

    def get_nonce(self) -> int:
        return self.w3.eth.get_transaction_count(self._account.address, "pending")
