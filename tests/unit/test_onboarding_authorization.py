"""Interactive onboarding authorization state machine — step order + consent gating."""
from __future__ import annotations

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from services.onboarding_authorization import (
    abort_onboarding,
    current_prompt,
    get_onboarding_flow,
    reset_onboarding_flows,
    respond_onboarding,
    start_onboarding,
)

# A deterministic test wallet; signatures are produced over the exact prompt message.
_KEY = "0x" + "11" * 32
_ACCOUNT = Account.from_key(_KEY)
VALID_ADDR = _ACCOUNT.address


def _sign(message: str) -> str:
    return "0x" + _ACCOUNT.sign_message(encode_defunct(text=message)).signature.hex()


@pytest.fixture(autouse=True)
def _fresh_store():
    reset_onboarding_flows()
    yield
    reset_onboarding_flows()


def _start(profile_id="merchant"):
    return start_onboarding(
        identity_id="identity-test", profile_id=profile_id, started_by="agent-test"
    )


def _advance_wallet_sign(flow_id, addr=VALID_ADDR):
    prompt = current_prompt(flow_id)["prompt"]
    message = prompt["payload"]["sign_message"]
    return respond_onboarding(
        flow_id=flow_id,
        action="sign",
        value={"address": addr, "signature": _sign(message)},
    )


def test_seven_steps_ordered_and_complete():
    r = _start()
    flow_id = r["flow"]["flow_id"]
    order = []
    order.append(r["prompt"]["step_id"])
    r = _advance_wallet_sign(flow_id)
    order.append(r["prompt"]["step_id"])
    r = respond_onboarding(flow_id=flow_id, action="confirm", value={"profile_id": "enterprise"})
    order.append(r["prompt"]["step_id"])
    r = respond_onboarding(flow_id=flow_id, action="confirm")
    order.append(r["prompt"]["step_id"])
    r = _advance_wallet_sign(flow_id)
    order.append(r["prompt"]["step_id"])
    r = respond_onboarding(flow_id=flow_id, action="confirm", value={"code": r["prompt"]["payload"]["match_code"]})
    order.append(r["prompt"]["step_id"])
    r = respond_onboarding(flow_id=flow_id, action="continue")
    order.append(r["prompt"]["step_id"])
    r = respond_onboarding(flow_id=flow_id, action="continue")

    assert order == [
        "owner_identity",
        "role_declaration",
        "funding_bounds",
        "runtime_key_mint",
        "agent_pairing",
        "binding_attestation",
        "runtime_spend",
    ]
    assert r["status"] == "complete"
    assert r["prompt"] is None


def test_prompt_types_match_step_contract():
    r = _start()
    flow_id = r["flow"]["flow_id"]
    seen = [r["prompt"]["prompt_type"]]
    r = _advance_wallet_sign(flow_id)
    seen.append(r["prompt"]["prompt_type"])
    r = respond_onboarding(flow_id=flow_id, action="confirm", value={"profile_id": "enterprise"})
    seen.append(r["prompt"]["prompt_type"])
    r = respond_onboarding(flow_id=flow_id, action="confirm")
    seen.append(r["prompt"]["prompt_type"])
    r = _advance_wallet_sign(flow_id)
    seen.append(r["prompt"]["prompt_type"])
    r = respond_onboarding(flow_id=flow_id, action="confirm", value={"code": r["prompt"]["payload"]["match_code"]})
    seen.append(r["prompt"]["prompt_type"])
    r = respond_onboarding(flow_id=flow_id, action="continue")
    seen.append(r["prompt"]["prompt_type"])

    assert seen == [
        "wallet_sign",
        "yes_no",
        "ack",
        "wallet_sign",
        "matching_code",
        "info",
        "info",
    ]
    assert r["prompt"]["prompt_type"] == "info"


