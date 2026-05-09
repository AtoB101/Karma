"""
Tests — OnChainSettlementAdapter
Unit tests using mocked Web3 provider.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.schemas import (
    EvidenceBundle, TaskContract, TaskStatus,
    VerificationDecision, VerificationResult, VerificationCheck,
)
from services.chain.settlement_adapter import (
    OnChainSettlementAdapter, SettlementRouter, settlement_router,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_contract(task_id="test-task-001", amount=100.0) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        client_agent_id="client-001",
        worker_agent_id="worker-001",
        title="Test",
        description="Test",
        expected_output_schema={},
        expected_step_count=3,
        escrow_amount=amount,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )


def _make_bundle(task_id="test-task-001") -> EvidenceBundle:
    return EvidenceBundle(
        task_id=task_id,
        task_contract_hash="a" * 64,
        receipt_ids=["r1", "r2"],
        receipt_hashes=["h1", "h2"],
        final_result_hash="f" * 64,
        total_steps=2,
        successful_steps=2,
        failed_steps=0,
        total_duration_ms=300,
        settlement_status=TaskStatus.VERIFIED,
    )


def _make_verification(decision=VerificationDecision.RELEASE) -> VerificationResult:
    return VerificationResult(
        task_id="test-task-001",
        bundle_id="bundle-001",
        decision=decision,
        confidence=0.95,
        checks=[VerificationCheck(name="test", passed=True)],
        notes="Unit test",
    )


# ---------------------------------------------------------------------------
# Evidence hash tests
# ---------------------------------------------------------------------------

def test_submit_evidence_hash_is_deterministic():
    adapter = OnChainSettlementAdapter()
    bundle  = _make_bundle()
    h1 = adapter.submit_evidence_hash("task-001", bundle)
    h2 = adapter.submit_evidence_hash("task-001", bundle)
    assert h1 == h2
    assert h1.startswith("0x")
    assert len(h1) == 66  # 0x + 64 hex chars


def test_submit_evidence_hash_differs_by_bundle():
    adapter  = OnChainSettlementAdapter()
    bundle1  = _make_bundle("task-001")
    bundle2  = _make_bundle("task-002")
    h1 = adapter.submit_evidence_hash("task-001", bundle1)
    h2 = adapter.submit_evidence_hash("task-002", bundle2)
    assert h1 != h2


# ---------------------------------------------------------------------------
# Refund / Dispute — off-chain only
# ---------------------------------------------------------------------------

def test_refund_returns_offchain_status():
    adapter      = OnChainSettlementAdapter()
    verification = _make_verification(VerificationDecision.REFUND)
    result       = adapter.refund_payment("task-001", verification)
    assert result["status"] == "offchain_only"
    assert result["action"] == "refund"


def test_dispute_returns_offchain_status():
    adapter = OnChainSettlementAdapter()
    result  = adapter.open_dispute("task-001", "0x" + "a" * 64)
    assert result["status"] == "offchain_only"
    assert result["action"] == "dispute"


# ---------------------------------------------------------------------------
# Release — transaction payload validation
# ---------------------------------------------------------------------------

def test_release_raises_if_decision_not_release():
    adapter      = OnChainSettlementAdapter()
    contract     = _make_contract()
    bundle       = _make_bundle()
    verification = _make_verification(VerificationDecision.REFUND)
    with pytest.raises(ValueError, match="Cannot release"):
        adapter.release_payment(contract, verification, bundle, 100)


@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_web3")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_account")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_engine")
def test_release_builds_correct_tx_payload(mock_engine_fn, mock_account_fn, mock_web3_fn):
    """Verify release_payment() calls submitSettlement() with correct structure."""
    from unittest.mock import MagicMock

    # Mock Web3
    mock_w3 = MagicMock()
    mock_w3.eth.chain_id = 11155111
    mock_w3.to_checksum_address.side_effect = lambda x: x
    mock_w3.keccak.return_value = b"\xab" * 32
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.send_raw_transaction.return_value = b"\xde\xad" * 16
    mock_receipt = MagicMock()
    mock_receipt.transactionHash.hex.return_value = "0x" + "de" * 32
    mock_receipt.blockNumber = 12345
    mock_receipt.gasUsed = 80000
    mock_receipt.status = 1
    mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt
    mock_web3_fn.return_value = mock_w3

    # Mock account
    mock_account = MagicMock()
    mock_account.address = "0x" + "aa" * 20
    signed_mock = MagicMock()
    signed_mock.v = 27
    signed_mock.r = 1234
    signed_mock.s = 5678
    signed_mock.raw_transaction = b"\xff" * 100
    mock_account.sign_typed_data.return_value = signed_mock
    mock_account.sign_transaction.return_value = signed_mock
    mock_account_fn.return_value = mock_account

    # Mock engine contract
    mock_engine = MagicMock()
    mock_engine.functions.paused.return_value.call.return_value = False
    mock_engine.functions.tokenAllowed.return_value.call.return_value = True
    mock_engine.functions.nonces.return_value.call.return_value = 0
    tx_mock = MagicMock()
    tx_mock.__getitem__ = lambda self, k: None
    mock_engine.functions.submitSettlement.return_value.build_transaction.return_value = {
        "from": "0x" + "aa" * 20, "nonce": 0, "chainId": 11155111
    }
    mock_engine_fn.return_value = mock_engine

    with patch("config.settings.settings.karma_engine_address", "0x" + "cc" * 20), \
         patch("config.settings.settings.erc20_token_address",  "0x" + "dd" * 20), \
         patch("config.settings.settings.payee_address",         "0x" + "ee" * 20), \
         patch("config.settings.settings.testnet_chain_id",      11155111):

        adapter      = OnChainSettlementAdapter()
        adapter._w3  = mock_w3
        adapter._account = mock_account
        adapter._engine_contract = mock_engine
        adapter._chain_id = 11155111

        contract     = _make_contract()
        bundle       = _make_bundle()
        verification = _make_verification(VerificationDecision.RELEASE)
        result       = adapter.release_payment(contract, verification, bundle, 100)

    assert result.tx_hash == "0x" + "de" * 32
    assert result.block_number == 12345
    assert result.status == "confirmed"
    assert mock_engine.functions.submitSettlement.called


# ---------------------------------------------------------------------------
# SettlementRouter mode switching
# ---------------------------------------------------------------------------

def test_router_offchain_mode_skips_chain():
    with patch("config.settings.settings.settlement_mode", "offchain"):
        router = SettlementRouter()
        assert not router.is_onchain()
        contract = _make_contract()
        result   = router.lock_funds(contract)
        assert result["status"] == "offchain"


def test_router_testnet_mode_is_onchain():
    with patch("config.settings.settings.settlement_mode", "testnet"):
        router = SettlementRouter()
        assert router.is_onchain()


def test_router_hybrid_mode_is_onchain():
    with patch("config.settings.settings.settlement_mode", "hybrid"):
        router = SettlementRouter()
        assert router.is_onchain()


def test_router_should_submit_onchain_only_on_release():
    with patch("config.settings.settings.settlement_mode", "testnet"):
        router = SettlementRouter()
        assert     router.should_submit_onchain(VerificationDecision.RELEASE)
        assert not router.should_submit_onchain(VerificationDecision.REFUND)
        assert not router.should_submit_onchain(VerificationDecision.DISPUTE)
        assert not router.should_submit_onchain(VerificationDecision.HOLD)


def test_router_offchain_never_submits():
    with patch("config.settings.settings.settlement_mode", "offchain"):
        router = SettlementRouter()
        assert not router.should_submit_onchain(VerificationDecision.RELEASE)


def test_router_release_returns_none_in_offchain():
    with patch("config.settings.settings.settlement_mode", "offchain"):
        router       = SettlementRouter()
        contract     = _make_contract()
        bundle       = _make_bundle()
        verification = _make_verification(VerificationDecision.RELEASE)
        result       = router.release_payment(contract, verification, bundle, 100)
        assert result is None
