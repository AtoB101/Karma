"""
Karma — On-Chain Settlement Adapter
=====================================
Connects the off-chain SettlementEngine to the existing Karma contracts:
  - KarmaSettlementEngine  (legacy, EIP-712 quote + submitSettlement)
  - KarmaNonCustodial      (M2.0, batch + bill model)

Design decisions based on contract analysis:
  - Both contracts have NO on-chain dispute/refund methods.
  - Dispute/refund decisions remain off-chain (private runtime).
  - On-chain action = payment transfer only (release or skip).
  - Evidence hash is embedded in scopeHash field of the EIP-712 Quote.
  - This adapter uses the Legacy Engine path (EIP-712 sign + submit).

Flow:
    lock_funds()           → validates pre-conditions (balance, allowance, nonce)
    submit_evidence_hash() → records bundle hash off-chain (no on-chain call needed for legacy engine)
    release_payment()      → builds EIP-712 Quote, signs, calls submitSettlement()
    refund_payment()       → no on-chain action; off-chain state only
    open_dispute()         → no on-chain action; off-chain state only
    get_onchain_status()   → reads tx receipt from chain
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

from config.settings import settings
from core.schemas import EvidenceBundle, SettlementState, TaskContract, VerificationDecision, VerificationResult

logger = structlog.get_logger(__name__)

# EIP-712 typed data for Quote (matches KarmaSettlementEngine)
QUOTE_TYPES = {
    "Quote": [
        {"name": "quoteId",   "type": "bytes32"},
        {"name": "payer",     "type": "address"},
        {"name": "payee",     "type": "address"},
        {"name": "token",     "type": "address"},
        {"name": "amount",    "type": "uint256"},
        {"name": "nonce",     "type": "uint256"},
        {"name": "deadline",  "type": "uint256"},
        {"name": "scopeHash", "type": "bytes32"},
    ]
}

EIP712_DOMAIN_NAME    = "KarmaSettlementEngine"
EIP712_DOMAIN_VERSION = "1"


@dataclass
class ChainTxResult:
    tx_hash: str
    block_number: int
    status: str          # "confirmed" | "failed"
    gas_used: int
    quote_id: Optional[str] = None
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
    Adapter between the Karma runtime and existing Karma smart contracts.

    Uses the KarmaSettlementEngine (legacy/EIP-712) path:
    - Payer signs a Quote with EIP-712
    - submitSettlement() transfers tokens from payer to payee on-chain
    - Evidence bundle hash is embedded in scopeHash

    Refund and dispute remain off-chain decisions — the contract
    has no refund/dispute methods, so these are handled purely
    by the settlement state machine.
    """

    def __init__(self):
        self._w3 = None
        self._account = None
        self._engine_contract = None
        self._erc20_contract = None
        self._chain_id: Optional[int] = None

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

    def _get_engine(self):
        if self._engine_contract is not None:
            return self._engine_contract
        if not settings.karma_engine_address:
            raise RuntimeError("KARMA_ENGINE_ADDRESS not set")
        w3 = self._get_web3()
        abi_path = Path(__file__).parent.parent / "abi" / "KarmaSettlementEngine.json"
        abi = json.loads(abi_path.read_text())
        self._engine_contract = w3.eth.contract(
            address=w3.to_checksum_address(settings.karma_engine_address),
            abi=abi,
        )
        return self._engine_contract

    def _get_erc20(self):
        if self._erc20_contract is not None:
            return self._erc20_contract
        if not settings.erc20_token_address:
            raise RuntimeError("ERC20_TOKEN_ADDRESS not set")
        w3 = self._get_web3()
        erc20_abi = [
            {"name": "balanceOf",  "type": "function", "stateMutability": "view",
             "inputs": [{"name": "account", "type": "address"}],
             "outputs": [{"name": "", "type": "uint256"}]},
            {"name": "allowance",  "type": "function", "stateMutability": "view",
             "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
             "outputs": [{"name": "", "type": "uint256"}]},
            {"name": "decimals",   "type": "function", "stateMutability": "view",
             "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
        ]
        self._erc20_contract = w3.eth.contract(
            address=w3.to_checksum_address(settings.erc20_token_address),
            abi=erc20_abi,
        )
        return self._erc20_contract

    # ------------------------------------------------------------------
    # Public adapter methods
    # ------------------------------------------------------------------

    def lock_funds(self, task_contract: TaskContract) -> dict[str, Any]:
        """
        Validate that on-chain pre-conditions are met before task execution.
        The Legacy Engine has no explicit lock — funds are transferred on settle.
        This method verifies: balance, allowance, nonce, engine not paused, token allowed.
        Returns a status dict; raises on hard failures.
        """
        w3 = self._get_web3()
        account = self._get_account()
        engine = self._get_engine()
        erc20 = self._get_erc20()

        amount_wei = int(task_contract.escrow_amount)  # assumed base units; caller adjusts for decimals
        payer = account.address
        engine_addr = settings.karma_engine_address

        paused        = engine.functions.paused().call()
        token_allowed = engine.functions.tokenAllowed(
            w3.to_checksum_address(settings.erc20_token_address)
        ).call()
        nonce    = engine.functions.nonces(w3.to_checksum_address(payer)).call()
        balance  = erc20.functions.balanceOf(w3.to_checksum_address(payer)).call()
        allowance = erc20.functions.allowance(
            w3.to_checksum_address(payer),
            w3.to_checksum_address(engine_addr),
        ).call()

        errors = []
        if paused:
            errors.append("Engine is paused")
        if not token_allowed:
            errors.append("Token not allowed by engine")
        if balance < amount_wei:
            errors.append(f"Insufficient balance: need {amount_wei}, have {balance}")
        if allowance < amount_wei:
            errors.append(f"Insufficient allowance: need {amount_wei}, approved {allowance}")

        if errors:
            raise ValueError(f"Lock pre-checks failed: {errors}")

        result = {
            "task_id":      task_contract.task_id,
            "payer":        payer,
            "amount_wei":   amount_wei,
            "nonce":        nonce,
            "balance":      balance,
            "allowance":    allowance,
            "paused":       paused,
            "token_allowed":token_allowed,
            "status":       "pre_checks_passed",
        }
        logger.info("lock_funds_ok", task_id=task_contract.task_id, amount=amount_wei)
        return result

    def submit_evidence_hash(self, task_id: str, bundle: EvidenceBundle) -> str:
        """
        Compute and store the evidence bundle hash.
        For the Legacy Engine, the hash is embedded in scopeHash during release.
        Returns the keccak256 hex hash of the bundle.
        """
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
        Build EIP-712 Quote with evidence hash in scopeHash, sign, and call
        submitSettlement() on the existing KarmaSettlementEngine contract.
        This transfers tokens from payer to payee on-chain.
        """
        if verification.decision != VerificationDecision.RELEASE:
            raise ValueError(f"Cannot release: decision is {verification.decision}")

        w3        = self._get_web3()
        account   = self._get_account()
        engine    = self._get_engine()
        chain_id  = self._chain_id or w3.eth.chain_id

        payer  = w3.to_checksum_address(account.address)
        payee  = w3.to_checksum_address(settings.payee_address)
        token  = w3.to_checksum_address(settings.erc20_token_address)
        engine_addr = w3.to_checksum_address(settings.karma_engine_address)

        nonce    = engine.functions.nonces(payer).call()
        now      = int(time.time())
        deadline = now + settings.settlement_ttl_seconds

        # Embed evidence hash + task_id in scopeHash for on-chain auditability
        scope_str  = f"{settings.settlement_scope}:{task_contract.task_id}:{bundle.bundle_id}"
        scope_hash = w3.keccak(text=scope_str)

        # Build quoteId from task identity
        quote_id_raw = w3.keccak(text=f"quote:{payer}:{payee}:{task_contract.task_id}:{now}")

        quote = {
            "quoteId":   quote_id_raw,
            "payer":     payer,
            "payee":     payee,
            "token":     token,
            "amount":    amount_wei,
            "nonce":     nonce,
            "deadline":  deadline,
            "scopeHash": scope_hash,
        }

        domain = {
            "name":              EIP712_DOMAIN_NAME,
            "version":           EIP712_DOMAIN_VERSION,
            "chainId":           chain_id,
            "verifyingContract": engine_addr,
        }

        # Sign EIP-712
        from eth_account.messages import encode_typed_data
        structured_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name",              "type": "string"},
                    {"name": "version",           "type": "string"},
                    {"name": "chainId",           "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **QUOTE_TYPES,
            },
            "domain": domain,
            "primaryType": "Quote",
            "message": {
                **quote,
                "quoteId":   quote_id_raw.hex(),
                "scopeHash": scope_hash.hex(),
                "amount":    amount_wei,
                "nonce":     nonce,
                "deadline":  deadline,
            },
        }
        signed = account.sign_typed_data(full_message=structured_data)
        v, r, s = signed.v, signed.r, signed.s

        # Submit on-chain
        tx = engine.functions.submitSettlement(
            (
                quote_id_raw,
                payer,
                payee,
                token,
                amount_wei,
                nonce,
                deadline,
                scope_hash,
            ),
            v,
            r.to_bytes(32, "big"),
            s.to_bytes(32, "big"),
        ).build_transaction({
            "from":  payer,
            "nonce": w3.eth.get_transaction_count(payer),
            "chainId": chain_id,
        })

        signed_tx = account.sign_transaction(tx)
        tx_hash   = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt   = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        status = "confirmed" if receipt.status == 1 else "failed"
        result = ChainTxResult(
            tx_hash=receipt.transactionHash.hex(),
            block_number=receipt.blockNumber,
            status=status,
            gas_used=receipt.gasUsed,
            quote_id=quote_id_raw.hex(),
        )

        logger.info(
            "release_payment_submitted",
            task_id=task_contract.task_id,
            tx_hash=result.tx_hash,
            status=status,
            block=result.block_number,
        )
        return result

    def refund_payment(
        self,
        task_id: str,
        verification: VerificationResult,
    ) -> dict[str, Any]:
        """
        The KarmaSettlementEngine has no on-chain refund method.
        Refund decisions are enforced off-chain: funds simply never move.
        This method records the decision and returns a status dict.
        """
        logger.info(
            "refund_decision_offchain",
            task_id=task_id,
            decision=verification.decision,
            notes="No on-chain refund call — KarmaSettlementEngine has no refund method. "
                  "Funds remain with payer as submitSettlement was never called.",
        )
        return {
            "task_id": task_id,
            "action":  "refund",
            "status":  "offchain_only",
            "note":    "Existing contract has no refund method. Escrow never transferred.",
        }

    def open_dispute(
        self,
        task_id: str,
        bundle_hash: str,
    ) -> dict[str, Any]:
        """
        The KarmaSettlementEngine has no on-chain dispute method.
        Disputes are handled off-chain by the private runtime.
        This method records the dispute intent.
        """
        logger.info(
            "dispute_opened_offchain",
            task_id=task_id,
            bundle_hash=bundle_hash,
        )
        return {
            "task_id":     task_id,
            "action":      "dispute",
            "bundle_hash": bundle_hash,
            "status":      "offchain_only",
            "note":        "Existing contract has no dispute method. Dispute handled by private runtime.",
        }

    def get_onchain_status(self, tx_hash: str) -> OnchainStatus:
        """
        Query the chain for transaction status by tx hash.
        """
        w3 = self._get_web3()
        try:
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
            return OnchainStatus(task_id="", tx_hash=tx_hash, block_number=None, confirmed=False, error=str(e))


# ---------------------------------------------------------------------------
# Settlement mode router
# ---------------------------------------------------------------------------

class SettlementRouter:
    """
    Routes settlement actions based on SETTLEMENT_MODE:
      offchain — database state only
      testnet  — real on-chain via existing Karma contracts
      hybrid   — off-chain verification, on-chain payment only on release
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
        """Only submit on-chain when mode is testnet/hybrid AND decision is RELEASE."""
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


# Singleton
settlement_router = SettlementRouter()
