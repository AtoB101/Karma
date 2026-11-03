"""Signed, sequenced off-chain settlement states (channel primitive)."""
from __future__ import annotations

import pytest
from eth_account import Account
from fastapi import HTTPException

from services import settlement_channel
from services.settlement_channel import ChannelLedger, state_batch_hash

KEY_A = "0x3333333333333333333333333333333333333333333333333333333333333333"
KEY_B = "0x4444444444444444444444444444444444444444444444444444444444444444"
ADDR_A = Account.from_key(KEY_A).address
ADDR_B = Account.from_key(KEY_B).address


def _state(channel_id="ch-1", seq=1, balances=None, meta_hash="0xdeadbeef"):
    return {
        "channel_id": channel_id,
        "seq": seq,
        "balances": balances or {ADDR_A: "10.0", ADDR_B: "0.0"},
        "meta_hash": meta_hash,
    }


def test_sign_recovers_to_signer():
    state = _state(seq=1)
    sig = settlement_channel.sign_state(private_key=KEY_A, **state)
    recovered = settlement_channel.recover_signer(signature=sig, **state)
    assert recovered.lower() == ADDR_A.lower()


def test_verify_state_true_for_signer_false_for_other():
    state = _state(seq=1)
    sig = settlement_channel.sign_state(private_key=KEY_A, **state)
    assert settlement_channel.verify_state(signature=sig, signer_address=ADDR_A, **state) is True
    assert settlement_channel.verify_state(signature=sig, signer_address=ADDR_B, **state) is False


def test_canonical_message_is_order_independent():
    s1 = _state(balances={ADDR_A: "1.0", ADDR_B: "2.0"})
    s2 = _state(balances={ADDR_B: "2.0", ADDR_A: "1.0"})
    assert settlement_channel.canonical_state_message(**s1) == settlement_channel.canonical_state_message(**s2)


def test_ledger_accepts_increasing_seq():
    ledger = ChannelLedger(parties={ADDR_A, ADDR_B})
    ledger.apply(state=_state(seq=1), signature=settlement_channel.sign_state(private_key=KEY_A, **_state(seq=1)), signer_address=ADDR_A)
    ledger.apply(state=_state(seq=2), signature=settlement_channel.sign_state(private_key=KEY_B, **_state(seq=2)), signer_address=ADDR_B)
    assert ledger.latest_seq == 2


def test_ledger_rejects_stale_or_equal_seq():
    ledger = ChannelLedger(parties={ADDR_A, ADDR_B})
    st = _state(seq=5)
    ledger.apply(state=st, signature=settlement_channel.sign_state(private_key=KEY_A, **st), signer_address=ADDR_A)
    with pytest.raises(HTTPException) as exc:
        ledger.apply(state=_state(seq=3), signature=settlement_channel.sign_state(private_key=KEY_A, **_state(seq=3)), signer_address=ADDR_A)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        ledger.apply(state=st, signature=settlement_channel.sign_state(private_key=KEY_A, **st), signer_address=ADDR_A)
    assert exc.value.status_code == 409


def test_ledger_rejects_non_party_signer():
    ledger = ChannelLedger(parties={ADDR_A})
    outsider = Account.create()
    st = _state(seq=1)
    sig = settlement_channel.sign_state(private_key=outsider.key.hex(), **st)
    with pytest.raises(HTTPException) as exc:
        ledger.apply(state=st, signature=sig, signer_address=outsider.address)
    assert exc.value.status_code == 403


def test_exit_evidence_carries_latest_state_and_signatures():
    ledger = ChannelLedger(parties={ADDR_A, ADDR_B})
    st = _state(seq=7)
    ledger.apply(state=st, signature=settlement_channel.sign_state(private_key=KEY_A, **st), signer_address=ADDR_A)
    evidence = ledger.exit_evidence()
    assert evidence["latest_seq"] == 7
    assert evidence["state"]["meta_hash"] == "0xdeadbeef"
    assert ADDR_A.lower() in evidence["signatures"]


def test_batch_hash_is_deterministic_and_state_sensitive():
    states = [_state(seq=1), _state(seq=2, meta_hash="0xabc")]
    assert state_batch_hash(states) == state_batch_hash(states)
    changed = [_state(seq=1), _state(seq=2, meta_hash="0xdef")]
    assert state_batch_hash(states) != state_batch_hash(changed)


def test_batch_due_thresholds():
    assert settlement_channel.batch_due(total_value=9.0, value_threshold=10.0, seq=4, seq_threshold=5) is False
    assert settlement_channel.batch_due(total_value=10.0, value_threshold=10.0, seq=4, seq_threshold=5) is True
    assert settlement_channel.batch_due(total_value=0.0, value_threshold=10.0, seq=5, seq_threshold=5) is True
