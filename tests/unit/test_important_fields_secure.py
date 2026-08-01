"""Protocol capture + encrypted submit + triple match."""
from __future__ import annotations

import copy

import pytest

from services import important_fields_capture as capmod
from services.important_fields_capture import (
    CaptureError,
    capture_from_interaction,
    encrypt_for_capture,
    finalize_triple_match,
    submit_encrypted,
)
from services.important_fields_crypto import decrypt_canonical_fields, encrypt_canonical_fields
from services.important_fields_standard import example_for_scene, fields_hash


@pytest.fixture(autouse=True)
def _clean():
    capmod.reset_capture_store()
    yield
    capmod.reset_capture_store()


def test_triple_match_success_with_ciphertext_only():
    fields = example_for_scene("ride_hailing")["fields"]
    created = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="a2a:demo-1",
        extracted_fields=fields,
    )
    cid = created["capture_id"]
    assert created["protocol_fields_hash"] == fields_hash(fields)
    assert "protocol_mac" in created

    buyer_ct = encrypt_for_capture(cid, fields)["ciphertext"]
    seller_ct = encrypt_for_capture(cid, copy.deepcopy(fields))["ciphertext"]
    assert buyer_ct.startswith("karma1.")
    assert seller_ct.startswith("karma1.")

    submit_encrypted(capture_id=cid, role="buyer", ciphertext=buyer_ct, nonce="nonce-buyer-1")
    submit_encrypted(capture_id=cid, role="seller", ciphertext=seller_ct, nonce="nonce-seller-1")
    result = finalize_triple_match(cid)
    assert result["status"] == "MATCHED"
    assert result["triple_match"] is True
    assert result["buyer_fields_hash"] == result["protocol_fields_hash"]


def test_tampered_buyer_fails_triple_match():
    fields = example_for_scene("food_delivery")["fields"]
    cid = capture_from_interaction(
        scene_id="food_delivery",
        interaction_ref="chat:42",
        extracted_fields=fields,
    )["capture_id"]

    buyer = copy.deepcopy(fields)
    buyer["amount"] = "999.00"  # attacker rewrite
    buyer_ct = encrypt_for_capture(cid, buyer)["ciphertext"]
    seller_ct = encrypt_for_capture(cid, fields)["ciphertext"]
    submit_encrypted(capture_id=cid, role="buyer", ciphertext=buyer_ct, nonce="nonce-buyer-tamper")
    submit_encrypted(capture_id=cid, role="seller", ciphertext=seller_ct, nonce="nonce-seller-ok")
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
    )["capture_id"]
    ct = encrypt_for_capture(cid, fields)["ciphertext"]
    submit_encrypted(capture_id=cid, role="buyer", ciphertext=ct, nonce="same-nonce")
    with pytest.raises(CaptureError, match="nonce"):
        submit_encrypted(capture_id=cid, role="seller", ciphertext=ct, nonce="same-nonce")


def test_cross_capture_ciphertext_fails_aad():
    fields = example_for_scene("flight_booking")["fields"]
    a = capture_from_interaction(scene_id="flight_booking", interaction_ref="a", extracted_fields=fields)[
        "capture_id"
    ]
    b = capture_from_interaction(scene_id="flight_booking", interaction_ref="b", extracted_fields=fields)[
        "capture_id"
    ]
    ct_a = encrypt_canonical_fields(fields, capture_id=a)
    with pytest.raises(Exception):
        decrypt_canonical_fields(ct_a, capture_id=b)


def test_b2b_procurement_secure_path():
    fields = example_for_scene("b2b_procurement")["fields"]
    cid = capture_from_interaction(
        scene_id="b2b_procurement",
        interaction_ref="po:7781",
        extracted_fields=fields,
    )["capture_id"]
    for role, nonce in (("buyer", "nonce-po-buyer-1"), ("seller", "nonce-po-seller-1")):
        ct = encrypt_for_capture(cid, fields)["ciphertext"]
        submit_encrypted(capture_id=cid, role=role, ciphertext=ct, nonce=nonce)
    assert finalize_triple_match(cid)["status"] == "MATCHED"
