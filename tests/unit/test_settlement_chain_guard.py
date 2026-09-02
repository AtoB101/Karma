"""Unit tests for services.settlement_chain_guard (false-settlement fail-closed guard)."""
from __future__ import annotations

import pytest

from core.schemas import SettlementState, TaskStatus
from services.settlement_chain_guard import assert_settlement_chain_finality


def _state(**overrides) -> SettlementState:
    base = dict(
        task_id="task-001",
        escrow_amount=100.0,
        client_agent_id="buyer-001",
        status=TaskStatus.DELIVERED,
        settlement_mode="testnet",
        onchain_status=None,
        tx_hash=None,
    )
    base.update(overrides)
    return SettlementState(**base)


def test_offchain_mode_is_noop(monkeypatch):
    monkeypatch.setattr("config.settings.settings.settlement_mode", "offchain")
    state = _state(settlement_mode="offchain", onchain_status=None, tx_hash=None)
    # should not raise
    assert_settlement_chain_finality(state, TaskStatus.SETTLED)


def test_testnet_blocks_settled_without_finality(monkeypatch):
    monkeypatch.setattr("config.settings.settings.settlement_mode", "testnet")
    state = _state(settlement_mode="testnet", onchain_status=None, tx_hash=None)
    with pytest.raises(Exception) as exc:
        assert_settlement_chain_finality(state, TaskStatus.SETTLED)
    assert exc.value.status_code == 409


def test_testnet_allows_settled_with_finality(monkeypatch):
    monkeypatch.setattr("config.settings.settings.settlement_mode", "testnet")
    state = _state(settlement_mode="testnet", onchain_status="settled", tx_hash="0xabc")
    # should not raise
    assert_settlement_chain_finality(state, TaskStatus.SETTLED)


def test_testnet_blocks_refunded_without_finality(monkeypatch):
    monkeypatch.setattr("config.settings.settings.settlement_mode", "testnet")
    state = _state(settlement_mode="testnet", onchain_status=None, tx_hash=None)
    with pytest.raises(Exception) as exc:
        assert_settlement_chain_finality(state, TaskStatus.REFUNDED)
    assert exc.value.status_code == 409


def test_testnet_ignores_non_fund_terminal(monkeypatch):
    monkeypatch.setattr("config.settings.settings.settlement_mode", "testnet")
    state = _state(settlement_mode="testnet")
    # DISPUTED and CANCELLED are not fund-moving terminals → no-op
    assert_settlement_chain_finality(state, TaskStatus.DISPUTED)
    assert_settlement_chain_finality(state, TaskStatus.CANCELLED)


def test_hybrid_also_guarded(monkeypatch):
    monkeypatch.setattr("config.settings.settings.settlement_mode", "hybrid")
    state = _state(settlement_mode="hybrid", onchain_status=None, tx_hash=None)
    with pytest.raises(Exception) as exc:
        assert_settlement_chain_finality(state, TaskStatus.SETTLED)
    assert exc.value.status_code == 409
