"""P8 settlement reputation — scene policy, encrypted attest, agent auto-verify."""
from __future__ import annotations

import pytest

from services import settlement_reputation as sr
from services.settlement_reputation import (
    SettlementReputationError,
    agent_auto_verify_decision,
    assert_settle_gates,
    decrypt_attestation,
    public_agent_reputation,
    public_attestation_view,
    seal_settlement_attestation,
    scene_settle_policy,
    verify_outcome_commitment,
)


@pytest.fixture(autouse=True)
def _clean():
    sr.reset_settle_attestations()
    yield
    sr.reset_settle_attestations()


def test_scene_policies_differ():
    food = scene_settle_policy("food_delivery")
    b2b = scene_settle_policy("b2b_procurement")
    fin = scene_settle_policy("financial_services")
    assert food["agent_auto_verify"] is True
    assert food["mode"] == "instant_on_verified"
    assert b2b["confirm"] == "OWNER_CONFIRM"
    assert b2b["invoice_window_seconds"] == 86400
    assert fin["agent_auto_verify"] is False
    assert fin["mode"] == "delayed_explicit"


def test_agent_auto_verify_food_vs_finance():
    food = agent_auto_verify_decision(
        scene_id="food_delivery",
        task_id="t1",
        delivery_verified=True,
    )
    fin = agent_auto_verify_decision(
        scene_id="financial_services",
        task_id="t2",
        delivery_verified=True,
    )
    assert food["allowed"] is True
    assert fin["allowed"] is False


def test_seal_public_has_no_plaintext_amount():
    pub = seal_settlement_attestation(
        task_id="task-seal-1",
        scene_id="food_delivery",
        buyer_agent_id="buyer-priv",
        seller_agent_id="seller-priv",
        amount=28.5,
        capture_id="cap_demo",
        agent_auto_verified=True,
    )
    assert pub["attestation_id"].startswith("sat_")
    assert pub["outcome_commitment"]
    assert pub["scope_hash"]
    assert pub["reputation_delta_commitment"]
    assert pub["agent_auto_verified"] is True
    # Public JSON must not embed raw amount or full agent ids as private fields
    blob = str(pub)
    assert "28.5" not in blob
    assert "buyer-priv" not in blob
    assert "seller-priv" not in blob


def test_verify_commitment_integrity():
    pub = seal_settlement_attestation(
        task_id="task-v",
        scene_id="ride_hailing",
        buyer_agent_id="b",
        seller_agent_id="s",
        amount=45.0,
    )
    check = verify_outcome_commitment(attestation_id=pub["attestation_id"])
    assert check["valid"] is True
    bad = verify_outcome_commitment(
        attestation_id=pub["attestation_id"],
        expected_commitment="0" * 64,
    )
    assert bad["valid"] is False


def test_decrypt_parties_and_regulator():
    pub = seal_settlement_attestation(
        task_id="task-d",
        scene_id="b2b_procurement",
        buyer_agent_id="ent-buyer",
        seller_agent_id="ent-seller",
        amount=1500.0,
    )
    aid = pub["attestation_id"]
    parties = decrypt_attestation(aid, role="parties")
    assert parties["detail"]["amount"] == 1500.0
    assert parties["detail"]["buyer_agent_id"] == "ent-buyer"
    assert "traceback" in parties["detail"]["audit"]
    reg = decrypt_attestation(aid, role="regulator")
    assert reg["detail"]["regulator_access"] is True


def test_wrong_role_decrypt_fails_conceptually():
    """Tampered ciphertext / wrong binding fails decrypt."""
    pub = seal_settlement_attestation(
        task_id="task-x",
        scene_id="api_tool_call",
        buyer_agent_id="b",
        seller_agent_id="s",
        amount=1.0,
    )
    # Corrupt stored ciphertext
    with sr._LOCK:  # noqa: SLF001
        rec = sr._ATTESTATIONS[pub["attestation_id"]]  # noqa: SLF001
        rec["ciphertext"]["parties"] = "karma2." + "A" * 80
    with pytest.raises(SettlementReputationError, match="decrypt"):
        decrypt_attestation(pub["attestation_id"], role="parties")


def test_scene_reputation_public_aggregate():
    seal_settlement_attestation(
        task_id="t-r1",
        scene_id="food_delivery",
        buyer_agent_id="b",
        seller_agent_id="merchant-x",
        amount=20.0,
    )
    seal_settlement_attestation(
        task_id="t-r2",
        scene_id="food_delivery",
        buyer_agent_id="b2",
        seller_agent_id="merchant-x",
        amount=30.0,
    )
    pub = public_agent_reputation("merchant-x")
    assert pub["total_settled"] == 2
    assert pub["total_success"] == 2
    food = next(s for s in pub["scenes"] if s["scene_id"] == "food_delivery")
    assert food["settled_count"] == 2
    assert food["score_delta_commitment"]


def test_assert_gates_owner_confirm():
    ok = assert_settle_gates(
        task_id="tg1",
        scene_id="b2b_procurement",
        delivery_verified=True,
        confirmation_satisfied=False,
        success_receipt=True,
        agent_auto=False,
    )
    assert ok["ok"] is False
    assert "owner_confirm_required" in ok["errors"]

    ok2 = assert_settle_gates(
        task_id="tg2",
        scene_id="food_delivery",
        delivery_verified=True,
        confirmation_satisfied=True,
        success_receipt=True,
        agent_auto=True,
    )
    assert ok2["ok"] is True


def test_public_view_idempotent():
    pub = seal_settlement_attestation(
        task_id="task-idem",
        scene_id="hotel_booking",
        buyer_agent_id="g",
        seller_agent_id="h",
        amount=320.0,
    )
    again = public_attestation_view(pub["attestation_id"])
    assert again["outcome_commitment"] == pub["outcome_commitment"]
