"""
Karma — On-Chain Settlement Adapter (KarmaBilateral)

Connects the off-chain settlement state machine to the active protocol contract:
  KarmaBilateral — lock → mint Bill (1:1) → bind → settle → finalizeSettle

Legacy KarmaSettlementEngine / NonCustodialAgentPayment paths are removed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from config.settings import settings
from core.schemas import EvidenceBundle, TaskContract, VerificationDecision, VerificationResult

logger = structlog.get_logger(__name__)

# Minimal ABI for KarmaBilateral core surface.
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
        "inputs": [
            {"name": "bindingId", "type": "uint256"},
            {"name": "evidenceHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "name": "refundOnTimeout",
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
        "name": "finalizeAfter",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "bindingId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
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
    {
        "name": "BillMinted",
        "type": "event",
        "inputs": [
            {"name": "billId", "type": "uint256", "indexed": True},
            {"name": "owner", "type": "address", "indexed": True},
            {"name": "token", "type": "address", "indexed": False},
            {"name": "amount", "type": "uint256", "indexed": False},
        ],
    },
    {
        "name": "BillsBound",
        "type": "event",
        "inputs": [
            {"name": "bindingId", "type": "uint256", "indexed": True},
            {"name": "buyerBillId", "type": "uint256", "indexed": False},
            {"name": "agentBillId", "type": "uint256", "indexed": False},
            {"name": "scopeHash", "type": "bytes32", "indexed": False},
        ],
    },
]


def _to_bytes32(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        raw = value
    else:
        hex_str = value[2:] if value.startswith("0x") else value
        raw = bytes.fromhex(hex_str)
    if len(raw) != 32:
        raise ValueError(f"Expected 32-byte hash, got {len(raw)} bytes")
    return raw


def scope_hash_for_task(task_id: str, explicit: str | bytes | None = None) -> bytes:
    if explicit is not None and explicit != "":
        return _to_bytes32(explicit)
    return hashlib.sha256(task_id.encode("utf-8")).digest()


@dataclass
class ChainTxResult:
    tx_hash: str
    block_number: int
    status: str  # "confirmed" | "failed"
    gas_used: int
    quote_id: Optional[str] = None
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

    - lock_funds() validates allowlist / balance / allowance; optionally broadcasts lock()
    - bind_bills() pairs buyer + agent bills → binding_id
    - release_payment() calls settle(bindingId, proofHash) → FINALIZING
    - finalize_settle() burns bills / releases USDC after dispute window
    - refund_payment() → refundOnTimeout(binding) or unlock(bill)
    - open_dispute() → dispute(bindingId, evidenceHash)
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

    def _binding_id(self, task_contract: TaskContract | None) -> int | None:
        if task_contract is None:
            return None
        raw = getattr(task_contract, "onchain_binding_id", None)
        return int(raw) if raw is not None else None

    # ------------------------------------------------------------------
    # Public adapter methods
    # ------------------------------------------------------------------

    def lock_funds(self, task_contract: TaskContract) -> dict[str, Any]:
        """
        Validate bilateral pre-conditions (token allowlist, balance, allowance).
        When ``task_contract.onchain_do_lock`` is true, broadcasts lock() and
        returns the minted bill_id (also sets task_contract.onchain_buyer_bill_id
        when previously unset).

        SECURITY: the server hot wallet (TESTNET_PRIVATE_KEY) is only allowed
        to be the escrow payer when CHAIN_ALLOW_HOT_WALLET_PAYER=true (dev /
        testnet MVP). For production funds the payer must be the user signing
        client-side — a compromised backend must never control escrow capital.
        """
        if not settings.chain_allow_hot_wallet_payer:
            raise RuntimeError(
                "CHAIN_ALLOW_HOT_WALLET_PAYER=false: backend hot wallet may not lock "
                "escrow funds — funds must be locked by the user's own signature "
                "(client_only/external signing backend)"
            )
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
            bill_id = None
            try:
                logs = bilateral.events.BillMinted().process_receipt(
                    w3.eth.get_transaction_receipt(tx_result.tx_hash)
                )
                if logs:
                    bill_id = int(logs[0]["args"]["billId"])
            except Exception as exc:  # pragma: no cover - best-effort parse
                logger.warning("bill_minted_parse_failed", error=str(exc))
            if bill_id is not None and getattr(task_contract, "onchain_buyer_bill_id", None) is None:
                task_contract.onchain_buyer_bill_id = bill_id
            result["status"] = "locked"
            result["tx_hash"] = tx_result.tx_hash
            result["bill_id"] = bill_id or getattr(task_contract, "onchain_buyer_bill_id", None)
            result["block_number"] = tx_result.block_number

        logger.info("lock_funds_ok", task_id=task_contract.task_id, amount=amount_wei)
        return result

    def bind_bills(
        self,
        task_contract: TaskContract,
        scope_hash: str | bytes | None = None,
    ) -> ChainTxResult:
        """Broadcast bind(buyerBillId, agentBillId, scopeHash); store binding on contract."""
        buyer_bill = getattr(task_contract, "onchain_buyer_bill_id", None)
        agent_bill = getattr(task_contract, "onchain_agent_bill_id", None)
        if buyer_bill is None or agent_bill is None:
            raise ValueError(
                "Cannot bind: task_contract.onchain_buyer_bill_id and "
                "onchain_agent_bill_id are required"
            )
        bilateral = self._get_bilateral()
        scope = scope_hash_for_task(
            task_contract.task_id,
            scope_hash or getattr(task_contract, "onchain_scope_hash", None),
        )
        tx = self._send_tx(
            bilateral.functions.bind(int(buyer_bill), int(agent_bill), scope)
        )
        binding_id = None
        try:
            w3 = self._get_web3()
            logs = bilateral.events.BillsBound().process_receipt(
                w3.eth.get_transaction_receipt(tx.tx_hash)
            )
            if logs:
                binding_id = int(logs[0]["args"]["bindingId"])
        except Exception as exc:  # pragma: no cover
            logger.warning("bills_bound_parse_failed", error=str(exc))
        if binding_id is None:
            raise RuntimeError("bind succeeded but BillsBound event not found")
        task_contract.onchain_binding_id = binding_id
        tx.binding_id = binding_id
        tx.quote_id = f"binding:{binding_id}"
        logger.info(
            "bilateral_bind_ok",
            task_id=task_contract.task_id,
            binding_id=binding_id,
            tx=tx.tx_hash,
        )
        return tx

    def submit_evidence_hash(self, task_id: str, bundle: EvidenceBundle) -> str:
        """Compute evidence bundle digest used as settle proofHash / dispute evidenceHash."""
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
        Call KarmaBilateral.settle(bindingId, proofHash) → FINALIZING.

        ``task_contract.onchain_binding_id`` must be set (bind already completed).
        Call finalize_settle() after the dispute window to release USDC.
        """
        if verification.decision != VerificationDecision.RELEASE:
            raise ValueError(f"Cannot release: decision is {verification.decision}")

        binding_id = self._binding_id(task_contract)
        if binding_id is None:
            raise ValueError(
                "Cannot settle: task_contract.onchain_binding_id is required for KarmaBilateral"
            )

        bilateral = self._get_bilateral()
        proof_hex = self.submit_evidence_hash(task_contract.task_id, bundle)
        proof_bytes = _to_bytes32(proof_hex)

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

    def finalize_settle(self, task_contract: TaskContract) -> ChainTxResult:
        """Call finalizeSettle(bindingId) after dispute window; burns bills / releases USDC."""
        binding_id = self._binding_id(task_contract)
        if binding_id is None:
            raise ValueError(
                "Cannot finalize: task_contract.onchain_binding_id is required"
            )
        bilateral = self._get_bilateral()
        result = self._send_tx(bilateral.functions.finalizeSettle(int(binding_id)))
        result.binding_id = int(binding_id)
        result.quote_id = f"binding:{binding_id}"
        logger.info(
            "bilateral_finalize_ok",
            task_id=task_contract.task_id,
            binding_id=binding_id,
            tx=result.tx_hash,
        )
        return result

    def refund_payment(
        self,
        task_id: str,
        verification: VerificationResult,
        task_contract: TaskContract | None = None,
    ) -> dict:
        """
        On-chain refund when handles are present:
          - binding_id → refundOnTimeout(bindingId)
          - else buyer bill only → unlock(billId)
        Otherwise returns offchain_only with guidance.
        """
        _ = verification
        binding_id = self._binding_id(task_contract)
        buyer_bill = (
            getattr(task_contract, "onchain_buyer_bill_id", None) if task_contract else None
        )

        if binding_id is None and buyer_bill is None:
            return {
                "status": "offchain_only",
                "action": "refund",
                "task_id": task_id,
                "note": (
                    "Set onchain_binding_id for refundOnTimeout, or onchain_buyer_bill_id "
                    "for unlock(MINTED)"
                ),
            }

        bilateral = self._get_bilateral()

        if binding_id is not None:
            tx = self._send_tx(bilateral.functions.refundOnTimeout(int(binding_id)))
            return {
                "status": "confirmed" if tx.status == "confirmed" else "failed",
                "action": "refundOnTimeout",
                "task_id": task_id,
                "binding_id": int(binding_id),
                "tx_hash": tx.tx_hash,
                "block_number": tx.block_number,
                "gas_used": tx.gas_used,
            }

        tx = self._send_tx(bilateral.functions.unlock(int(buyer_bill)))
        return {
            "status": "confirmed" if tx.status == "confirmed" else "failed",
            "action": "unlock",
            "task_id": task_id,
            "bill_id": int(buyer_bill),
            "tx_hash": tx.tx_hash,
            "block_number": tx.block_number,
            "gas_used": tx.gas_used,
        }

    def open_dispute(
        self,
        task_id: str,
        bundle_hash: str,
        task_contract: TaskContract | None = None,
    ) -> dict:
        """On-chain dispute(bindingId, evidenceHash) when binding_id is present."""
        binding_id = self._binding_id(task_contract)
        if binding_id is None:
            return {
                "status": "offchain_only",
                "action": "dispute",
                "task_id": task_id,
                "bundle_hash": bundle_hash,
                "note": "Set task_contract.onchain_binding_id to call KarmaBilateral.dispute",
            }

        bilateral = self._get_bilateral()
        evidence = _to_bytes32(bundle_hash)
        tx = self._send_tx(bilateral.functions.dispute(int(binding_id), evidence))
        return {
            "status": "confirmed" if tx.status == "confirmed" else "failed",
            "action": "dispute",
            "task_id": task_id,
            "binding_id": int(binding_id),
            "bundle_hash": bundle_hash,
            "tx_hash": tx.tx_hash,
            "block_number": tx.block_number,
            "gas_used": tx.gas_used,
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

    def bind_bills(
        self,
        task_contract: TaskContract,
        scope_hash: str | bytes | None = None,
    ) -> Optional[ChainTxResult]:
        if not self.is_onchain():
            return None
        return self._chain().bind_bills(task_contract, scope_hash=scope_hash)

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

    def finalize_settle(self, task_contract: TaskContract) -> Optional[ChainTxResult]:
        if not self.is_onchain():
            return None
        return self._chain().finalize_settle(task_contract)

    def refund_payment(
        self,
        task_id: str,
        verification: VerificationResult,
        task_contract: TaskContract | None = None,
    ) -> dict:
        if not self.is_onchain():
            return {"status": "offchain"}
        return self._chain().refund_payment(task_id, verification, task_contract=task_contract)

    def open_dispute(
        self,
        task_id: str,
        bundle_hash: str,
        task_contract: TaskContract | None = None,
    ) -> dict:
        if not self.is_onchain():
            return {"status": "offchain"}
        return self._chain().open_dispute(task_id, bundle_hash, task_contract=task_contract)

    def get_onchain_status(self, tx_hash: str) -> Optional[OnchainStatus]:
        if not self.is_onchain() or not tx_hash:
            return None
        return self._chain().get_onchain_status(tx_hash)


settlement_router = SettlementRouter()
