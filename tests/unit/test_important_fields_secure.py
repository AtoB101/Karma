"""Protocol capture + karma2 encrypted submit + triple match + anti-collusion."""
from __future__ import annotations

import copy

import pytest

from services import important_fields_capture as capmod
from services.important_fields_capture import (
    CaptureError,
    capture_from_interaction,
    encrypt_for_capture,
    finalize_triple_match,
    require_matched_capture,
    submit_encrypted,
)
from services.important_fields_crypto import decrypt_canonical_fields, encrypt_canonical_fields
from services.important_fields_standard import (
    example_for_scene,
    fields_hash,
    normalize_amount_string,
)


@pytest.fixture(autouse=True)
def _clean():
    capmod.reset_capture_store()
    yield
    capmod.reset_capture_store()


def test_triple_match_success_with_karma2_ciphertext():
    fields = example_for_scene("ride_hailing")["fields"]
    created = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="a2a:demo-1",
        extracted_fields=fields,
        buyer_agent_id="buyer-a",
        seller_agent_id="seller-b",
    )
    cid = created["capture_id"]
    assert created["protocol_fields_hash"] == fields_hash(fields)
    assert "protocol_mac" in created
    assert created.get("envelope") == "karma2"

    buyer_ct = encrypt_for_capture(cid, fields, role="buyer")["ciphertext"]
    seller_ct = encrypt_for_capture(cid, copy.deepcopy(fields), role="seller")["ciphertext"]
    assert buyer_ct.startswith("karma2.")
    assert seller_ct.startswith("karma2.")
    assert buyer_ct != seller_ct  # role-separated keys → different ciphertext

    submit_encrypted(
        capture_id=cid,
        role="buyer",
        ciphertext=buyer_ct,
        nonce="nonce-buyer-1",
        submitter_agent_id="buyer-a",
    )
    submit_encrypted(
        capture_id=cid,
        role="seller",
        ciphertext=seller_ct,
        nonce="nonce-seller-1",
        submitter_agent_id="seller-b",
    )
    result = finalize_triple_match(cid)
    assert result["status"] == "MATCHED"
    assert result["triple_match"] is True
    assert result["buyer_fields_hash"] == result["protocol_fields_hash"]
    assert result.get("sealed_at")

    # MATCHED sealed — no further submit
    with pytest.raises(CaptureError, match="sealed"):
        submit_encrypted(
            capture_id=cid,
            role="buyer",
            ciphertext=buyer_ct,
            nonce="nonce-buyer-2",
            submitter_agent_id="buyer-a",
        )

    # Idempotent finalize
    again = finalize_triple_match(cid)
    assert again["status"] == "MATCHED"
    assert again.get("idempotent") is True


def test_amount_precision_18_50_matches_18_5():
    fields = example_for_scene("ride_hailing")["fields"]
    protocol = copy.deepcopy(fields)
    protocol["amount"] = "18.50"
    buyer = copy.deepcopy(fields)
    buyer["amount"] = "18.5"
    seller = copy.deepcopy(fields)
    seller["amount"] = "18.5000"
    assert normalize_amount_string("18.50") == normalize_amount_string("18.5")
    assert fields_hash(protocol) == fields_hash(buyer) == fields_hash(seller)

    cid = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="a2a:precision",
        extracted_fields=protocol,
        buyer_agent_id="b1",
        seller_agent_id="s1",
    )["capture_id"]
    for role, agent, payload, nonce in (
        ("buyer", "b1", buyer, "n-buy-prec"),
        ("seller", "s1", seller, "n-sell-prec"),
    ):
        ct = encrypt_for_capture(cid, payload, role=role)["ciphertext"]
        submit_encrypted(
            capture_id=cid,
            role=role,
            ciphertext=ct,
            nonce=nonce,
            submitter_agent_id=agent,
        )
    assert finalize_triple_match(cid)["status"] == "MATCHED"


