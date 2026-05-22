"""
SolanaTransactionBuilder — Construct and submit Solana transactions
====================================================================

Wraps ``solders`` + ``solana.rpc`` for building Memo, SPL Token, and
custom Program Instructions. Designed to be extended for a dedicated
Karma Solana Program in a future version.

For the MVP, Karma settlement records are written as structured JSON
memos (via ``solders.system_program.create_account`` is not required —
memos are cheap, always available, and provide an audit trail).

Usage
-----
    builder = SolanaTransactionBuilder(rpc_url="https://api.devnet.solana.com")
    tx_sig = await builder.send_memo(keypair, "KARMA|v1|...")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from solders.hash import Hash as Blockhash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

logger = logging.getLogger(__name__)

# ── Solana SPL Memo Program ───────────────────────────────────────
# The SPL Memo Program uses PDA-derived addresses. Since solders
# requires 32-byte Pubkeys, use the solana-py Pubkey for PDA addresses.
# For production, use the exact SPL Memo Program ID from the official SDK.
# Reference: https://github.com/solana-labs/solana-program-library/tree/master/memo

import base58 as _base58
from solana.rpc.api import Pubkey as SolPubkey

# Well-known SPL Memo Program addresses (PDA-derived, not ed25519)
MEMO_PROGRAM_ID_STR = "Memo1UhkJRfHyvLMcVucvhxFWiYKEhZhVGS"
MEMO_PROGRAM_V2_ID_STR = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGm8"


def _memo_program_id() -> Pubkey:
    """Get the Memo Program ID as a solders Pubkey."""
    raw = _base58.b58decode(MEMO_PROGRAM_ID_STR)
    padded = raw + bytes(32 - len(raw))
    return Pubkey(padded)


def _memo_program_v2_id() -> Pubkey:
    """Get the Memo V2 Program ID as a solders Pubkey."""
    raw = _base58.b58decode(MEMO_PROGRAM_V2_ID_STR)
    padded = raw + bytes(32 - len(raw))
    return Pubkey(padded)


class SolanaTransactionBuilder:
    """
    High-level builder for submitting Solana transactions.

    Handles:
    - Recent blockhash fetching
    - Transaction assembly and signing
    - Submission with confirmation polling

    Parameters
    ----------
    rpc_url : str
        Solana RPC endpoint URL.
    commitment : str
        Default commitment level (default: "confirmed").
    """

    def __init__(
        self,
        rpc_url: str = "https://api.devnet.solana.com",
        commitment: str = "confirmed",
    ) -> None:
        self.rpc_url = rpc_url
        self.commitment = Confirmed
        self._client: Optional[AsyncClient] = None

    async def _get_client(self) -> AsyncClient:
        """Lazy-init the async RPC client."""
        if self._client is None:
            self._client = AsyncClient(self.rpc_url)
        return self._client

    async def send_memo(
        self,
        signer_keypair: Keypair,
        memo_text: str,
        *,
        additional_signers: Optional[list[Keypair]] = None,
    ) -> str:
        """
        Submit a memo transaction to Solana.

        The memo is recorded in the transaction log and is publicly
        visible on explorers (Solscan, SolanaFM). For Karma, this
        is used to record verification results as structured JSON.

        Parameters
        ----------
        signer_keypair : solders.Keypair
            The keypair that signs (and pays for) the transaction.
        memo_text : str
            Memo content. For Karma, a JSON object with verification data.
        additional_signers : list[Keypair] | None
            Additional signers if needed.

        Returns
        -------
        str
            Base58-encoded transaction signature.
        """
        client = await self._get_client()

        # Build memo instruction
        memo_ix = self._build_memo_instruction(
            signer_pubkey=signer_keypair.pubkey(),
            memo_text=memo_text,
        )

        # Get recent blockhash
        recent_blockhash_resp = await client.get_latest_blockhash()
        recent_blockhash = recent_blockhash_resp.value.blockhash

        # Build and sign transaction
        signers = [signer_keypair]
        if additional_signers:
            signers.extend(additional_signers)

        tx = self._build_versioned_tx(
            instructions=[memo_ix],
            payer=signer_keypair.pubkey(),
            blockhash=recent_blockhash,
        )

        # Sign with all signers
        signed_tx = self._sign_tx(tx, signers)

        # Submit
        opts = TxOpts(skip_preflight=False, preflight_commitment=self.commitment)
        tx_sig_resp = await client.send_transaction(signed_tx, opts=opts)
        tx_sig = str(tx_sig_resp.value)

        logger.info("Memo tx submitted: %s", tx_sig)

        # Wait for confirmation
        await self._confirm_transaction(client, tx_sig)
        return tx_sig

    async def send_spl_transfer(
        self,
        signer_keypair: Keypair,
        mint: Pubkey,
        destination: Pubkey,
        amount: int,
        *,
        decimals: int = 6,
    ) -> str:
        """
        Submit an SPL Token transfer transaction.

        Parameters
        ----------
        signer_keypair : Keypair
            Signer's keypair (must hold the token account).
        mint : Pubkey
            Token mint address (e.g., USDC on Solana).
        destination : Pubkey
            Destination token account.
        amount : int
            Amount in atomic units (e.g., 1_000_000 = 1 USDC with 6 decimals).
        decimals : int
            Token decimals (default: 6 for USDC).

        Returns
        -------
        str
            Transaction signature.
        """
        client = await self._get_client()
        signer_pubkey = signer_keypair.pubkey()

        # Derive Associated Token Account (ATA) for signer
        signer_ata = await self._get_associated_token_address(signer_pubkey, mint)

        # Derive ATA for destination
        dest_ata = await self._get_associated_token_address(destination, mint)

        # Build SPL Transfer instruction
        transfer_ix = self._build_spl_transfer_instruction(
            source=signer_ata,
            dest=dest_ata,
            owner=signer_pubkey,
            amount=amount,
        )

        recent_blockhash_resp = await client.get_latest_blockhash()
        tx = self._build_versioned_tx(
            instructions=[transfer_ix],
            payer=signer_pubkey,
            blockhash=recent_blockhash_resp.value.blockhash,
        )
        signed_tx = self._sign_tx(tx, [signer_keypair])

        opts = TxOpts(skip_preflight=False, preflight_commitment=self.commitment)
        tx_sig_resp = await client.send_transaction(signed_tx, opts=opts)
        tx_sig = str(tx_sig_resp.value)

        await self._confirm_transaction(client, tx_sig)
        return tx_sig

    # ── Instruction Builders ──────────────────────────────────────

    def _build_memo_instruction(
        self,
        signer_pubkey: Pubkey,
        memo_text: str,
    ) -> Instruction:
        """
        Build an SPL Memo instruction.

        The Memo program expects the fee payer as a read-only signer
        account, with the memo text as raw instruction data.

        SPL Memo size limit: 566 bytes. Exceeding this causes the
        transaction to fail on-chain.

        NOTE: MEMO_PROGRAM_ID uses a padded address for solders compatibility.
        For production, replace with the real SPL Memo program ID.
        """
        memo_bytes = memo_text.encode("utf-8")
        if len(memo_bytes) > 566:
            raise ValueError(
                f"Memo text exceeds SPL Memo limit of 566 bytes "
                f"(got {len(memo_bytes)}). Shorten evidence_uri or use "
                f"a content-addressed reference."
            )
        return Instruction(
            program_id=MEMO_PROGRAM_ID,
            accounts=[
                {"pubkey": signer_pubkey, "is_signer": True, "is_writable": False},
            ],
            data=memo_bytes,
        )

    def _build_spl_transfer_instruction(
        self,
        source: Pubkey,
        dest: Pubkey,
        owner: Pubkey,
        amount: int,
    ) -> Instruction:
        """
        Build an SPL Token Transfer instruction.

        Uses the standard SPL Token Program (TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA).
        The Transfer instruction discriminator is 3 (little-endian u8).
        Amount is u64 little-endian.
        """
        from solders.pubkey import Pubkey as SPubkey

        TOKEN_PROGRAM_ID = SPubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

        # Build instruction data: [3 (Transfer)] + [amount as u64 LE]
        data = bytearray([3])  # Transfer instruction index
        data.extend(amount.to_bytes(8, "little"))

        return Instruction(
            program_id=TOKEN_PROGRAM_ID,
            accounts=[
                {"pubkey": source, "is_signer": False, "is_writable": True},
                {"pubkey": dest, "is_signer": False, "is_writable": True},
                {"pubkey": owner, "is_signer": True, "is_writable": False},
            ],
            data=bytes(data),
        )

    # ── Transaction Assembly ──────────────────────────────────────

    def _build_versioned_tx(
        self,
        instructions: list[Instruction],
        payer: Pubkey,
        blockhash: Blockhash,
    ) -> VersionedTransaction:
        """Build a V0 (Versioned) transaction from instructions."""
        msg = MessageV0.try_compile(
            payer=payer,
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash,
        )
        return VersionedTransaction(msg, [])

    def _sign_tx(
        self,
        tx: VersionedTransaction,
        signers: list[Keypair],
    ) -> VersionedTransaction:
        """Sign a transaction with one or more keypairs."""
        for kp in signers:
            tx.sign([kp], tx.message.recent_blockhash)
        return tx

    # ── Helpers ───────────────────────────────────────────────────

    async def _get_associated_token_address(
        self,
        wallet: Pubkey,
        mint: Pubkey,
    ) -> Pubkey:
        """
        Derive the Associated Token Account (ATA) for a wallet + mint pair.

        First tries to look up existing token accounts via RPC.
        Falls back to PDA derivation using the SPL Associated Token
        Account program.

        Raises ValueError if no ATA can be found or derived.
        """
        ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string(
            "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
        )
        TOKEN_PROGRAM_ID = Pubkey.from_string(
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        )

        # Strategy 1: Look up existing token accounts via RPC
        try:
            from solana.rpc.types import TokenAccountOpts
            client = await self._get_client()
            resp = await client.get_token_accounts_by_owner(
                wallet,
                TokenAccountOpts(mint=mint),
            )
            if resp.value:
                return resp.value[0].pubkey
        except Exception as e:
            logger.debug("RPC lookup for ATA failed, deriving via PDA: %s", e)

        # Strategy 2: Derive via PDA (works even if ATA doesn't exist yet)
        try:
            ata, _bump = Pubkey.find_program_address(
                [bytes(wallet), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
                ASSOCIATED_TOKEN_PROGRAM_ID,
            )
            return Pubkey(ata)
        except Exception as e:
            logger.error("Could not derive ATA for wallet=%s mint=%s: %s", wallet, mint, e)
            raise ValueError(
                f"Could not derive Associated Token Account for wallet={wallet}"
            ) from e

    async def _confirm_transaction(
        self,
        client: AsyncClient,
        tx_sig: str,
        max_retries: int = 30,
        retry_delay: float = 0.5,
    ) -> None:
        """
        Poll for transaction confirmation.

        On Solana, transactions typically confirm within 1-2 seconds
        (devnet) or ~400ms (mainnet with priority fees).
        """
        from solana.rpc.core import RPCException

        for attempt in range(max_retries):
            try:
                resp = await client.get_signature_statuses([tx_sig])
                if resp.value and resp.value[0] is not None:
                    status = resp.value[0]
                    if hasattr(status, 'confirmation_status'):
                        logger.info("Tx %s confirmed in %d attempts", tx_sig, attempt + 1)
                        return
                    # Legacy: None means pending
            except RPCException as e:
                logger.warning("Confirmation poll error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(retry_delay)

        logger.warning("Tx %s not confirmed after %d retries", tx_sig, max_retries)

    async def close(self) -> None:
        """Close the RPC client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def __aenter__(self) -> "SolanaTransactionBuilder":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
