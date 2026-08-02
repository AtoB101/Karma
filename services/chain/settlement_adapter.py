"""
Karma — On-Chain Settlement Adapter (KarmaBilateral)

Connects the off-chain settlement state machine to the active protocol contract:
  KarmaBilateral — lock → mint Bill (1:1) → bind → settle → finalizeSettle

Legacy KarmaSettlementEngine / NonCustodialAgentPayment paths are removed.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from config.settings import settings
from core.schemas import EvidenceBundle, TaskContract, VerificationDecision, VerificationResult

logger = structlog.get_logger(__name__)

# Minimal ABI for KarmaBilateral core surface (lock / bind / settle / views).
KARMA_BILATERAL_ABI: list[dict[str, Any]] = [
    {
        "name": "lock",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "billId", "type": "uint256"}],
    },
    {
        "name": "bind",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "buyerBillId", "type": "uint256"},
            {"name": "agentBillId", "type": "uint256"},
            {"name": "scopeHash", "type": "bytes32"},
        ],
        "outputs": [{"name": "bindingId", "type": "uint256"}],
    },
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
    {
        "name": "finalizeSettle",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "bindingId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "dispute",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "bindingId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "unlock",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "billId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "tokenAllowed",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "token", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
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
                    {"name": "bindingId", "type": "uint256"},
                    {"name": "buyerBillId", "type": "uint256"},
                    {"name": "agentBillId", "type": "uint256"},
                    {"name": "scopeHash", "type": "bytes32"},
                    {"name": "state", "type": "uint8"},
                    {"name": "createdAt", "type": "uint256"},
                    {"name": "settleAfter", "type": "uint256"},
                    {"name": "proofHash", "type": "bytes32"},
                    {"name": "disputedAt", "type": "uint256"},
                    {"name": "disputeInitiator", "type": "address"},
                ],
            }
        ],
    },
]


@dataclass
class ChainTxResult:
    tx_hash: str
    block_number: int
    status: str  # "confirmed" | "failed"
    gas_used: int
    quote_id: Optional[str] = None  # retained for API compat; unused on bilateral
    binding_id: Optional[int] = None
    bill_id: Optional[int] = None
    error: Optional[str] = None


@dataclass
class OnchainStatus:
    task_id: str
    tx_hash: Optional[str]
    block_number: Optional[int]
    confirmed: bool
    error: Optional[str] = None


class OnChainSettlementAdapter:
    """
    Adapter between Karma runtime and KarmaBilateral.

    - lock_funds() validates token allowlist / balance / allowance (and optionally locks)
    - release_payment() calls settle(bindingId, proofHash)
    - refund / dispute remain off-chain decisions unless binding_id is supplied for dispute()
    """

    def __init__(self):
        self._w3 = None
        self._account = None
        self._bilateral_contract = None
        self._erc20_contract = None
        self._chain_id: Optional[int] = None

    def _bilateral_address(self) -> str:
        addr = (settings.karma_bilateral_address or "").strip()
        if not addr:
            raise RuntimeError("KARMA_BILATERAL_ADDRESS not set")
        return addr

    def _get_web3(self):
        if self._w3 is not None:
            return self._w3
        if not settings.testnet_rpc_url:
            raise RuntimeError("TESTNET_RPC_URL not set — cannot connect to chain")
        from web3 import Web3

        self._w3 = Web3(Web3.HTTPProvider(settings.testnet_rpc_url))
        if not self._w3.is_connected():
            raise RuntimeError(f"Cannot connect to RPC: {settings.testnet_rpc_url}")
        self._chain_id = self._w3.eth.chain_id
        logger.info("web3_connected", chain_id=self._chain_id, rpc=settings.testnet_rpc_url)
        return self._w3

    def _get_account(self):
        if self._account is not None:
            return self._account
        if not settings.testnet_private_key:
            raise RuntimeError("TESTNET_PRIVATE_KEY not set")
        from eth_account import Account

        self._account = Account.from_key(settings.testnet_private_key)
        return self._account

    def _get_bilateral(self):
        if self._bilateral_contract is not None:
            return self._bilateral_contract
        w3 = self._get_web3()
        self._bilateral_contract = w3.eth.contract(
            address=w3.to_checksum_address(self._bilateral_address()),
            abi=KARMA_BILATERAL_ABI,
        )
        return self._bilateral_contract

    def _get_erc20(self):
        if self._erc20_contract is not None:
            return self._erc20_contract
        if not settings.erc20_token_address:
            raise RuntimeError("ERC20_TOKEN_ADDRESS not set")
        w3 = self._get_web3()
        erc20_abi = [
            {
                "name": "balanceOf",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "account", "type": "address"}],
                "outputs": [{"name": "", "type": "uint256"}],
            },
            {
                "name": "allowance",
                "type": "function",
                "stateMutability": "view",
                "inputs": [
                    {"name": "owner", "type": "address"},
                    {"name": "spender", "type": "address"},
                ],
                "outputs": [{"name": "", "type": "uint256"}],
            },
            {
                "name": "decimals",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"name": "", "type": "uint8"}],
            },
        ]
        self._erc20_contract = w3.eth.contract(
            address=w3.to_checksum_address(settings.erc20_token_address),
            abi=erc20_abi,
        )
        return self._erc20_contract

    def _send_tx(self, fn) -> ChainTxResult:
        w3 = self._get_web3()
        account = self._get_account()
        chain_id = self._chain_id or w3.eth.chain_id
        tx = fn.build_transaction(
            {
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": chain_id,
            }
        )
        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = w3.eth.send_raw_transaction(raw)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        hx = receipt.transactionHash.hex()
        if not hx.startswith("0x"):
            hx = "0x" + hx
        return ChainTxResult(
            tx_hash=hx,
            block_number=receipt.blockNumber,
            status="confirmed" if receipt.status == 1 else "failed",
            gas_used=receipt.gasUsed,
        )

    # ------------------------------------------------------------------
    # Public adapter methods
    # ------------------------------------------------------------------

    def lock_funds(self, task_contract: TaskContract) -> dict[str, Any]:
        """
        Validate bilateral pre-conditions (token allowlist, balance, allowance).
        Does not always broadcast lock() — callers that already locked off-chain
        capacity only need these checks. When ``task_contract.onchain_do_lock``
        is true, broadcasts lock() and returns bill_id.
        """
        w3 = self._get_web3()
        account = self._get_account()
        bilateral = self._get_bilateral()
        erc20 = self._get_erc20()

        amount_wei = int(task_contract.escrow_amount)
        payer = account.address
        bilateral_addr = self._bilateral_address()
        token = w3.to_checksum_address(settings.erc20_token_address)

        token_allowed = bilateral.functions.tokenAllowed(token).call()
        balance = erc20.functions.balanceOf(w3.to_checksum_address(payer)).call()
        allowance = erc20.functions.allowance(
            w3.to_checksum_address(payer),
            w3.to_checksum_address(bilateral_addr),
        ).call()

        errors = []
        if not token_allowed:
            errors.append("Token not allowed by KarmaBilateral")
        if balance < amount_wei:
            errors.append(f"Insufficient balance: need {amount_wei}, have {balance}")
        if allowance < amount_wei:
            errors.append(f"Insufficient allowance: need {amount_wei}, approved {allowance}")
        if errors:
            raise ValueError(f"Lock pre-checks failed: {errors}")

        result: dict[str, Any] = {
            "task_id": task_contract.task_id,
            "payer": payer,
            "amount_wei": amount_wei,
            "balance": balance,
            "allowance": allowance,
            "token_allowed": token_allowed,
            "contract": "KarmaBilateral",
            "contract_address": bilateral_addr,
            "status": "pre_checks_passed",
        }

        do_lock = bool(getattr(task_contract, "onchain_do_lock", False))
        if do_lock:
            tx_result = self._send_tx(bilateral.functions.lock(token, amount_wei))
            result["status"] = "locked"
            result["tx_hash"] = tx_result.tx_hash
            result["bill_id"] = getattr(task_contract, "onchain_buyer_bill_id", None)

        logger.info("lock_funds_ok", task_id=task_contract.task_id, amount=amount_wei)
        return result

    def submit_evidence_hash(self, task_id: str, bundle: EvidenceBundle) -> str:
        """Compute evidence bundle digest used as settle proofHash input."""
        bundle_data = bundle.model_dump(mode="json")
        raw = json.dumps(bundle_data, sort_keys=True, separators=(",", ":"), default=str).encode()
        bundle_hash = "0x" + hashlib.sha256(raw).hexdigest()
        logger.info("evidence_hash_computed", task_id=task_id, hash=bundle_hash[:16])
        return bundle_hash

    def release_payment(
        self,
        task_contract: TaskContract,
        verification: VerificationResult,
        bundle: EvidenceBundle,
        amount_wei: int,
    ) -> ChainTxResult:
        """
        Call KarmaBilateral.settle(bindingId, proofHash).

        ``task_contract.onchain_binding_id`` must be set (bind already completed).
        """
        if verification.decision != VerificationDecision.RELEASE:
            raise ValueError(f"Cannot release: decision is {verification.decision}")

        binding_id = getattr(task_contract, "onchain_binding_id", None)
        if binding_id is None:
            raise ValueError(
                "Cannot settle: task_contract.onchain_binding_id is required for KarmaBilateral"
            )

        w3 = self._get_web3()
        bilateral = self._get_bilateral()
        proof_hex = self.submit_evidence_hash(task_contract.task_id, bundle)
        proof_bytes = bytes.fromhex(proof_hex[2:] if proof_hex.startswith("0x") else proof_hex)

        result = self._send_tx(bilateral.functions.settle(int(binding_id), proof_bytes))
        result.binding_id = int(binding_id)
        result.quote_id = f"binding:{binding_id}"
        logger.info(
            "bilateral_settle_submitted",
            task_id=task_contract.task_id,
            binding_id=binding_id,
            amount_wei=amount_wei,
            tx=result.tx_hash,
        )
        return result

    def refund_payment(self, task_id: str, verification: VerificationResult) -> dict:
        """Refund remains an off-chain decision unless an unlock/timeout path is wired."""
        _ = verification
        return {
            "status": "offchain_only",
            "action": "refund",
            "task_id": task_id,
            "note": "Use unlock(MINTED) or refundOnTimeout(binding) on KarmaBilateral when applicable",
        }

    def open_dispute(self, task_id: str, bundle_hash: str) -> dict:
        """Dispute recording; on-chain dispute() requires binding_id in a follow-up call path."""
        return {
            "status": "offchain_only",
            "action": "dispute",
            "task_id": task_id,
            "bundle_hash": bundle_hash,
            "note": "Call KarmaBilateral.dispute(bindingId) when binding is FINALIZING/ACTIVE",
        }

    def get_onchain_status(self, tx_hash: str) -> OnchainStatus:
        try:
            w3 = self._get_web3()
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is None:
                return OnchainStatus(task_id="", tx_hash=tx_hash, block_number=None, confirmed=False)
            return OnchainStatus(
                task_id="",
                tx_hash=tx_hash,
                block_number=receipt.blockNumber,
                confirmed=receipt.status == 1,
            )
        except Exception as e:
            return OnchainStatus(
                task_id="", tx_hash=tx_hash, block_number=None, confirmed=False, error=str(e)
            )


class SettlementRouter:
    """
    Routes settlement actions based on SETTLEMENT_MODE:
      offchain — database state only
      testnet  — real on-chain via KarmaBilateral
      hybrid   — off-chain verification, on-chain settle on RELEASE
    """

    def __init__(self):
        self._adapter: Optional[OnChainSettlementAdapter] = None

    def _chain(self) -> OnChainSettlementAdapter:
        if self._adapter is None:
            self._adapter = OnChainSettlementAdapter()
        return self._adapter

    @property
    def mode(self) -> str:
        return settings.settlement_mode

    def is_onchain(self) -> bool:
        return self.mode in ("testnet", "hybrid")

    def should_submit_onchain(self, decision: VerificationDecision) -> bool:
        return self.is_onchain() and decision == VerificationDecision.RELEASE

    def lock_funds(self, task_contract: TaskContract) -> dict[str, Any]:
        if not self.is_onchain():
            return {"status": "offchain", "note": "Settlement mode is offchain — no chain call"}
        return self._chain().lock_funds(task_contract)

    def submit_evidence_hash(self, task_id: str, bundle: EvidenceBundle) -> str:
        return self._chain().submit_evidence_hash(task_id, bundle)

    def release_payment(
        self,
        task_contract: TaskContract,
        verification: VerificationResult,
        bundle: EvidenceBundle,
        amount_wei: int,
    ) -> Optional[ChainTxResult]:
        if not self.should_submit_onchain(verification.decision):
            return None
        return self._chain().release_payment(task_contract, verification, bundle, amount_wei)

    def refund_payment(self, task_id: str, verification: VerificationResult) -> dict:
        if not self.is_onchain():
            return {"status": "offchain"}
        return self._chain().refund_payment(task_id, verification)

    def open_dispute(self, task_id: str, bundle_hash: str) -> dict:
        if not self.is_onchain():
            return {"status": "offchain"}
        return self._chain().open_dispute(task_id, bundle_hash)

    def get_onchain_status(self, tx_hash: str) -> Optional[OnchainStatus]:
        if not self.is_onchain() or not tx_hash:
            return None
        return self._chain().get_onchain_status(tx_hash)


settlement_router = SettlementRouter()
