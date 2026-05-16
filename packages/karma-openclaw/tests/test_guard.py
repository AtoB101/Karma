import json

import pytest

from karma_openclaw.guard import load_handoff_payload, require_valid_handoff, setup_mutations_allowed


def _handoff():
    return {
        "handoff_version": "1",
        "trace_id": "t",
        "task_id": "task-1",
        "voucher_id": "v-1",
        "buyer_identity_id": "b",
        "seller_identity_id": "s",
        "authorization": {
            "voucher_status": "accepted",
            "manual_console_steps_completed": [
                "buyer_create_voucher",
                "seller_accept_voucher",
                "settlement_created",
            ],
        },
    }


def test_require_valid_handoff_ok():
    err, norm = require_valid_handoff(json.dumps(_handoff()))
    assert err is None
    assert norm["task_id"] == "task-1"


def test_require_valid_handoff_missing_steps():
    h = _handoff()
    h["authorization"]["manual_console_steps_completed"] = []
    err, _ = require_valid_handoff(json.dumps(h))
    assert err is not None
    assert err["error"] == "handoff_invalid"


def test_load_handoff_requires_input():
    with pytest.raises(ValueError, match="handoff JSON required"):
        load_handoff_payload("")


def test_setup_mutations_default_off(monkeypatch):
    monkeypatch.delenv("KARMA_OPENCLAW_ALLOW_SETUP_MUTATIONS", raising=False)
    assert setup_mutations_allowed() is False
