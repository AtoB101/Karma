"""
Tests for KarmaSolanaVerifier — Core Solana Verification & Settlement.

Covers:
- Verifier initialization and configuration
- Evidence bundle hash computation (deterministic, cross-chain compatible)
- SolanaSettlementResult construction and serialization
- Off-chain verification flow (with mock HTTP)
- Error handling and edge cases
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure karma-solana and karma-core are importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "karma-solana"))

from core.schemas import (
    EvidenceBundle,
    ExecutionReceipt,
    TaskStatus,
    ToolStatus,
    VerificationDecision,
    VerificationResult,
)
from karma_solana.verifier import (
    KarmaSolanaVerifier,
    SolanaSettlementResult,
    SolanaSettlementStatus,
)
from karma_solana.evidence_store import MockUploader


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sample_receipts():
    """Create sample execution receipts for testing."""
    return [
        ExecutionReceipt(
            receipt_id="rcpt-test-0001",
            task_id="task-test-001",
            agent_id="agent-test-001",
            step_index=1,
            tool_name="solana.getBalance",
            input_hash="abc123input",
            output_hash="def456output",
            started_at="2026-05-22T10:00:00Z",
            ended_at="2026-05-22T10:00:01Z",
            duration_ms=1000,
            status=ToolStatus.SUCCESS,
        ),
        ExecutionReceipt(
            receipt_id="rcpt-test-0002",
            task_id="task-test-001",
            agent_id="agent-test-001",
            step_index=2,
            tool_name="solana.swap",
            input_hash="ghi789input",
            output_hash="jkl012output",
            started_at="2026-05-22T10:00:01Z",
            ended_at="2026-05-22T10:00:03Z",
            duration_ms=2000,
            status=ToolStatus.SUCCESS,
        ),
    ]


@pytest.fixture
def sample_bundle(sample_receipts):
    """Create a sample evidence bundle."""
    receipt_ids = [r.receipt_id for r in sample_receipts]
    receipt_hashes = []
    for r in sample_receipts:
        canonical = json.dumps(r.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        import hashlib
        receipt_hashes.append(hashlib.sha256(canonical.encode()).hexdigest())

    return EvidenceBundle(
        bundle_id="bundle-test-001",
        task_id="task-test-001",
        task_contract_hash="task_contract_hash_abc",
        receipt_ids=receipt_ids,
        receipt_hashes=receipt_hashes,
        final_result_hash="final_result_hash_xyz",
        total_steps=2,
        successful_steps=2,
        failed_steps=0,
        total_duration_ms=3000,
        agent_signature=None,
    )


@pytest.fixture
def verifier():
    """Create a KarmaSolanaVerifier with mock evidence store."""
    return KarmaSolanaVerifier(
        karma_endpoint="http://localhost:8000",
        api_key="karma_test_key",
        solana_rpc="https://api.devnet.solana.com",
        evidence_store=MockUploader(),
    )


# ── Tests: SolanaSettlementResult ─────────────────────────────────

class TestSolanaSettlementResult:
    """Tests for the SolanaSettlementResult dataclass."""

    def test_default_values(self):
        result = SolanaSettlementResult(
            task_id="task-001",
            status=SolanaSettlementStatus.ERROR,
        )
        assert result.task_id == "task-001"
        assert result.status == SolanaSettlementStatus.ERROR
        assert result.confidence == 0.0
        assert result.solana_tx_signature is None
        assert result.evidence_uri is None
        assert result.error_message is None

    def test_is_success_settled(self):
        result = SolanaSettlementResult(
            task_id="task-001",
            status=SolanaSettlementStatus.SETTLED,
        )
        assert result.is_success() is True

    def test_is_success_rejected(self):
        result = SolanaSettlementResult(
            task_id="task-001",
            status=SolanaSettlementStatus.REJECTED,
        )
        assert result.is_success() is False

    def test_to_dict_full(self):
        result = SolanaSettlementResult(
            task_id="task-001",
            status=SolanaSettlementStatus.SETTLED,
            verdict=VerificationDecision.RELEASE,
            confidence=0.95,
            solana_tx_signature="abc123base58",
            evidence_uri="ar://evidence-123",
            bundle_hash_on_chain="0xabcd1234",
        )
        d = result.to_dict()
        assert d["task_id"] == "task-001"
        assert d["status"] == "settled"
        assert d["verdict"] == "release"
        assert d["confidence"] == 0.95
        assert d["solana_tx_signature"] == "abc123base58"
        assert d["evidence_uri"] == "ar://evidence-123"
        assert d["bundle_hash_on_chain"] == "0xabcd1234"


# ── Tests: KarmaSolanaVerifier ────────────────────────────────────

class TestKarmaSolanaVerifier:
    """Tests for the core KarmaSolanaVerifier class."""

    def test_initialization(self):
        v = KarmaSolanaVerifier(
            karma_endpoint="http://localhost:8000",
            api_key="karma_key",
            solana_rpc="https://api.devnet.solana.com",
        )
        assert v.karma_endpoint == "http://localhost:8000"
        assert v._api_key == "karma_key"  # Private — stored securely
        assert v.solana_rpc == "https://api.devnet.solana.com"
        assert v.timeout == 30.0
        # Verify api_key is NOT exposed in repr
        assert "karma_key" not in repr(v)

    def test_initialization_custom_timeout(self):
        v = KarmaSolanaVerifier(
            karma_endpoint="http://localhost:8000",
            api_key="karma_key",
            solana_rpc="https://api.devnet.solana.com",
            timeout=10.0,
        )
        assert v.timeout == 10.0

    def test_initialization_strips_trailing_slash(self):
        v = KarmaSolanaVerifier(
            karma_endpoint="http://localhost:8000/",
            api_key="karma_key",
            solana_rpc="https://api.devnet.solana.com",
        )
        assert v.karma_endpoint == "http://localhost:8000"

    def test_initialization_with_evidence_store(self):
        store = MockUploader()
        v = KarmaSolanaVerifier(
            karma_endpoint="http://localhost:8000",
            api_key="karma_key",
            solana_rpc="https://api.devnet.solana.com",
            evidence_store=store,
        )
        assert v._evidence_store is store

    def test_compute_bundle_hash_deterministic(self, verifier, sample_bundle):
        """Bundle hash must be deterministic (same input → same output)."""
        h1 = verifier._compute_bundle_hash(sample_bundle)
        h2 = verifier._compute_bundle_hash(sample_bundle)
        assert h1 == h2

    def test_compute_bundle_hash_format(self, verifier, sample_bundle):
        """Bundle hash must be a hex string with 0x prefix."""
        h = verifier._compute_bundle_hash(sample_bundle)
        assert h.startswith("0x")
        assert len(h) == 66  # 0x + 64 hex chars
        # Verify it's valid hex
        int(h, 16)

    def test_compute_bundle_hash_different_bundles(self, verifier, sample_bundle):
        """Different bundles must produce different hashes."""
        h1 = verifier._compute_bundle_hash(sample_bundle)

        # Modify the bundle slightly
        bundle2 = sample_bundle.model_copy()
        bundle2.total_duration_ms = 9999
        h2 = verifier._compute_bundle_hash(bundle2)

        assert h1 != h2

    @pytest.mark.asyncio
    async def test_verify_only_mock_success(self, verifier, sample_bundle):
        """verify_only should return VerificationResult on successful mock response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verification_id": "vfy-test-001",
            "task_id": "task-test-001",
            "bundle_id": "bundle-test-001",
            "decision": "release",
            "confidence": 0.95,
            "checks": [
                {"name": "receipt_hash", "passed": True, "detail": "ok"},
            ],
            "notes": "All good",
        }

        with patch.object(verifier._http, "post", return_value=mock_response):
            result = await verifier.verify_only(
                task_id="task-test-001",
                evidence_bundle=sample_bundle,
            )

        assert result is not None
        assert result.decision == VerificationDecision.RELEASE
        assert result.confidence == 0.95
        assert result.task_id == "task-test-001"

    @pytest.mark.asyncio
    async def test_verify_only_http_error(self, verifier, sample_bundle):
        """verify_only should return None on HTTP error."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.text = "Bad Gateway"

        with patch.object(
            verifier._http, "post",
            side_effect=httpx.HTTPStatusError(
                "Bad Gateway",
                request=MagicMock(),
                response=mock_response,
            ),
        ):
            result = await verifier.verify_only(
                task_id="task-test-001",
                evidence_bundle=sample_bundle,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_verify_and_settle_dry_run(self, verifier, sample_bundle):
        """verify_and_settle with skip_on_chain should skip on-chain recording."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verification_id": "vfy-test-001",
            "task_id": "task-test-001",
            "bundle_id": "bundle-test-001",
            "decision": "release",
            "confidence": 0.95,
            "checks": [],
            "notes": "Test",
        }

        with patch.object(verifier._http, "post", return_value=mock_response):
            result = await verifier.verify_and_settle(
                task_id="task-test-001",
                evidence_bundle=sample_bundle,
                signer_keypair=None,  # Not needed for dry-run
                skip_on_chain=True,
            )

        assert result.status == SolanaSettlementStatus.SETTLED
        assert result.verdict == VerificationDecision.RELEASE
        assert result.confidence == 0.95
        assert result.solana_tx_signature is None  # Skipped on-chain
        assert result.evidence_uri is not None  # Mock upload happened

    @pytest.mark.asyncio
    async def test_verify_and_settle_reject(self, verifier, sample_bundle):
        """verify_and_settle should return REJECTED on REFUND verdict."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verification_id": "vfy-test-001",
            "task_id": "task-test-001",
            "bundle_id": "bundle-test-001",
            "decision": "refund",
            "confidence": 0.85,
            "checks": [],
            "notes": "Invalid receipt hash",
        }

        with patch.object(verifier._http, "post", return_value=mock_response):
            result = await verifier.verify_and_settle(
                task_id="task-test-001",
                evidence_bundle=sample_bundle,
                signer_keypair=None,
                skip_on_chain=True,
            )

        assert result.status == SolanaSettlementStatus.REJECTED
        assert result.verdict == VerificationDecision.REFUND

    @pytest.mark.asyncio
    async def test_verify_and_settle_hold(self, verifier, sample_bundle):
        """verify_and_settle should return PENDING_VERIFICATION on HOLD verdict."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verification_id": "vfy-test-001",
            "task_id": "task-test-001",
            "bundle_id": "bundle-test-001",
            "decision": "hold",
            "confidence": 0.5,
            "checks": [],
            "notes": "Needs manual review",
        }

        with patch.object(verifier._http, "post", return_value=mock_response):
            result = await verifier.verify_and_settle(
                task_id="task-test-001",
                evidence_bundle=sample_bundle,
                signer_keypair=None,
                skip_on_chain=True,
            )

        assert result.status == SolanaSettlementStatus.PENDING_VERIFICATION

    @pytest.mark.asyncio
    async def test_verify_and_settle_verification_none(self, verifier, sample_bundle):
        """verify_and_settle should handle None verification result gracefully."""
        with patch.object(verifier, "_verify_bundle", return_value=None):
            result = await verifier.verify_and_settle(
                task_id="task-test-001",
                evidence_bundle=sample_bundle,
                signer_keypair=None,
                skip_on_chain=True,
            )

        assert result.status == SolanaSettlementStatus.ERROR
        assert "no result" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_verify_and_settle_exception(self, verifier, sample_bundle):
        """verify_and_settle should catch and report unexpected exceptions."""
        with patch.object(
            verifier._http, "post",
            side_effect=RuntimeError("Unexpected crash"),
        ):
            result = await verifier.verify_and_settle(
                task_id="task-test-001",
                evidence_bundle=sample_bundle,
                signer_keypair=None,
                skip_on_chain=True,
            )

        assert result.status == SolanaSettlementStatus.ERROR
        assert "no result" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_context_manager(self, verifier):
        """Verifier should support async context manager."""
        async with verifier as v:
            assert v is verifier
        # After close, _http should be closed
        # (httpx.AsyncClient.aclose is a no-op if already closed)


