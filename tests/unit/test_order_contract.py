"""Unit tests for order contract terms hashing and dual-party signatures."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eth_account import Account

from core.schemas import TaskContract
from services import order_contract


def _contract(**overrides) -> TaskContract:
    base = dict(
        task_id="task-123",
        client_agent_id="buyer-1",
        worker_agent_id="worker-1",
        title="Buy 100 widgets",
        description="Inspect and clear customs",
        expected_output_schema={"type": "object"},
        expected_step_count=3,
        escrow_amount=5000.0,
        currency="USD",
        deadline_at=datetime(2026, 12, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return TaskContract(**base)


def test_terms_hash_stable_across_key_order():
    terms = order_contract.build_terms(_contract())
    h1 = order_contract.terms_hash_hex(terms)
    # canonical JSON sorts keys, so a differently-ordered dict hashes identically
    raw = order_contract.canonical_terms_json(terms)
    assert '"escrow_amount":"5000.000000"' in raw
    assert '"task_id":"task-123"' in raw
    h2 = order_contract.terms_hash_hex(terms)
    assert h1 == h2
    assert len(h1) == 64


def test_terms_hash_changes_when_amount_changes():
    a = order_contract.terms_hash_hex(order_contract.build_terms(_contract(escrow_amount=5000.0)))
    b = order_contract.terms_hash_hex(order_contract.build_terms(_contract(escrow_amount=5001.0)))
    assert a != b


def test_buyer_sign_and_verify():
    acct = Account.create()
    terms = order_contract.build_terms(_contract())
    th = order_contract.terms_hash_hex(terms)
    sig = order_contract.sign_buyer(
        private_key=acct.key, terms_hash=th, task_id="task-123", chain_id=84532,
    )
    order_contract.verify_buyer_signature(
        buyer_address=acct.address, buyer_signature=sig,
        terms_hash=th, task_id="task-123", chain_id=84532,
    )


def test_buyer_verify_rejects_wrong_address():
    acct = Account.create()
    other = Account.create()
    terms = order_contract.build_terms(_contract())
    th = order_contract.terms_hash_hex(terms)
    sig = order_contract.sign_buyer(
        private_key=acct.key, terms_hash=th, task_id="task-123", chain_id=84532,
    )
    with pytest.raises(ValueError):
        order_contract.verify_buyer_signature(
            buyer_address=other.address, buyer_signature=sig,
            terms_hash=th, task_id="task-123", chain_id=84532,
        )


def test_worker_sign_and_verify():
    key = Ed25519PrivateKey.generate()
    terms = order_contract.build_terms(_contract())
    th = order_contract.terms_hash_hex(terms)
    sig, pub = order_contract.sign_worker(th, key)
    assert order_contract.verify_worker_signature(
        terms_hash=th, signature_b64=sig, public_key_b64=pub,
    )


def test_worker_verify_rejects_wrong_terms():
    key = Ed25519PrivateKey.generate()
    th = order_contract.terms_hash_hex(order_contract.build_terms(_contract()))
    other = order_contract.terms_hash_hex(order_contract.build_terms(_contract(escrow_amount=1.0)))
    sig, pub = order_contract.sign_worker(th, key)
    assert not order_contract.verify_worker_signature(
        terms_hash=other, signature_b64=sig, public_key_b64=pub,
    )


def test_terms_hash_bytes32_normalization():
    h = "0x" + "ab" * 32
    assert order_contract.terms_hash_bytes32(h) == h.lower()
    with pytest.raises(ValueError):
        order_contract.terms_hash_bytes32("short")

def test_trade_clauses_enter_terms_hash():
    base = order_contract.terms_hash_hex(order_contract.build_terms(_contract()))
    with_clauses = order_contract.terms_hash_hex(
        order_contract.build_terms(
            _contract(
                quality_standard="ISO 9001",
                inspection_standard="SGS pre-shipment",
                shipment_terms="CIF Shanghai",
                delivery_criteria="within 30 days",
                penalty="0.1% per day late",
                arbitration_rules="SIAC",
            )
        )
    )
    assert base != with_clauses


def test_trade_clauses_empty_do_not_change_hash():
    a = order_contract.terms_hash_hex(order_contract.build_terms(_contract()))
    b = order_contract.terms_hash_hex(
        order_contract.build_terms(_contract(quality_standard=None, penalty=None))
    )
    assert a == b

