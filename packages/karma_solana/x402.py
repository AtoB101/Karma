"""
SolanaX402Hook — x402 Payment Integration for Solana
=====================================================

Implements the x402 (HTTP 402 Payment Required) protocol on Solana,
enabling Agent-to-Agent micropayments using SPL tokens (USDC, SOL).

The hook integrates with KarmaSolanaVerifier so that x402 payments
are automatically executed as part of the verify_and_settle pipeline.

x402 Protocol Summary
---------------------
1. Client Agent requests a resource → Server returns HTTP 402 with
   payment requirements (``PaymentRequiredAccept``)
2. Client Agent signs a ``PAYMENT-SIGNATURE`` header proving intent
3. Client resends the request with the signed payment header
4. Server verifies the signature and processes the SPL transfer

For Karma on Solana, this means:
- x402 payment is settled on-chain (SPL Token transfer)
- The payment proof is embedded in the Evidence Bundle
- The on-chain settlement record includes the payment link

Usage
-----
    hook = SolanaX402Hook(solana_rpc="https://api.devnet.solana.com")
    proof = await hook.execute_payment(
        signer_keypair=keypair,
        accept=payment_accept,
        task_id="task-001",
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SolanaPaymentProof:
    """
    Proof of an x402 payment executed on Solana.

    Equivalent to x402's ``PaymentProof`` but with Solana-specific
    fields (Solana transaction signature instead of EVM tx hash).

    Attributes
    ----------
    protocol : str
        Always "x402".
    network : str
        Solana network (e.g., "solana-mainnet", "solana-devnet").
    solana_tx_signature : str
        Base58 Solana transaction signature of the SPL transfer.
    amount : float
        Amount in human-readable units (e.g., 5.0 USDC).
    asset : str
        Asset ticker (e.g., "USDC", "SOL").
    pay_to : str
        Recipient's Solana address (Base58).
    payer : str
        Payer's Solana address (Base58).
    payment_signature_b64 : str
        Base64-encoded Ed25519 signature over the payment payload.
    timestamp : str
        ISO-8601 timestamp of payment execution.
    task_id : str | None
        Associated Karma task ID.
    """
    protocol: str = "x402"
    network: str = "solana-devnet"
    solana_tx_signature: str = ""
    amount: float = 0.0
    asset: str = "USDC"
    pay_to: str = ""
    payer: str = ""
    payment_signature_b64: str = ""
    timestamp: str = ""
    task_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "network": self.network,
            "solana_tx_signature": self.solana_tx_signature,
            "amount": self.amount,
            "asset": self.asset,
            "pay_to": self.pay_to,
            "payer": self.payer,
            "payment_signature_b64": self.payment_signature_b64,
            "timestamp": self.timestamp,
            "task_id": self.task_id,
        }


class SolanaX402Hook:
    """
    x402 HTTP 402 payment hook for Solana.

    Implements the full x402 flow:
    1. Parse the ``PaymentRequiredAccept`` object from a 402 response
    2. Build a signed payment payload (Ed25519)
    3. Execute the SPL token transfer on Solana
    4. Return a ``SolanaPaymentProof`` for the audit trail

    Parameters
    ----------
    solana_rpc : str
        Solana RPC endpoint.
    usdc_mint : str
        USDC mint address on Solana. Default is mainnet USDC.
    network : str
        Network identifier for payment proof metadata.
    """

    # USDC on Solana Mainnet
    USDC_MINT_MAINNET = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    # USDC on Solana Devnet
    USDC_MINT_DEVNET = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

    def __init__(
        self,
        solana_rpc: str = "https://api.devnet.solana.com",
        usdc_mint: Optional[str] = None,
        network: str = "solana-devnet",
    ) -> None:
        from solders.pubkey import Pubkey

        self.solana_rpc = solana_rpc
        self.network = network

        # Auto-detect USDC mint based on network
        if usdc_mint:
            self.usdc_mint = Pubkey.from_string(usdc_mint)
        elif "devnet" in solana_rpc:
            self.usdc_mint = Pubkey.from_string(self.USDC_MINT_DEVNET)
        else:
            self.usdc_mint = Pubkey.from_string(self.USDC_MINT_MAINNET)

    async def execute_payment(
        self,
        signer_keypair: Any,  # solders.Keypair
        accept: Any,  # PaymentRequiredAccept from x402 models
        task_id: str,
    ) -> SolanaPaymentProof:
        """
        Execute an x402 payment on Solana.

        Parameters
        ----------
        signer_keypair : solders.Keypair
            Payer's Solana keypair.
        accept : PaymentRequiredAccept
            Payment terms from the 402 response.
        task_id : str
            Karma task identifier for payment linking.

        Returns
        -------
        SolanaPaymentProof
        """
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey

        # ── Step 1: Parse payment details ──
        try:
            pay_to_pubkey = Pubkey.from_string(accept.pay_to)
        except Exception:
            raise ValueError(f"Invalid pay_to address: {accept.pay_to}")

        amount_usdc = accept.amount_usdc_float()
        if amount_usdc <= 0:
            raise ValueError(f"Invalid payment amount: {amount_usdc}")

        asset = accept.asset or "USDC"

        # ── Step 2: Build and sign payment payload ──
        payment_payload = self._build_payment_payload(
            payer=str(signer_keypair.pubkey()),
            pay_to=accept.pay_to,
            amount=amount_usdc,
            asset=asset,
            resource=accept.resource or "",
            task_id=task_id,
        )

        payment_sig_b64 = self._sign_payment_payload(
            keypair=signer_keypair,
            payload=payment_payload,
        )

        # ── Step 3: Execute SPL transfer on Solana ──
        from .transaction_builder import SolanaTransactionBuilder

        tx_builder = SolanaTransactionBuilder(rpc_url=self.solana_rpc)

        # Convert amount to atomic units (USDC has 6 decimals)
        # Use decimal math to avoid float precision loss
        from decimal import Decimal
        amount_atomic = int(Decimal(str(amount_usdc)) * Decimal(1_000_000))

        tx_sig = await tx_builder.send_spl_transfer(
            signer_keypair=signer_keypair,
            mint=self.usdc_mint,
            destination=pay_to_pubkey,
            amount=amount_atomic,
            decimals=6,
        )

        await tx_builder.close()

        # ── Step 4: Build proof ──
        proof = SolanaPaymentProof(
            protocol="x402",
            network=self.network,
            solana_tx_signature=tx_sig,
            amount=amount_usdc,
            asset=asset,
            pay_to=accept.pay_to,
            payer=str(signer_keypair.pubkey()),
            payment_signature_b64=payment_sig_b64,
            timestamp=datetime.now(timezone.utc).isoformat(),
            task_id=task_id,
        )

        logger.info(
            "x402 payment executed on Solana | task=%s | tx=%s | amount=%.2f %s",
            task_id, tx_sig, amount_usdc, asset,
        )
        return proof

    def _build_payment_payload(
        self,
        payer: str,
        pay_to: str,
        amount: float,
        asset: str,
        resource: str,
        task_id: str,
    ) -> dict[str, Any]:
        """Build the canonical x402 payment payload for signing."""
        return {
            "x402_version": 1,
            "network": self.network,
            "payer": payer,
            "pay_to": pay_to,
            "amount": str(amount),
            "asset": asset,
            "resource": resource,
            "task_id": task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _sign_payment_payload(
        self,
        keypair: Any,  # solders.Keypair
        payload: dict[str, Any],
    ) -> str:
        """
        Sign the payment payload with Ed25519.

        The signature is over the SHA-256 hash of the canonical JSON
        payload. Uses the Solana keypair (Ed25519) directly.
        """
        import base64

        from nacl.signing import SigningKey

        # Canonical JSON
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        message_hash = hashlib.sha256(canonical.encode()).digest()

        # Sign with Ed25519 (Solana's native curve)
        # keypair.secret() returns the 32-byte secret seed (not the full 64-byte keypair)
        secret_bytes = keypair.secret()
        signing_key = SigningKey(secret_bytes)
        signed = signing_key.sign(message_hash)

        # Return the signature portion (first 64 bytes of signed message)
        signature_bytes = signed.signature
        return base64.b64encode(signature_bytes).decode()

    def verify_payment_signature(
        self,
        proof: SolanaPaymentProof,
    ) -> bool:
        """
        Verify an x402 payment proof signature.

        Can be called by any party to independently verify that the
        payment was authorized by the claimed payer.
        """
        import base64

        from nacl.signing import VerifyKey
        from solders.pubkey import Pubkey

        # Reconstruct the payload that was signed
        payload = self._build_payment_payload(
            payer=proof.payer,
            pay_to=proof.pay_to,
            amount=proof.amount,
            asset=proof.asset,
            resource="",  # resource is optional
            task_id=proof.task_id or "",
        )
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        message_hash = hashlib.sha256(canonical.encode()).digest()

        # Recover the public key from the payer's address
        try:
            pubkey_bytes = bytes(Pubkey.from_string(proof.payer))
            verify_key = VerifyKey(pubkey_bytes)
            signature_bytes = base64.b64decode(proof.payment_signature_b64)
            verify_key.verify(message_hash, signature_bytes)
            return True
        except Exception as e:
            logger.warning("Payment signature verification failed: %s", e)
            return False
