"""
Tests for IncrementalMerkleAnchor
==================================

Tests the Merkle tree anchoring client with simulate=True
(no real Solana transaction needed). Covers:
- append_receipt / append_batch
- Merkle proof generation (local)
- Proof verification (local)
- Batch operations
- Edge cases
"""

import hashlib
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

# ── Helpers ─────────────────────────────────────────────────────────

def keccak256(data: bytes) -> bytes:
    return hashlib.sha3_256(data).digest()


def make_universal_receipt(
    task_id: bytes,
    receipt_id: str,
    scenario: str = "e-commerce-checkout",
    billing_state: str = "funded",
    cost: int = 1500,
):
    """Create a UniversalReceipt for testing."""
    from karma_solana.merkle_anchor import UniversalReceipt
    receipt_data = json.dumps({
        "id": receipt_id,
        "timestamp": 1716400000,
        "amount": cost,
    }, sort_keys=True).encode("utf-8")
    return UniversalReceipt(
        task_id=task_id,
        receipt_data=receipt_data,
        scenario=scenario,
        billing_state=billing_state,
        cost_accrued_usdc=cost,
    )


# ── Test Off-chain Merkle Tree ─────────────────────────────────────

class TestOffchainMerkleTree:
    """Tests for the internal _OffchainMerkleTree class."""

    def test_empty_tree_root(self):
        from karma_solana.merkle_anchor import _OffchainMerkleTree
        tree = _OffchainMerkleTree()
        assert tree.get_root() == bytes(32)
        assert tree.leaf_count == 0

    def test_single_leaf(self):
        from karma_solana.merkle_anchor import _OffchainMerkleTree
        tree = _OffchainMerkleTree()
        leaf = keccak256(b"receipt-1")
        tree.add_leaf(leaf)
        # Single leaf root = hash of leaf with itself (balanced tree)
        assert tree.leaf_count == 1
        root = tree.get_root()
        assert len(root) == 32
        assert root != bytes(32)  # Not empty

    def test_multiple_leaves_root_changes(self):
        from karma_solana.merkle_anchor import _OffchainMerkleTree
        tree = _OffchainMerkleTree()

        leaf1 = keccak256(b"receipt-1")
        leaf2 = keccak256(b"receipt-2")

        tree.add_leaves([leaf1, leaf2])
        root_with_2 = tree.get_root()

        leaf3 = keccak256(b"receipt-3")
        tree.add_leaf(leaf3)
        root_with_3 = tree.get_root()

        # Root should change when a third leaf is added
        assert root_with_2 != root_with_3

    def test_proof_generation_two_leaves(self):
        from karma_solana.merkle_anchor import _OffchainMerkleTree
        tree = _OffchainMerkleTree()

        leaf1 = keccak256(b"receipt-1")
        leaf2 = keccak256(b"receipt-2")
        tree.add_leaves([leaf1, leaf2])

        root = tree.get_root()

        # Proof for leaf 0
        proof0 = tree.get_proof(0)
        assert len(proof0) == 1  # One level deep
        assert proof0[0] == leaf2  # Sibling

        # Verify proof
        from karma_solana.merkle_anchor import _compute_merkle_root_from_proof
        computed0 = _compute_merkle_root_from_proof(leaf1, proof0, 0)
        assert computed0 == root

        # Proof for leaf 1
        proof1 = tree.get_proof(1)
        assert proof1[0] == leaf1
        computed1 = _compute_merkle_root_from_proof(leaf2, proof1, 1)
        assert computed1 == root

    def test_proof_generation_many_leaves(self):
        from karma_solana.merkle_anchor import _OffchainMerkleTree
        tree = _OffchainMerkleTree()

        leaves = [keccak256(f"receipt-{i}".encode()) for i in range(10)]
        tree.add_leaves(leaves)

        root = tree.get_root()

        # Verify every leaf
        for i, leaf in enumerate(leaves):
            proof = tree.get_proof(i)
            from karma_solana.merkle_anchor import _compute_merkle_root_from_proof
            computed = _compute_merkle_root_from_proof(leaf, proof, i)
            assert computed == root, f"Proof verification failed for leaf {i}"

    def test_proof_invalid_index(self):
        from karma_solana.merkle_anchor import _OffchainMerkleTree
        tree = _OffchainMerkleTree()
        tree.add_leaf(keccak256(b"receipt-1"))

        with pytest.raises(ValueError, match="out of range"):
            tree.get_proof(5)

    def test_lazy_recomputation(self):
        from karma_solana.merkle_anchor import _OffchainMerkleTree
        tree = _OffchainMerkleTree()

        leaf1 = keccak256(b"r1")
        leaf2 = keccak256(b"r2")
        tree.add_leaves([leaf1, leaf2])

        root1 = tree.get_root()
        root1_again = tree.get_root()
        assert root1 == root1_again  # Same root when not dirty

        leaf3 = keccak256(b"r3")
        tree.add_leaf(leaf3)
        root2 = tree.get_root()
        assert root2 != root1  # Root changed