def test_tampered_buyer_fails_triple_match():
    fields = example_for_scene("food_delivery")["fields"]
    cid = capture_from_interaction(
        scene_id="food_delivery",
        interaction_ref="chat:42",
        extracted_fields=fields,
        buyer_agent_id="b1",
        seller_agent_id="s1",
    )["capture_id"]

    buyer = copy.deepcopy(fields)
    buyer["amount"] = "999.00"  # attacker rewrite
    buyer_ct = encrypt_for_capture(cid, buyer, role="buyer")["ciphertext"]
    seller_ct = encrypt_for_capture(cid, fields, role="seller")["ciphertext"]
    submit_encrypted(
        capture_id=cid,
        role="buyer",
        ciphertext=buyer_ct,
        nonce="nonce-buyer-tamper",
        submitter_agent_id="b1",
    )
    submit_encrypted(
        capture_id=cid,
        role="seller",
        ciphertext=seller_ct,
        nonce="nonce-seller-ok",
        submitter_agent_id="s1",
    )
    result = finalize_triple_match(cid)
    assert result["status"] == "COUNTERED"
    assert result["triple_match"] is False
    assert result["diff"]["buyer_vs_protocol"]


def test_plaintext_submit_rejected():
    fields = example_for_scene("hotel_booking")["fields"]
    cid = capture_from_interaction(
        scene_id="hotel_booking",
        interaction_ref="t1",
        extracted_fields=fields,
    )["capture_id"]
    with pytest.raises(CaptureError, match="ciphertext"):
        submit_encrypted(
            capture_id=cid,
            role="buyer",
            ciphertext='{"amount":"1"}',
            nonce="n1xxxxxx",
        )


def test_nonce_replay_rejected():
    fields = example_for_scene("api_tool_call")["fields"]
    cid = capture_from_interaction(
        scene_id="api_tool_call",
        interaction_ref="t2",
        extracted_fields=fields,
        buyer_agent_id="b1",
        seller_agent_id="s1",
    )["capture_id"]
    ct = encrypt_for_capture(cid, fields, role="buyer")["ciphertext"]
    submit_encrypted(
        capture_id=cid,
        role="buyer",
        ciphertext=ct,
        nonce="same-nonce",
        submitter_agent_id="b1",
    )
    with pytest.raises(CaptureError, match="nonce"):
        submit_encrypted(
            capture_id=cid,
            role="seller",
            ciphertext=encrypt_for_capture(cid, fields, role="seller")["ciphertext"],
            nonce="same-nonce",
            submitter_agent_id="s1",
        )


def test_cross_capture_ciphertext_fails_aad():
    fields = example_for_scene("flight_booking")["fields"]
    a = capture_from_interaction(
        scene_id="flight_booking", interaction_ref="a", extracted_fields=fields
    )["capture_id"]
    b = capture_from_interaction(
        scene_id="flight_booking", interaction_ref="b", extracted_fields=fields
    )["capture_id"]
    ph = fields_hash(fields)
    ct_a = encrypt_canonical_fields(
        fields,
        capture_id=a,
        scene_id="flight_booking",
        role="buyer",
        protocol_fields_hash=ph,
    )
    with pytest.raises(Exception):
        decrypt_canonical_fields(
            ct_a,
            capture_id=b,
            scene_id="flight_booking",
            role="buyer",
            protocol_fields_hash=ph,
        )


def test_role_key_separation_buyer_ct_not_decryptable_as_seller():
    fields = example_for_scene("ride_hailing")["fields"]
    cid = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="role-sep",
        extracted_fields=fields,
    )["capture_id"]
    pub = capmod.get_capture_public(cid)
    buyer_ct = encrypt_for_capture(cid, fields, role="buyer")["ciphertext"]
    with pytest.raises(Exception):
        decrypt_canonical_fields(
            buyer_ct,
            capture_id=cid,
            scene_id="ride_hailing",
            role="seller",
            protocol_fields_hash=pub["protocol_fields_hash"],
        )


