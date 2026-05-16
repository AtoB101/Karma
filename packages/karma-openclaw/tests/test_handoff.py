import json

from karma_openclaw.handoff import validate_handoff_v1


def _minimal_handoff(**overrides):
    base = {
        "handoff_version": "1",
        "trace_id": "t1",
        "task_id": "task-1",
        "voucher_id": "v-1",
        "buyer_identity_id": "buyer-a",
        "seller_identity_id": "seller-b",
        "authorization": {
            "voucher_status": "accepted",
            "manual_console_steps_completed": [
                "buyer_create_voucher",
                "seller_accept_voucher",
                "settlement_created",
            ],
        },
    }
    base.update(overrides)
    return base


def test_handoff_valid_minimal():
    ok, errors, _ = validate_handoff_v1(_minimal_handoff())
    assert ok is True
    assert errors == []


def test_handoff_rejects_missing_manual_steps():
    payload = _minimal_handoff()
    payload["authorization"]["manual_console_steps_completed"] = ["buyer_create_voucher"]
    ok, errors, _ = validate_handoff_v1(payload)
    assert ok is False
    assert any("seller_accept_voucher" in e for e in errors)


def test_handoff_rejects_wrong_version():
    ok, errors, _ = validate_handoff_v1(_minimal_handoff(handoff_version="2"))
    assert ok is False
    assert any("handoff_version" in e for e in errors)