# ── Test IncrementalMerkleAnchor (simulate=True) ───────────────────

class TestIncrementalMerkleAnchor:
    """Tests for IncrementalMerkleAnchor with simulate=True."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock AsyncClient."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def anchor(self, mock_client):
        """Create an IncrementalMerkleAnchor in simulate mode."""
        from karma_solana.merkle_anchor import IncrementalMerkleAnchor
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey

        kp = Keypair()
        return IncrementalMerkleAnchor(
            solana_client=mock_client,
            program_id="2nMJG572zrnQiRpBQf3N7DBEX6Ufiwz4NikxVTcgDMka",
            tree_address=Pubkey.unique(),
            payer_keypair=kp,
            simulate=True,
        )

    @pytest.mark.asyncio
    async def test_initialize(self, anchor):
        task_id = b"task-001\0\0\0\0\0\0\0\0"
        sig = await anchor.initialize(task_id)
        assert sig == "simulated"
        assert anchor.get_latest_root() is not None

    @pytest.mark.asyncio
    async def test_append_single_receipt(self, anchor):
        task_id = b"task-001\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipt = make_universal_receipt(task_id, "rec-001")
        result = await anchor.append_receipt(receipt)

        assert result.signature == "simulated"
        assert len(result.new_root) == 64  # Hex string, 32 bytes
        assert result.leaf_indices == [0]
        root = await anchor.get_latest_root()
        assert root is not None
        assert len(root) == 64

    @pytest.mark.asyncio
    async def test_append_batch(self, anchor):
        task_id = b"task-002\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipts = [
            make_universal_receipt(task_id, f"rec-{i:03d}", cost=500 * (i + 1))
            for i in range(5)
        ]
        result = await anchor.append_batch(receipts)

        assert result.signature == "simulated"
        assert result.leaf_indices == [0, 1, 2, 3, 4]

        # Verify tree has 5 leaves
        root = await anchor.get_latest_root()
        assert root != "00" * 32

    @pytest.mark.asyncio
    async def test_get_merkle_proof(self, anchor):
        task_id = b"task-003\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipts = [
            make_universal_receipt(task_id, f"rec-{i:03d}")
            for i in range(3)
        ]
        await anchor.append_batch(receipts)

        # Get proof for leaf 0
        proof = await anchor.get_merkle_proof(0)
        assert proof.leaf_index == 0
        assert proof.verified is True
        assert len(proof.proof_path) > 0
        assert len(proof.leaf_hash) == 32
        assert len(proof.root) == 32

        # Get proof for leaf 2
        proof2 = await anchor.get_merkle_proof(2)
        assert proof2.verified is True
        assert proof2.leaf_index == 2

    @pytest.mark.asyncio
    async def test_get_merkle_proof_out_of_range(self, anchor):
        task_id = b"task-004\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipts = [make_universal_receipt(task_id, "rec-001")]
        await anchor.append_batch(receipts)

        with pytest.raises(ValueError):
            await anchor.get_merkle_proof(10)

    @pytest.mark.asyncio
    async def test_proof_verification(self, anchor):
        task_id = b"task-005\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipts = [
            make_universal_receipt(task_id, f"rec-{i:03d}")
            for i in range(4)
        ]
        await anchor.append_batch(receipts)

        root = await anchor.get_latest_root()

        # Verify each leaf's proof
        for i in range(4):
            proof_obj = await anchor.get_merkle_proof(i)
            assert proof_obj.verified is True
            # Also verify against root
            from karma_solana.merkle_anchor import _compute_merkle_root_from_proof
            computed = _compute_merkle_root_from_proof(
                proof_obj.leaf_hash,
                proof_obj.proof_path,
                proof_obj.leaf_index,
            )
            assert computed.hex() == root

    @pytest.mark.asyncio
    async def test_tampered_proof_fails(self, anchor):
        task_id = b"task-006\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipts = [make_universal_receipt(task_id, f"rec-{i:03d}") for i in range(3)]
        await anchor.append_batch(receipts)

        proof = await anchor.get_merkle_proof(0)

        # Tamper with the proof
        tampered_proof = list(proof.proof_path)
        tampered_proof[0] = bytes(32)  # Replace with zeros

        from karma_solana.merkle_anchor import _verify_proof_locally
        result = _verify_proof_locally(
            proof.leaf_hash,
            tampered_proof,
            proof.root,
            proof.leaf_index,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_batch_raises(self, anchor):
        task_id = b"task-007\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        with pytest.raises(ValueError, match="At least one"):
            await anchor.append_batch([])

    @pytest.mark.asyncio
    async def test_leaf_hash_consistency(self, anchor):
        """Leaf hashes should be deterministic for the same receipt data."""
        task_id = b"task-008\0\0\0\0\0\0\0\0"

        r1 = make_universal_receipt(task_id, "rec-001")
        r2 = make_universal_receipt(task_id, "rec-001")  # Same data

        assert r1.leaf_hash() == r2.leaf_hash()

    @pytest.mark.asyncio
    async def test_root_history_tracking(self, anchor):
        """After multiple appends, root should change each time."""
        task_id = b"task-009\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        roots = []
        for batch_num in range(3):
            receipts = [
                make_universal_receipt(task_id, f"batch-{batch_num}-rec-{i}")
                for i in range(2)
            ]
            result = await anchor.append_batch(receipts)
            roots.append(result.new_root)

        # All roots should be different (different leaf sets)
        assert len(set(roots)) == 3

    @pytest.mark.asyncio
    async def test_verify_on_chain_simulated(self, anchor):
        task_id = b"task-010\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipts = [make_universal_receipt(task_id, "rec-001")]
        await anchor.append_batch(receipts)

        proof = await anchor.get_merkle_proof(0)

        # Verify on-chain (simulated) — should succeed
        verified = await anchor.verify_on_chain(
            proof.leaf_hash,
            proof.proof_path,
            proof.leaf_index,
        )
        assert verified is True

        # Tampered proof — should fail
        verified_bad = await anchor.verify_on_chain(
            proof.leaf_hash,
            [bytes(32)] * len(proof.proof_path),  # Fake proof
            proof.leaf_index,
        )
        assert verified_bad is False

    @pytest.mark.asyncio
    async def test_large_batch(self, anchor):
        """Test anchoring a large batch of receipts."""
        task_id = b"task-011\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipts = [
            make_universal_receipt(task_id, f"large-rec-{i:04d}")
            for i in range(100)
        ]
        result = await anchor.append_batch(receipts)
        assert result.leaf_indices[-1] == 99

        # Verify a sample of proofs
        for i in [0, 50, 99]:
            proof = await anchor.get_merkle_proof(i)
            assert proof.verified is True

    @pytest.mark.asyncio
    async def test_merkle_proof_validation(self, anchor):
        """MerkleProof.verify() should work standalone."""
        task_id = b"task-012\0\0\0\0\0\0\0\0"
        await anchor.initialize(task_id)

        receipts = [make_universal_receipt(task_id, "rec-001")]
        await anchor.append_batch(receipts)

        proof = await anchor.get_merkle_proof(0)

        # Standalone verify
        assert proof.verify() is True

        # Verify against expected root
        from karma_solana.merkle_anchor import MerkleProof
        root = proof.root
        assert proof.verify(expected_root=root) is True
        assert proof.verify(expected_root=bytes(32)) is False  # Wrong expected root


# ── Test metadata helpers ──────────────────────────────────────────

class TestMetadataHelpers:
    """Tests for utility functions."""

    def test_compute_leaf_hash(self):
        from karma_solana.merkle_anchor import compute_leaf_hash
        h1 = compute_leaf_hash(b"hello")
        h2 = compute_leaf_hash(b"hello")
        h3 = compute_leaf_hash(b"world")

        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 32

    def test_build_metadata_from_receipts(self):
        from karma_solana.merkle_anchor import build_metadata_from_receipts
        task_id = b"task-X\0\0\0\0\0\0\0\0\0\0"
        receipts = [
            make_universal_receipt(task_id, "r1", cost=100),
            make_universal_receipt(task_id, "r2", cost=200),
            make_universal_receipt(task_id, "r3", cost=300),
        ]

        metadata, leaves = build_metadata_from_receipts(receipts)
        assert metadata.receipt_count == 3
        assert metadata.cost_accrued_usdc == 600  # 100+200+300
        assert len(leaves) == 3
        assert all(len(l) == 32 for l in leaves)
