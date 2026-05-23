"""
IncrementalMerkleAnchor — Solana Merkle Tree Anchoring Client
===============================================================

Python client for the Karma Anchor Program on Solana.
Provides typed interfaces for anchoring verifiable execution receipts
into a Merkle tree on Solana via the karma_anchor program.

Usage
-----
    from karma_solana.merkle_anchor import IncrementalMerkleAnchor, AnchorResult

    anchor = IncrementalMerkleAnchor(
        solana_client=client,
        program_id="2nMJG572zrnQiRpBQf3N7DBEX6Ufiwz4NikxVTcgDMka",
        tree_address=tree_pubkey,
        payer_keypair=keypair,
    )

    result = await anchor.append_receipt(receipt)
    proof = await anchor.get_merkle_proof(leaf_index=0)
"""

from __future__ import annotations

import hashlib
import logging
import struct
from dataclasses import dataclass, field
from typing import Optional, Any

try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.instruction import Instruction, AccountMeta
    from solders.hash import Hash as Blockhash
    from solders.message import MessageV0
    from solders.transaction import VersionedTransaction
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Confirmed
    from solana.rpc.types import TxOpts
    _SOLANA_AVAILABLE = True
except ImportError:
    _SOLANA_AVAILABLE = False
    Keypair = None  # type: ignore
    Pubkey = None  # type: ignore
    Instruction = None  # type: ignore
    AccountMeta = None  # type: ignore
    Blockhash = None  # type: ignore
    MessageV0 = None  # type: ignore
    VersionedTransaction = None  # type: ignore
    AsyncClient = None  # type: ignore
    Confirmed = None  # type: ignore
    TxOpts = None  # type: ignore

logger = logging.getLogger(__name__)


# ── Data Classes ───────────────────────────────────────────────────

@dataclass
class UniversalReceipt:
    """A universal Karma receipt before anchoring."""
    task_id: bytes       # 16 bytes (UUID)
    receipt_data: bytes  # Raw receipt data to be hashed as a leaf
    scenario: str        # e.g., "e-commerce-checkout"
    billing_state: str   # e.g., "funded"
    cost_accrued_usdc: int = 0  # scaled by 100 (e.g., 1500 = $15.00)

    def leaf_hash(self) -> bytes:
        """Compute the Keccak256 leaf hash for this receipt."""
        return _keccak256(self.receipt_data)


@dataclass
class AnchorResult:
    """Result of an anchoring operation."""
    signature: str
    new_root: str       # hex-encoded 32-byte root
    leaf_indices: list[int]
    block_slot: int
    timestamp: int = 0     # unix timestamp from event
    task_id: str = ""       # task_id from event


@dataclass
class MerkleProof:
    """A Merkle proof for a single leaf in the tree."""
    leaf_hash: bytes
    proof_path: list[bytes]  # Sibling hashes from leaf to root
    root: bytes
    leaf_index: int
    verified: bool = False

    def verify(self, expected_root: Optional[bytes] = None) -> bool:
        """Verify the proof locally, optionally against an expected root."""
        computed = _compute_merkle_root_from_proof(
            self.leaf_hash, self.proof_path, self.leaf_index
        )
        self.verified = (computed == self.root)
        if expected_root is not None:
            self.verified = self.verified and (computed == expected_root)
        return self.verified


@dataclass
class KarmaAnchorMetadata:
    """Metadata for an anchoring transaction."""
    task_id: bytes       # [u8; 16]
    scenario: bytes      # [u8; 32] — padded scenario name
    billing_state: bytes # [u8; 16] — padded billing state
    receipt_count: int   # u16
    cost_accrued_usdc: int  # u32


# ── IncrementalMerkleAnchor ────────────────────────────────────────

@dataclass
class _CachedTreeState:
    """Cached Merkle tree state to avoid RPC calls on every op."""
    task_id: bytes
    current_root: bytes
    leaf_count: int
    leaves: list[bytes] = field(default_factory=list)
    root_history: list[bytes] = field(default_factory=list)


