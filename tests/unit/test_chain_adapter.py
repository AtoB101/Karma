"""
Tests — OnChainSettlementAdapter (KarmaBilateral)
Unit tests using mocked Web3 provider.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.schemas import (
    EvidenceBundle,
    TaskContract,
    TaskStatus,
    VerificationCheck,
    VerificationDecision,
    VerificationResult,
)
from services.chain.settlement_adapter import (
    OnChainSettlementAdapter,
    SettlementRouter,
)


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
        onchain_binding_id=7,
        onchain_buyer_bill_id=1,
        onchain_agent_bill_id=2,
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


def _wire_mock_tx(mock_bilateral, mock_w3, mock_account, fn_name: str):
    mock_w3.eth.chain_id = 11155111
    mock_w3.to_checksum_address.side_effect = lambda x: x
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.send_raw_transaction.return_value = b"\xde\xad" * 16
    mock_receipt = MagicMock()
    mock_receipt.transactionHash.hex.return_value = "0x" + "de" * 32
    mock_receipt.blockNumber = 12345
    mock_receipt.gasUsed = 80000
    mock_receipt.status = 1
    mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt
    mock_w3.eth.get_transaction_receipt.return_value = mock_receipt

    mock_account.address = "0x" + "aa" * 20
    signed_mock = MagicMock()
    signed_mock.raw_transaction = b"\xff" * 100
    mock_account.sign_transaction.return_value = signed_mock

    getattr(mock_bilateral.functions, fn_name).return_value.build_transaction.return_value = {
        "from": "0x" + "aa" * 20,
        "nonce": 0,
        "chainId": 11155111,
    }


def test_submit_evidence_hash_is_deterministic():
    adapter = OnChainSettlementAdapter()
    bundle = _make_bundle()
    h1 = adapter.submit_evidence_hash("task-001", bundle)
    h2 = adapter.submit_evidence_hash("task-001", bundle)
    assert h1 == h2
    assert h1.startswith("0x")
    assert len(h1) == 66


def test_submit_evidence_hash_differs_by_bundle():
    adapter = OnChainSettlementAdapter()
    bundle1 = _make_bundle("task-001")
    bundle2 = _make_bundle("task-002")
    h1 = adapter.submit_evidence_hash("task-001", bundle1)
    h2 = adapter.submit_evidence_hash("task-002", bundle2)
    assert h1 != h2


def test_refund_without_handles_is_offchain_only():
    adapter = OnChainSettlementAdapter()
    verification = _make_verification(VerificationDecision.REFUND)
    result = adapter.refund_payment("task-001", verification)
    assert result["status"] == "offchain_only"
    assert result["action"] == "refund"


def test_dispute_without_binding_is_offchain_only():
    adapter = OnChainSettlementAdapter()
    result = adapter.open_dispute("task-001", "0x" + "a" * 64)
    assert result["status"] == "offchain_only"
    assert result["action"] == "dispute"


def test_release_raises_if_decision_not_release():
    adapter = OnChainSettlementAdapter()
    contract = _make_contract()
    bundle = _make_bundle()
    verification = _make_verification(VerificationDecision.REFUND)
    with pytest.raises(ValueError, match="Cannot release"):
        adapter.release_payment(contract, verification, bundle, 100)


def test_release_requires_binding_id():
    adapter = OnChainSettlementAdapter()
    contract = _make_contract()
    contract.onchain_binding_id = None
    bundle = _make_bundle()
    verification = _make_verification(VerificationDecision.RELEASE)
    with pytest.raises(ValueError, match="onchain_binding_id"):
        adapter.release_payment(contract, verification, bundle, 100)


@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_web3")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_account")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_bilateral")
def test_release_calls_bilateral_settle(mock_bilateral_fn, mock_account_fn, mock_web3_fn):
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_bilateral = MagicMock()
    _wire_mock_tx(mock_bilateral, mock_w3, mock_account, "settle")
    mock_web3_fn.return_value = mock_w3
    mock_account_fn.return_value = mock_account
    mock_bilateral_fn.return_value = mock_bilateral

    with patch("config.settings.settings.karma_bilateral_address", "0x" + "cc" * 20), patch(
        "config.settings.settings.erc20_token_address", "0x" + "dd" * 20
    ), patch("config.settings.settings.testnet_chain_id", 11155111):
        adapter = OnChainSettlementAdapter()
        adapter._w3 = mock_w3
        adapter._account = mock_account
        adapter._bilateral_contract = mock_bilateral
        adapter._chain_id = 11155111

        contract = _make_contract()
        bundle = _make_bundle()
        verification = _make_verification(VerificationDecision.RELEASE)
        result = adapter.release_payment(contract, verification, bundle, 100)

    assert result.tx_hash == "0x" + "de" * 32
    assert result.block_number == 12345
    assert result.status == "confirmed"
    assert result.binding_id == 7
    assert mock_bilateral.functions.settle.called


@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_web3")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_account")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_bilateral")
def test_bind_bills_sets_binding_id(mock_bilateral_fn, mock_account_fn, mock_web3_fn):
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_bilateral = MagicMock()
    _wire_mock_tx(mock_bilateral, mock_w3, mock_account, "bind")
    mock_bilateral.events.BillsBound.return_value.process_receipt.return_value = [
        {"args": {"bindingId": 99, "buyerBillId": 1, "agentBillId": 2, "scopeHash": b"\x11" * 32}}
    ]
    mock_web3_fn.return_value = mock_w3
    mock_account_fn.return_value = mock_account
    mock_bilateral_fn.return_value = mock_bilateral

    adapter = OnChainSettlementAdapter()
    adapter._w3 = mock_w3
    adapter._account = mock_account
    adapter._bilateral_contract = mock_bilateral
    adapter._chain_id = 11155111

    contract = _make_contract()
    contract.onchain_binding_id = None
    tx = adapter.bind_bills(contract)
    assert tx.binding_id == 99
    assert contract.onchain_binding_id == 99
    assert mock_bilateral.functions.bind.called


@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_web3")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_account")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_bilateral")
def test_finalize_settle_calls_contract(mock_bilateral_fn, mock_account_fn, mock_web3_fn):
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_bilateral = MagicMock()
    _wire_mock_tx(mock_bilateral, mock_w3, mock_account, "finalizeSettle")
    mock_web3_fn.return_value = mock_w3
    mock_account_fn.return_value = mock_account
    mock_bilateral_fn.return_value = mock_bilateral

    adapter = OnChainSettlementAdapter()
    adapter._w3 = mock_w3
    adapter._account = mock_account
    adapter._bilateral_contract = mock_bilateral
    adapter._chain_id = 11155111

    tx = adapter.finalize_settle(_make_contract())
    assert tx.binding_id == 7
    assert mock_bilateral.functions.finalizeSettle.called


@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_web3")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_account")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_bilateral")
def test_refund_calls_refund_on_timeout(mock_bilateral_fn, mock_account_fn, mock_web3_fn):
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_bilateral = MagicMock()
    _wire_mock_tx(mock_bilateral, mock_w3, mock_account, "refundOnTimeout")
    mock_web3_fn.return_value = mock_w3
    mock_account_fn.return_value = mock_account
    mock_bilateral_fn.return_value = mock_bilateral

    adapter = OnChainSettlementAdapter()
    adapter._w3 = mock_w3
    adapter._account = mock_account
    adapter._bilateral_contract = mock_bilateral
    adapter._chain_id = 11155111

    result = adapter.refund_payment(
        "task-001",
        _make_verification(VerificationDecision.REFUND),
        task_contract=_make_contract(),
    )
    assert result["status"] == "confirmed"
    assert result["action"] == "refundOnTimeout"
    assert result["binding_id"] == 7
    assert mock_bilateral.functions.refundOnTimeout.called


@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_web3")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_account")
@patch("services.chain.settlement_adapter.OnChainSettlementAdapter._get_bilateral")
def test_dispute_calls_dispute_with_evidence(mock_bilateral_fn, mock_account_fn, mock_web3_fn):
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_bilateral = MagicMock()
    _wire_mock_tx(mock_bilateral, mock_w3, mock_account, "dispute")
    mock_web3_fn.return_value = mock_w3
    mock_account_fn.return_value = mock_account
    mock_bilateral_fn.return_value = mock_bilateral

    adapter = OnChainSettlementAdapter()
    adapter._w3 = mock_w3
    adapter._account = mock_account
    adapter._bilateral_contract = mock_bilateral
    adapter._chain_id = 11155111

    evidence = "0x" + "ab" * 32
    result = adapter.open_dispute("task-001", evidence, task_contract=_make_contract())
    assert result["status"] == "confirmed"
    assert result["action"] == "dispute"
    assert mock_bilateral.functions.dispute.called


def test_router_offchain_mode_skips_chain():
    with patch("config.settings.settings.settlement_mode", "offchain"):
        router = SettlementRouter()
        assert not router.is_onchain()
        contract = _make_contract()
        result = router.lock_funds(contract)
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
        assert router.should_submit_onchain(VerificationDecision.RELEASE)
        assert not router.should_submit_onchain(VerificationDecision.REFUND)
        assert not router.should_submit_onchain(VerificationDecision.DISPUTE)
        assert not router.should_submit_onchain(VerificationDecision.HOLD)


def test_router_offchain_never_submits():
    with patch("config.settings.settings.settlement_mode", "offchain"):
        router = SettlementRouter()
        assert not router.should_submit_onchain(VerificationDecision.RELEASE)


def test_router_release_returns_none_in_offchain():
    with patch("config.settings.settings.settlement_mode", "offchain"):
        router = SettlementRouter()
        contract = _make_contract()
        bundle = _make_bundle()
        verification = _make_verification(VerificationDecision.RELEASE)
        result = router.release_payment(contract, verification, bundle, 100)
        assert result is None


def test_abi_includes_finalize_dispute_refund():
    from services.chain.settlement_adapter import KARMA_BILATERAL_ABI

    names = {e["name"] for e in KARMA_BILATERAL_ABI if e.get("type") == "function"}
    assert {"finalizeSettle", "dispute", "refundOnTimeout", "bind", "settle", "unlock"} <= names
    dispute = next(e for e in KARMA_BILATERAL_ABI if e.get("name") == "dispute")
    assert [i["name"] for i in dispute["inputs"]] == ["bindingId", "evidenceHash"]