def test_matching_code_rejects_wrong_value():
    r = _start()
    flow_id = r["flow"]["flow_id"]
    for step in range(4):
        if step == 0:
            r = _advance_wallet_sign(flow_id)
        elif step == 1:
            r = respond_onboarding(flow_id=flow_id, action="confirm", value={"profile_id": "enterprise"})
        elif step == 2:
            r = respond_onboarding(flow_id=flow_id, action="confirm")
        else:
            r = _advance_wallet_sign(flow_id)
    code = r["prompt"]["payload"]["match_code"]
    with pytest.raises(ValueError, match="code does not match"):
        respond_onboarding(flow_id=flow_id, action="confirm", value={"code": "XXXX-XXXX"})
    r = respond_onboarding(
        flow_id=flow_id, action="confirm", value={"code": code.lower().replace("-", "")}
    )
    assert r["prompt"]["step_id"] == "binding_attestation"


def test_wallet_sign_validates_address_and_signature():
    r = _start()
    flow_id = r["flow"]["flow_id"]
    with pytest.raises(ValueError, match="address"):
        respond_onboarding(flow_id=flow_id, action="sign", value={"address": "bad", "signature": "0x" + "ab" * 65})
    with pytest.raises(ValueError, match="signature"):
        respond_onboarding(flow_id=flow_id, action="sign", value={"address": VALID_ADDR, "signature": "bad"})


def test_wallet_sign_rejects_signature_from_wrong_key():
    r = _start()
    flow_id = r["flow"]["flow_id"]
    prompt = current_prompt(flow_id)["prompt"]
    message = prompt["payload"]["sign_message"]
    # Sign the correct message with a different wallet, then claim another address.
    other = Account.from_key("0x" + "22" * 32)
    sig = "0x" + other.sign_message(encode_defunct(text=message)).signature.hex()
    with pytest.raises(ValueError, match="verification failed"):
        respond_onboarding(flow_id=flow_id, action="sign", value={"address": VALID_ADDR, "signature": sig})


def test_wallet_sign_rejects_signature_over_different_message():
    r = _start()
    flow_id = r["flow"]["flow_id"]
    # Signing a different message must never recover to the claimed address for this step.
    sig = _sign("a totally different message")
    with pytest.raises(ValueError, match="verification failed"):
        respond_onboarding(flow_id=flow_id, action="sign", value={"address": VALID_ADDR, "signature": sig})


def test_reject_aborts_flow():
    r = _start()
    flow_id = r["flow"]["flow_id"]
    out = respond_onboarding(flow_id=flow_id, action="reject")
    assert out["status"] == "aborted"
    assert current_prompt(flow_id)["status"] == "aborted"
    with pytest.raises(ValueError, match="flow is aborted"):
        respond_onboarding(flow_id=flow_id, action="confirm")


def test_abort_endpoint_marks_aborted():
    r = _start()
    flow_id = r["flow"]["flow_id"]
    out = abort_onboarding(flow_id=flow_id)
    assert out["status"] == "aborted"
    assert get_onboarding_flow(flow_id).status == "aborted"


def test_start_rejects_bad_profile():
    with pytest.raises(ValueError, match="profile_id"):
        start_onboarding(identity_id="x", profile_id="admin")


def test_flow_binds_started_by():
    r = _start()
    assert r["flow"]["started_by"] == "agent-test"


def test_completed_flow_marks_identity_authorized():
    from services.onboarding_authorization import has_completed_onboarding

    assert not has_completed_onboarding("identity-test")
    r = _start()
    flow_id = r["flow"]["flow_id"]
    for step in range(7):
        p = current_prompt(flow_id)["prompt"]
        if p is None:
            break
        if p["prompt_type"] == "wallet_sign":
            r = _advance_wallet_sign(flow_id)
        elif p["prompt_type"] == "matching_code":
            r = respond_onboarding(flow_id=flow_id, action="confirm", value={"code": p["payload"]["match_code"]})
        elif p["prompt_type"] in ("yes_no", "ack"):
            r = respond_onboarding(flow_id=flow_id, action="confirm", value={"profile_id": "merchant"})
        else:
            r = respond_onboarding(flow_id=flow_id, action="continue")
    assert r["status"] == "complete"
    assert has_completed_onboarding("identity-test")