class IncrementalMerkleAnchor:
    """
    Client for Karma's on-chain Merkle Tree via the Anchor program.

    Wraps the karma_anchor program instructions:
    - initialize_tree: Create a new tree PDA for a task
    - append_leaves: Append leaf hashes, update root
    - verify_receipt: Check a Merkle proof against on-chain root
    - get_root: Read current root
    - get_root_history: Read historical roots

    Parameters
    ----------
    solana_client : AsyncClient
        An initialized solana.rpc.async_api.AsyncClient.
    program_id : str
        Base58-encoded program ID for karma_anchor.
    tree_address : str | Pubkey
        The PDA address of the Merkle tree account.
    payer_keypair : Keypair
        Keypair that pays for transactions.
    commitment : str
        Default commitment level (default: "confirmed").
    simulate : bool
        If True, simulate transactions instead of submitting.
        Useful when the program hasn't been deployed.
    """

    # Anchor discriminator for karma_anchor instructions
    # These are the first 8 bytes of sha256("global:<instruction_name>")
    DISCRIMINATOR_INITIALIZE = bytes([
        0xaf, 0xaf, 0xa6, 0x9e, 0x3f, 0x74, 0x2d, 0x2a,  # sha256("global:initialize_tree")[:8]
    ])
    DISCRIMINATOR_APPEND = bytes([
        0xe0, 0xa1, 0x4b, 0x2d, 0x3a, 0x4d, 0xb6, 0x2e,  # sha256("global:append_leaves")[:8]
    ])
    DISCRIMINATOR_VERIFY = bytes([
        0x3a, 0x5d, 0x5d, 0x3c, 0xcf, 0x1c, 0x1e, 0x0c,  # sha256("global:verify_receipt")[:8]
    ])

    def __init__(
        self,
        solana_client: AsyncClient,
        program_id: str,
        tree_address: str | Pubkey,
        payer_keypair: Keypair,
        commitment: str = "confirmed",
        simulate: bool = False,
    ) -> None:
        if not _SOLANA_AVAILABLE:
            raise ImportError(
                "karma_solana.merkle_anchor requires solders and solana packages. "
                "Install with: pip install solders solana"
            )
        self._client = solana_client
        self._program_id = (
            Pubkey.from_string(program_id) if isinstance(program_id, str) else program_id
        )
        self._tree_address = (
            Pubkey.from_string(tree_address) if isinstance(tree_address, str) else tree_address
        )
        self._payer = payer_keypair
        self._commitment = Confirmed
        self._simulate = simulate

        # Local cache
        self._cache: Optional[_CachedTreeState] = None
        self._offchain_leaves: list[bytes] = []
        self._offchain_tree: _OffchainMerkleTree | None = None

    # ── Public API ─────────────────────────────────────────────────

    async def initialize(self, task_id: bytes) -> str:
        """
        Initialize a Merkle tree PDA for a task.

        Returns the transaction signature (or "simulated" if simulate=True).
        """
        if self._simulate:
            logger.info("[SIMULATE] initialize_tree task_id=%s", task_id.hex())
            self._cache = _CachedTreeState(
                task_id=task_id,
                current_root=_empty_root(),
                leaf_count=0,
            )
            self._offchain_tree = _OffchainMerkleTree()
            return "simulated"

        # Build the initialize_tree instruction
        ix = self._build_initialize_instruction(task_id)
        sig = await self._send_instruction(ix)
        
        self._cache = _CachedTreeState(
            task_id=task_id,
            current_root=_empty_root(),
            leaf_count=0,
        )
        self._offchain_tree = _OffchainMerkleTree()
        return sig

    async def append_receipt(self, receipt: UniversalReceipt) -> AnchorResult:
        """Append a single receipt's leaf hash to the tree."""
        return await self.append_batch([receipt])

    async def append_batch(self, receipts: list[UniversalReceipt]) -> AnchorResult:
        """
        Append multiple receipts to the Merkle tree in one transaction.

        Returns AnchorResult with signature, new root, and leaf indices.
        """
        if not receipts:
            raise ValueError("At least one receipt is required")

        # Compute leaf hashes
        leaves = [r.leaf_hash() for r in receipts]
        metadata = self._build_metadata(receipts)

        if self._simulate:
            return self._simulate_append(leaves, metadata)

        ix = self._build_append_instruction(leaves, metadata)
        sig = await self._send_instruction(ix)

        # Update local cache
        start_idx = self._offchain_tree.leaf_count if self._offchain_tree else 0
        for leaf in leaves:
            self._offchain_tree.add_leaf(leaf)

        new_root = self._offchain_tree.get_root()

        return AnchorResult(
            signature=sig,
            new_root=new_root.hex(),
            leaf_indices=list(range(start_idx, start_idx + len(leaves))),
            block_slot=0,  # Will be filled if we poll
            timestamp=0,
            task_id=receipts[0].task_id.hex() if receipts else "",
        )

    async def get_merkle_proof(self, leaf_index: int) -> MerkleProof:
        """
        Get the Merkle proof for a leaf at the given index.
        Computed locally from the off-chain tree; can be verified on-chain.
        """
        if self._offchain_tree is None or leaf_index >= self._offchain_tree.leaf_count:
            raise ValueError(
                f"Leaf index {leaf_index} out of range "
                f"(tree has {self._offchain_tree.leaf_count if self._offchain_tree else 0} leaves)"
            )

        leaf_hash = self._offchain_tree.leaves[leaf_index]
        proof_path = self._offchain_tree.get_proof(leaf_index)
        root = self._offchain_tree.get_root()

        proof = MerkleProof(
            leaf_hash=leaf_hash,
            proof_path=proof_path,
            root=root,
            leaf_index=leaf_index,
        )
        proof.verify()  # Local verification
        return proof

    async def verify_on_chain(
        self,
        leaf_hash: bytes,
        proof: list[bytes],
        leaf_index: int,
    ) -> bool:
        """
        Submit a verification request to the on-chain program.

        Returns True if the proof is valid, False otherwise.
        """
        if self._simulate:
            # Local verification
            root = self._offchain_tree.get_root() if self._offchain_tree else _empty_root()
            return _verify_proof_locally(leaf_hash, proof, root, leaf_index)

        ix = self._build_verify_instruction(leaf_hash, proof, leaf_index)
        try:
            await self._send_instruction(ix)
            return True
        except Exception as e:
            if "ProofVerificationFailed" in str(e):
                return False
            raise

    async def get_latest_root(self) -> str:
        """Get the current Merkle root as a hex string."""
        if self._offchain_tree:
            return self._offchain_tree.get_root().hex()
        if self._simulate:
            return _empty_root().hex()
        
        # On-chain read via get_root
        try:
            raw = await self._read_account_data()
            # current_root is at offset 8 + 16 (task_id) = 24
            root = raw[24:56]
            return root.hex()
        except Exception as e:
            logger.error("Failed to read on-chain root: %s", e)
            return ""

    async def get_root_history(self) -> list[str]:
        """Get historical roots from on-chain or cache."""
        if self._cache:
            return [r.hex() for r in self._cache.root_history]

        try:
            raw = await self._read_account_data()
            # After current_root (32 bytes) + leaf_count (8 bytes) = 40
            # Then root_history length prefix (4 bytes for Borsh Vec)
            hist_len = struct.unpack_from("<I", raw, 64)[0]
            roots = []
            offset = 68
            for _ in range(min(hist_len, 100)):
                roots.append(raw[offset:offset + 32].hex())
                offset += 32
            return roots
        except Exception as e:
            logger.error("Failed to read root history: %s", e)
            return []

    # ── Instruction Builders ───────────────────────────────────────

    def _build_initialize_instruction(self, task_id: bytes) -> Instruction:
        """Build the initialize_tree instruction."""
        # Data: discriminator + task_id (Borsh-serialized)
        data = bytearray(self.DISCRIMINATOR_INITIALIZE)
        data.extend(_borsh_serialize_fixed_bytes(task_id, 16))

        return Instruction(
            program_id=self._program_id,
            accounts=[
                AccountMeta(pubkey=self._tree_address, is_signer=False, is_writable=True),
                AccountMeta(pubkey=self._payer.pubkey(), is_signer=True, is_writable=True),
                AccountMeta(pubkey=_SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            ],
            data=bytes(data),
        )

    def _build_append_instruction(
        self,
        leaves: list[bytes],
        metadata: KarmaAnchorMetadata,
    ) -> Instruction:
        """Build the append_leaves instruction."""
        data = bytearray(self.DISCRIMINATOR_APPEND)

        # Borsh-serialize leaves: vec<[u8; 32]>
        data.extend(struct.pack("<I", len(leaves)))  # vec length (u32 LE)
        for leaf in leaves:
            data.extend(leaf)

        # Borsh-serialize metadata struct:
        # task_id: [u8; 16]
        data.extend(metadata.task_id)
        # scenario: [u8; 32]
        data.extend(metadata.scenario)
        # billing_state: [u8; 16]
        data.extend(metadata.billing_state)
        # receipt_count: u16
        data.extend(struct.pack("<H", metadata.receipt_count))
        # cost_accrued_usdc: u32
        data.extend(struct.pack("<I", metadata.cost_accrued_usdc))

        return Instruction(
            program_id=self._program_id,
            accounts=[
                AccountMeta(pubkey=self._tree_address, is_signer=False, is_writable=True),
                AccountMeta(pubkey=self._payer.pubkey(), is_signer=True, is_writable=True),
            ],
            data=bytes(data),
        )

    def _build_verify_instruction(
        self,
        leaf_hash: bytes,
        proof: list[bytes],
        leaf_index: int,
    ) -> Instruction:
        """Build the verify_receipt instruction."""
        data = bytearray(self.DISCRIMINATOR_VERIFY)

        # leaf_hash: [u8; 32]
        data.extend(leaf_hash)

        # proof: vec<[u8; 32]>
        data.extend(struct.pack("<I", len(proof)))
        for p in proof:
            data.extend(p)

        # leaf_index: u64
        data.extend(struct.pack("<Q", leaf_index))

        return Instruction(
            program_id=self._program_id,
            accounts=[
                AccountMeta(pubkey=self._tree_address, is_signer=False, is_writable=False),
            ],
            data=bytes(data),
        )

    # ── Internal Helpers ───────────────────────────────────────────

    def _build_metadata(self, receipts: list[UniversalReceipt]) -> KarmaAnchorMetadata:
        """Build metadata from a batch of receipts."""
        if not receipts:
            return KarmaAnchorMetadata(
                task_id=b"\x00" * 16,
                scenario=b"\x00" * 32,
                billing_state=b"\x00" * 16,
                receipt_count=0,
                cost_accrued_usdc=0,
            )

        r = receipts[0]
        task_id = r.task_id if len(r.task_id) == 16 else r.task_id[:16].ljust(16, b"\x00")
        scenario = r.scenario.encode("utf-8")[:32].ljust(32, b"\x00")
        billing_state = r.billing_state.encode("utf-8")[:16].ljust(16, b"\x00")
        total_cost = sum(rx.cost_accrued_usdc for rx in receipts) & 0xFFFFFFFF

        return KarmaAnchorMetadata(
            task_id=task_id,
            scenario=scenario,
            billing_state=billing_state,
            receipt_count=len(receipts),
            cost_accrued_usdc=total_cost,
        )

    def _simulate_append(
        self,
        leaves: list[bytes],
        metadata: KarmaAnchorMetadata,
    ) -> AnchorResult:
        """Simulate an append operation locally (off-chain)."""
        if self._offchain_tree is None:
            self._offchain_tree = _OffchainMerkleTree()

        start_idx = self._offchain_tree.leaf_count
        for leaf in leaves:
            self._offchain_tree.add_leaf(leaf)

        new_root = self._offchain_tree.get_root()

        logger.info(
            "[SIMULATE] append_leaves: %d leaves, new_root=%s, leaf_indices=%s",
            len(leaves),
            new_root.hex()[:16] + "...",
            list(range(start_idx, start_idx + len(leaves))),
        )

        return AnchorResult(
            signature="simulated",
            new_root=new_root.hex(),
            leaf_indices=list(range(start_idx, start_idx + len(leaves))),
            block_slot=0,
            timestamp=0,
            task_id=metadata.task_id.hex(),
        )

    async def _send_instruction(self, instruction: Instruction) -> str:
        """Sign and send a transaction with the given instruction."""
        # Get recent blockhash
        resp = await self._client.get_latest_blockhash()
        blockhash = resp.value.blockhash

        # Build V0 message
        msg = MessageV0.try_compile(
            payer=self._payer.pubkey(),
            instructions=[instruction],
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash,
        )

        # Sign
        tx = VersionedTransaction(msg, [self._payer])

        # Submit
        opts = TxOpts(skip_preflight=False, preflight_commitment=self._commitment)
        tx_resp = await self._client.send_transaction(tx, opts=opts)
        sig = str(tx_resp.value)

        logger.info("Transaction submitted: %s", sig)

        # Poll for confirmation
        await self._confirm_tx(sig)
        return sig

    async def _confirm_tx(self, sig: str, max_retries: int = 30) -> None:
        """Poll until the transaction is confirmed."""
        import asyncio
        for attempt in range(max_retries):
            resp = await self._client.get_signature_statuses([sig])
            if resp.value and resp.value[0] is not None:
                status = resp.value[0]
                if hasattr(status, "confirmation_status"):
                    logger.info("Tx confirmed in %d attempts", attempt + 1)
                    return
            await asyncio.sleep(0.5)
        logger.warning("Tx %s not confirmed after %d retries", sig)

    async def _read_account_data(self) -> bytes:
        """Read raw account data from the tree account."""
        resp = await self._client.get_account_info(self._tree_address)
        if resp.value is None:
            raise ValueError(f"Tree account {self._tree_address} not found")
        return resp.value.data


# ── Off-chain Merkle Tree ──────────────────────────────────────────

class _OffchainMerkleTree:
    """
    Pure-Python Merkle tree used for local proof generation and verification.
    Mirrors the on-chain tree structure.
    """

    def __init__(self):
        self.leaves: list[bytes] = []
        self._layers: list[list[bytes]] = []
        self._dirty = True
        self._root: bytes = _empty_root()

    @property
    def leaf_count(self) -> int:
        return len(self.leaves)

    def add_leaf(self, leaf: bytes) -> None:
        """Add a leaf and mark tree as dirty for lazy recomputation."""
        if len(leaf) != 32:
            raise ValueError(f"Leaf must be 32 bytes, got {len(leaf)}")
        self.leaves.append(leaf)
        self._dirty = True

    def add_leaves(self, leaves: list[bytes]) -> None:
        """Add multiple leaves at once."""
        for leaf in leaves:
            self.add_leaf(leaf)

    def get_root(self) -> bytes:
        """Return the current Merkle root (lazy computation)."""
        if self._dirty:
            self._recompute()
        return self._root

    def get_proof(self, leaf_index: int) -> list[bytes]:
        """Generate a Merkle proof for the leaf at the given index."""
        if self._dirty:
            self._recompute()

        if leaf_index >= len(self.leaves):
            raise ValueError(f"Leaf index {leaf_index} out of range")

        proof: list[bytes] = []
        idx = leaf_index

        for layer in self._layers[:-1]:  # All layers except root
            pair_idx = idx ^ 1  # XOR to get sibling index
            if pair_idx < len(layer):
                proof.append(layer[pair_idx])
            else:
                # Odd node — duplicate self
                proof.append(layer[idx])
            idx //= 2

        return proof

    def _recompute(self) -> None:
        """Rebuild the Merkle tree from leaves."""
        if not self.leaves:
            self._root = _empty_root()
            self._layers = [[]]
            self._dirty = False
            return

        self._layers = [list(self.leaves)]
        layer = list(self.leaves)

        while len(layer) > 1:
            next_layer: list[bytes] = []
            for i in range(0, len(layer), 2):
                left = layer[i]
                right = layer[i + 1] if i + 1 < len(layer) else layer[i]
                combined = left + right if left < right else right + left
                node_hash = _keccak256(combined)
                next_layer.append(node_hash)
            self._layers.append(next_layer)
            layer = next_layer

        self._root = layer[0]
        self._dirty = False


# ── Pure Functions ─────────────────────────────────────────────────

def _keccak256(data: bytes) -> bytes:
    """Compute Keccak256 hash of data."""
    return hashlib.sha3_256(data).digest()


def _empty_root() -> bytes:
    """Return the empty Merkle root (32 zero bytes)."""
    return bytes(32)


_SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111") if _SOLANA_AVAILABLE else None


def _borsh_serialize_fixed_bytes(data: bytes, expected_len: int) -> bytes:
    """Serialize fixed-size bytes in Borsh format (no length prefix)."""
    if len(data) != expected_len:
        data = data[:expected_len].ljust(expected_len, b"\x00")
    return data


def _compute_merkle_root_from_proof(
    leaf: bytes,
    proof: list[bytes],
    leaf_index: int,
) -> bytes:
    """Verify a Merkle proof, returning the computed root."""
    current = leaf
    idx = leaf_index
    for sibling in proof:
        if idx % 2 == 0:
            combined = current + sibling
        else:
            combined = sibling + current
        current = _keccak256(combined)
        idx //= 2
    return current


def _verify_proof_locally(
    leaf_hash: bytes,
    proof: list[bytes],
    root: bytes,
    leaf_index: int,
) -> bool:
    """Verify a Merkle proof locally."""
    computed = _compute_merkle_root_from_proof(leaf_hash, proof, leaf_index)
    return computed == root


# ── Utils ──────────────────────────────────────────────────────────

def compute_leaf_hash(receipt_data: bytes) -> bytes:
    """Compute the Keccak256 leaf hash for a receipt."""
    return _keccak256(receipt_data)


def build_metadata_from_receipts(
    receipts: list[UniversalReceipt],
) -> tuple[KarmaAnchorMetadata, list[bytes]]:
    """Convenience: build metadata and leaf hashes from receipts."""
    leaves = [r.leaf_hash() for r in receipts]
    metadata = KarmaAnchorMetadata(
        task_id=receipts[0].task_id[:16].ljust(16, b"\x00"),
        scenario=receipts[0].scenario.encode("utf-8")[:32].ljust(32, b"\x00"),
        billing_state=receipts[0].billing_state.encode("utf-8")[:16].ljust(16, b"\x00"),
        receipt_count=len(receipts),
        cost_accrued_usdc=sum(r.cost_accrued_usdc for r in receipts) & 0xFFFFFFFF,
    )
    return metadata, leaves
