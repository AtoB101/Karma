"""
Karma — Integration Test: Mock Testnet Full Flow
Simulates the complete testnet settlement flow without a real RPC connection.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.schemas import (
    EvidenceBundle, TaskContract, TaskStatus,
    VerificationDecision, VerificationResult, VerificationCheck,
)
from core.hooks.hook_layer import InMemoryReceiptStore, KarmaHookLayer
from core.evidence.bundle_builder import EvidenceBundleBuilder
from core.verification.engine import MockVerificationEngine
from services.chain.settlement_adapter import OnChainSettlementAdapter, SettlementRouter


# ---------------------------------------------------------------------------
# Mock Web3 factory
# ---------------------------------------------------------------------------

def make_mock_web3(tx_hash="0x" + "ab" * 32, block_number=99999, status=1):
    mock_w3 = MagicMock()
    mock_w3.eth.chain_id = 11155111
    mock_w3.is_connected.return_value = True
    mock_w3.to_checksum_address.side_effect = lambda x: x
    mock_w3.keccak.return_value = b"\xab" * 32
    mock_w3.eth.get_transaction_count.return_value = 5

    raw_tx = MagicMock()
    raw_tx.raw_transaction = b"\xff" * 100
    mock_w3.eth.send_raw_transaction.return_value = bytes.fromhex(tx_hash[2:])

    receipt = MagicMock()
    receipt.transactionHash.hex.return_value = tx_hash
    receipt.blockNumber = block_number
    receipt.gasUsed = 95000
    receipt.status = status
    mock_w3.eth.wait_for_transaction_receipt.return_value = receipt
    mock_w3.eth.get_transaction_receipt.return_value = receipt
    return mock_w3


def make_mock_account():
    acc = MagicMock()
    acc.address = "0xPayerAddress1234"
    signed = MagicMock()
    signed.v = 28
    signed.r = 9999
    signed.s = 8888
    signed.raw_transaction = b"\xee" * 100
    acc.sign_typed_data.return_value = signed
    acc.sign_transaction.return_value = signed
    return acc


def make_mock_engine():
    eng = MagicMock()
    eng.functions.paused.return_value.call.return_value = False
    eng.functions.tokenAllowed.return_value.call.return_value = True
    eng.functions.nonces.return_value.call.return_value = 2
    eng.functions.submitSettlement.return_value.build_transaction.return_value = {
        "from": "0xPayerAddress1234", "nonce": 5, "chainId": 11155111
    }
    return eng


def make_mock_erc20(balance=10000, allowance=10000):
    erc = MagicMock()
    erc.functions.balanceOf.return_value.call.return_value = balance
    erc.functions.allowance.return_value.call.return_value = allowance
    erc.functions.decimals.return_value.call.return_value = 6
    return erc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_testnet_full_flow():
    """
    Full flow with mocked Web3:
    receipts → bundle → verify → evidence_hash → release_payment (mocked)
    """
    TASK_ID   = "mock-testnet-task-001"
    TX_HASH   = "0x" + "cc" * 32
    AMOUNT    = 500

    # Agent execution
    store = InMemoryReceiptStore()
    hooks = KarmaHookLayer(agent_id="worker-testnet-001", receipt_store=store)

    async def mock_tool(data):
        await asyncio.sleep(0.01)
        return {"result": f"processed:{data}"}

    for i in range(1, 4):
        await hooks.run_tool(TASK_ID, f"tool.{i}", mock_tool, {"step": i})

    receipts = await store.list_by_task(TASK_ID)
    assert len(receipts) == 3

    # Build bundle
    contract = TaskContract(
        task_id=TASK_ID,
        client_agent_id="client-001",
        title="Mock Testnet Task",
        description="Integration test",
        expected_output_schema={},
        expected_step_count=3,
        escrow_amount=float(AMOUNT),
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )
    builder  = EvidenceBundleBuilder(receipt_store=store)
    bundle   = await builder.build(contract, {"results": "mock"})

    assert bundle.total_steps == 3
    assert bundle.successful_steps == 3

    # Verify
    verifier     = MockVerificationEngine()
    verification = await verifier.verify(bundle, contract)
    assert verification.decision == VerificationDecision.RELEASE

    # Evidence hash
    adapter     = OnChainSettlementAdapter()
    bundle_hash = adapter.submit_evidence_hash(TASK_ID, bundle)
    assert bundle_hash.startswith("0x")
    assert len(bundle_hash) == 66

    # On-chain release (mocked)
    mock_w3  = make_mock_web3(tx_hash=TX_HASH)
    mock_acc = make_mock_account()
    mock_eng = make_mock_engine()

    adapter._w3              = mock_w3
    adapter._account         = mock_acc
    adapter._engine_contract = mock_eng
    adapter._chain_id        = 11155111

    with patch("config.settings.settings.karma_engine_address", "0x" + "aa" * 20), \
         patch("config.settings.settings.erc20_token_address",  "0x" + "bb" * 20), \
         patch("config.settings.settings.payee_address",         "0x" + "cc" * 20), \
         patch("config.settings.settings.settlement_ttl_seconds", 3600):

        tx_result = adapter.release_payment(contract, verification, bundle, AMOUNT)

    assert tx_result.tx_hash == TX_HASH
    assert tx_result.block_number == 99999
    assert tx_result.status == "confirmed"
    assert tx_result.gas_used == 95000
    assert tx_result.quote_id is not None

    print(f"\n[ok] Mock testnet full flow complete")
    print(f"     tx_hash={tx_result.tx_hash}")
    print(f"     block={tx_result.block_number}")
    print(f"     bundle_hash={bundle_hash[:20]}...")


@pytest.mark.asyncio
async def test_mock_testnet_refund_flow():
    """Refund flow — no on-chain tx, status recorded off-chain."""
    from core.schemas import VerificationDecision, VerificationResult, VerificationCheck

    verification = VerificationResult(
        task_id="task-refund-001",
        bundle_id="bundle-refund-001",
        decision=VerificationDecision.REFUND,
        confidence=0.9,
        checks=[VerificationCheck(name="hash_integrity", passed=False)],
        notes="Refund: hash mismatch",
    )

    adapter = OnChainSettlementAdapter()
    result  = adapter.refund_payment("task-refund-001", verification)

    assert result["action"] == "refund"
    assert result["status"] == "offchain_only"
    # No mock_w3 needed — no chain call
    assert "submitSettlement" not in str(result)


@pytest.mark.asyncio
async def test_mock_testnet_dispute_flow():
    adapter = OnChainSettlementAdapter()
    result  = adapter.open_dispute("task-dispute-001", "0x" + "dd" * 32)
    assert result["action"] == "dispute"
    assert result["status"] == "offchain_only"


@pytest.mark.asyncio
async def test_router_offchain_mode_no_chain_calls():
    """In offchain mode, no Web3 calls should ever be made."""
    with patch("config.settings.settings.settlement_mode", "offchain"):
        router = SettlementRouter()
        contract = TaskContract(
            task_id="task-offchain-001",
            client_agent_id="c", title="T", description="D",
            expected_output_schema={}, expected_step_count=1,
            escrow_amount=10.0,
            deadline_at=datetime.utcnow() + timedelta(hours=1),
        )

        # All of these should return without touching Web3
        lock_result = router.lock_funds(contract)
        assert lock_result["status"] == "offchain"

        verification = VerificationResult(
            task_id="task-offchain-001", bundle_id="b",
            decision=VerificationDecision.RELEASE, confidence=1.0,
            checks=[], notes="",
        )
        bundle = EvidenceBundle(
            task_id="task-offchain-001", task_contract_hash="a"*64,
            receipt_ids=[], receipt_hashes=[], final_result_hash="b"*64,
            total_steps=0, successful_steps=0, failed_steps=0,
            total_duration_ms=0, settlement_status=TaskStatus.VERIFIED,
        )
        release_result = router.release_payment(contract, verification, bundle, 100)
        assert release_result is None  # offchain mode returns None


def test_get_onchain_status_with_mock():
    mock_w3 = make_mock_web3(tx_hash="0x" + "ff" * 32, block_number=54321)
    adapter = OnChainSettlementAdapter()
    adapter._w3 = mock_w3

    with patch("config.settings.settings.testnet_rpc_url", "http://mock"):
        status = adapter.get_onchain_status("0x" + "ff" * 32)

    assert status.confirmed
    assert status.block_number == 54321