def test_anti_collusion_same_submitter_rejected():
    fields = example_for_scene("b2b_procurement")["fields"]
    # Unbound capture: still reject one agent filling both roles
    cid = capture_from_interaction(
        scene_id="b2b_procurement",
        interaction_ref="po:collude",
        extracted_fields=fields,
    )["capture_id"]
    buyer_ct = encrypt_for_capture(cid, fields, role="buyer")["ciphertext"]
    seller_ct = encrypt_for_capture(cid, fields, role="seller")["ciphertext"]
    submit_encrypted(
        capture_id=cid,
        role="buyer",
        ciphertext=buyer_ct,
        nonce="n-buyer-c",
        submitter_agent_id="agent-x",
    )
    with pytest.raises(CaptureError, match="anti-collusion"):
        submit_encrypted(
            capture_id=cid,
            role="seller",
            ciphertext=seller_ct,
            nonce="n-seller-c",
            submitter_agent_id="agent-x",  # same actor both sides
        )


def test_bound_party_mismatch_rejected():
    fields = example_for_scene("food_delivery")["fields"]
    cid = capture_from_interaction(
        scene_id="food_delivery",
        interaction_ref="bind-1",
        extracted_fields=fields,
        buyer_agent_id="real-buyer",
        seller_agent_id="real-seller",
    )["capture_id"]
    ct = encrypt_for_capture(cid, fields, role="buyer")["ciphertext"]
    with pytest.raises(CaptureError, match="bound"):
        submit_encrypted(
            capture_id=cid,
            role="buyer",
            ciphertext=ct,
            nonce="n-wrong-buyer",
            submitter_agent_id="imposter",
        )


def test_require_matched_binds_interaction_and_amount():
    fields = example_for_scene("ride_hailing")["fields"]
    fields = copy.deepcopy(fields)
    fields["amount"] = "42.00"
    created = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="deal:42",
        extracted_fields=fields,
        buyer_agent_id="b1",
        seller_agent_id="s1",
    )
    cid = created["capture_id"]
    for role, agent, nonce in (("buyer", "b1", "nonce-b1"), ("seller", "s1", "nonce-s1")):
        ct = encrypt_for_capture(cid, fields, role=role)["ciphertext"]
        submit_encrypted(
            capture_id=cid,
            role=role,
            ciphertext=ct,
            nonce=nonce,
            submitter_agent_id=agent,
        )
    assert finalize_triple_match(cid)["status"] == "MATCHED"

    pub = require_matched_capture(
        capture_id=cid,
        scene_id="ride_hailing",
        interaction_ref="deal:42",
        expected_amount=42.0,
    )
    assert pub["status"] == "MATCHED"

    with pytest.raises(CaptureError, match="interaction_ref"):
        require_matched_capture(
            capture_id=cid,
            scene_id="ride_hailing",
            interaction_ref="deal:OTHER",
            expected_amount=42.0,
        )
    with pytest.raises(CaptureError, match="amount"):
        require_matched_capture(
            capture_id=cid,
            scene_id="ride_hailing",
            interaction_ref="deal:42",
            expected_amount=99.0,
        )


def test_b2b_procurement_secure_path():
    fields = example_for_scene("b2b_procurement")["fields"]
    cid = capture_from_interaction(
        scene_id="b2b_procurement",
        interaction_ref="po:7781",
        extracted_fields=fields,
        buyer_agent_id="ent-buyer",
        seller_agent_id="ent-seller",
    )["capture_id"]
    for role, agent, nonce in (
        ("buyer", "ent-buyer", "nonce-po-buyer-1"),
        ("seller", "ent-seller", "nonce-po-seller-1"),
    ):
        ct = encrypt_for_capture(cid, fields, role=role)["ciphertext"]
        submit_encrypted(
            capture_id=cid,
            role=role,
            ciphertext=ct,
            nonce=nonce,
            submitter_agent_id=agent,
        )
    assert finalize_triple_match(cid)["status"] == "MATCHED"