# ── Tests: Evidence Store Integration ────────────────────────────

class TestEvidenceStoreIntegration:
    """Tests for evidence store integration with the verifier."""

    @pytest.mark.asyncio
    async def test_mock_uploader(self):
        store = MockUploader()
        bundle = EvidenceBundle(
            task_id="task-001",
            task_contract_hash="hash_abc",
            receipt_ids=["r1"],
            receipt_hashes=["h1"],
            final_result_hash="fr_h1",
            total_steps=1,
            successful_steps=1,
            failed_steps=0,
            total_duration_ms=1000,
        )
        uri = await store.upload(bundle)
        assert uri.startswith("mock://")

        retrieved = await store.retrieve(uri)
        assert retrieved is not None
        assert retrieved["task_id"] == "task-001"

    @pytest.mark.asyncio
    async def test_verifier_uses_evidence_store(self):
        """Verifier should call evidence_store.upload during verification."""
        store = MockUploader()
        v = KarmaSolanaVerifier(
            karma_endpoint="http://localhost:8000",
            api_key="karma_key",
            solana_rpc="https://api.devnet.solana.com",
            evidence_store=store,
        )

        bundle = EvidenceBundle(
            task_id="task-001",
            task_contract_hash="hash_abc",
            receipt_ids=["r1"],
            receipt_hashes=["h1"],
            final_result_hash="fr_h1",
            total_steps=1,
            successful_steps=1,
            failed_steps=0,
            total_duration_ms=1000,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verification_id": "vfy-test-001",
            "task_id": "task-001",
            "bundle_id": bundle.bundle_id,
            "decision": "release",
            "confidence": 0.95,
            "checks": [],
            "notes": "",
        }

        with patch.object(v._http, "post", return_value=mock_response):
            result = await v.verify_and_settle(
                task_id="task-001",
                evidence_bundle=bundle,
                signer_keypair=None,
                skip_on_chain=True,
            )

        assert result.evidence_uri is not None
        assert result.evidence_uri.startswith("mock://")

        # Verify it was stored
        retrieved = await store.retrieve(result.evidence_uri)
        assert retrieved is not None


# ── Tests: SolanaSettlementStatus Enum ───────────────────────────

class TestSolanaSettlementStatus:
    """Tests for the SolanaSettlementStatus enum."""

    def test_all_statuses_exist(self):
        assert SolanaSettlementStatus.SETTLED.value == "settled"
        assert SolanaSettlementStatus.PENDING_VERIFICATION.value == "pending_verification"
        assert SolanaSettlementStatus.REJECTED.value == "rejected"
        assert SolanaSettlementStatus.ERROR.value == "error"
