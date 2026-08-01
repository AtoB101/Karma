"""Adversarial P1–P8 suite — try to overthrow gates (crypto/collusion/bypass/race/privacy).

PASS = attack blocked; no unauthorized MATCHED / VERIFIED / SETTLED / plaintext leak.
"""
from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services import accept_fulfillment as af
from services import delivery_verification as dv
from services import human_confirmation_policy as hcp
from services import important_fields_capture as capmod
from services import settlement_reputation as sr
from services.accept_fulfillment import (
    process_expired_seller_session,
    record_seller_non_confirm,
    seller_risk_profile,
)
from services.agent_trust import AgentTrustStats
from services.delivery_verification import (
    DeliveryVerificationError,
    apply_silent_buyer_default,
    create_verification_session,
    issue_capture_challenge,
    logistics_deliver,
    logistics_intake,
    require_verified_for_settle,
    seller_ship,
)
from services.discovery_priority import apply_priority_ranking
from services.human_confirmation_policy import (
    ConfirmationPolicyError,
    assert_step_allowed,
    create_confirmation_session,
    decide_confirmation_session,
    reset_confirmation_sessions,
)
from services.important_fields_capture import (
    CaptureError,
    capture_from_interaction,
    encrypt_for_capture,
    finalize_triple_match,
    submit_encrypted,
)
from services.important_fields_crypto import FieldsCryptoError
from services.important_fields_standard import example_for_scene
from services.settlement_reputation import (
    agent_auto_verify_decision,
    assert_settle_gates,
    decrypt_attestation,
    public_agent_reputation,
    seal_settlement_attestation,
    verify_outcome_commitment,
)


@pytest.fixture(autouse=True)
def _clean_all():
    capmod.reset_capture_store()
    sr.reset_settle_attestations()
    af.reset_accept_ledger()
    dv.reset_delivery_sessions()
    reset_confirmation_sessions()
    yield
    capmod.reset_capture_store()
    sr.reset_settle_attestations()
    af.reset_accept_ledger()
    dv.reset_delivery_sessions()
    reset_confirmation_sessions()


# ─── Crypto ───────────────────────────────────────────────────────────────


def test_adv_aad_role_splice_blocked():
    fields = example_for_scene("ride_hailing")["fields"]
    cid = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="a2a:adv-role",
        extracted_fields=fields,
        buyer_agent_id="b",
        seller_agent_id="s",
    )["capture_id"]
    buyer_ct = encrypt_for_capture(cid, fields, role="buyer")["ciphertext"]
    with pytest.raises((CaptureError, FieldsCryptoError)):
        submit_encrypted(
            capture_id=cid,
            role="seller",
            ciphertext=buyer_ct,
            nonce="n-role-splice",
            submitter_agent_id="s",
        )


def test_adv_cross_capture_ciphertext_blocked():
    fields = example_for_scene("food_delivery")["fields"]
    a = capture_from_interaction(
        scene_id="food_delivery",
        interaction_ref="a2a:adv-a",
        extracted_fields=fields,
        buyer_agent_id="b1",
        seller_agent_id="s1",
    )["capture_id"]
    b = capture_from_interaction(
        scene_id="food_delivery",
        interaction_ref="a2a:adv-b",
        extracted_fields=fields,
        buyer_agent_id="b2",
        seller_agent_id="s2",
    )["capture_id"]
    ct = encrypt_for_capture(a, fields, role="buyer")["ciphertext"]
    with pytest.raises((CaptureError, FieldsCryptoError)):
        submit_encrypted(
            capture_id=b,
            role="buyer",
            ciphertext=ct,
            nonce="n-xcap",
            submitter_agent_id="b2",
        )


def test_adv_bitflip_ciphertext_fails():
    fields = example_for_scene("ride_hailing")["fields"]
    cid = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="a2a:adv-flip",
        extracted_fields=fields,
        buyer_agent_id="b",
        seller_agent_id="s",
    )["capture_id"]
    ct = encrypt_for_capture(cid, fields, role="buyer")["ciphertext"]
    parts = ct.split(".", 1)
    blob = parts[1]
    flipped = ("A" if blob[10] != "A" else "B") + blob[1:]
    bad = parts[0] + "." + flipped
    with pytest.raises((CaptureError, FieldsCryptoError)):
        submit_encrypted(
            capture_id=cid,
            role="buyer",
            ciphertext=bad,
            nonce="n-flip",
            submitter_agent_id="b",
        )


def test_adv_protocol_hash_mismatch_countered():
    fields = example_for_scene("ride_hailing")["fields"]
    protocol = copy.deepcopy(fields)
    buyer = copy.deepcopy(fields)
    buyer["amount"] = "99999.00"
    cid = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="a2a:adv-amt",
        extracted_fields=protocol,
        buyer_agent_id="b",
        seller_agent_id="s",
    )["capture_id"]
    submit_encrypted(
        capture_id=cid,
        role="buyer",
        ciphertext=encrypt_for_capture(cid, buyer, role="buyer")["ciphertext"],
        nonce="n-bad-buyer",
        submitter_agent_id="b",
    )
    submit_encrypted(
        capture_id=cid,
        role="seller",
        ciphertext=encrypt_for_capture(cid, protocol, role="seller")["ciphertext"],
        nonce="n-bad-seller",
        submitter_agent_id="s",
    )
    result = finalize_triple_match(cid)
    assert result["status"] in {"COUNTERED", "FAILED"}
    assert result.get("triple_match") is not True


# ─── Collusion ────────────────────────────────────────────────────────────


def test_adv_same_submitter_both_roles_blocked():
    fields = example_for_scene("food_delivery")["fields"]
    # Unbound capture: one agent filling both roles must still be rejected
    cid = capture_from_interaction(
        scene_id="food_delivery",
        interaction_ref="a2a:adv-col",
        extracted_fields=fields,
    )["capture_id"]
    submit_encrypted(
        capture_id=cid,
        role="buyer",
        ciphertext=encrypt_for_capture(cid, fields, role="buyer")["ciphertext"],
        nonce="n-col-buyer",
        submitter_agent_id="colluder",
    )
    with pytest.raises(CaptureError, match="anti-collusion|both|same submitter"):
        submit_encrypted(
            capture_id=cid,
            role="seller",
            ciphertext=encrypt_for_capture(cid, fields, role="seller")["ciphertext"],
            nonce="n-col-seller",
            submitter_agent_id="colluder",
        )


def test_adv_bound_party_mismatch_blocked():
    fields = example_for_scene("food_delivery")["fields"]
    cid = capture_from_interaction(
        scene_id="food_delivery",
        interaction_ref="a2a:adv-bind",
        extracted_fields=fields,
        buyer_agent_id="real-buyer",
        seller_agent_id="real-seller",
    )["capture_id"]
    with pytest.raises(CaptureError, match="anti-collusion|must match"):
        submit_encrypted(
            capture_id=cid,
            role="buyer",
            ciphertext=encrypt_for_capture(cid, fields, role="buyer")["ciphertext"],
            nonce="n-bind-imp",
            submitter_agent_id="impostor",
        )


def test_adv_post_matched_resubmit_sealed():
    fields = example_for_scene("ride_hailing")["fields"]
    cid = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="a2a:adv-seal",
        extracted_fields=fields,
        buyer_agent_id="b",
        seller_agent_id="s",
    )["capture_id"]
    for role, agent, nonce in (("buyer", "b", "n-seal-b"), ("seller", "s", "n-seal-s")):
        submit_encrypted(
            capture_id=cid,
            role=role,
            ciphertext=encrypt_for_capture(cid, fields, role=role)["ciphertext"],
            nonce=nonce,
            submitter_agent_id=agent,
        )
    assert finalize_triple_match(cid)["status"] == "MATCHED"
    with pytest.raises(CaptureError, match="sealed"):
        submit_encrypted(
            capture_id=cid,
            role="buyer",
            ciphertext=encrypt_for_capture(cid, fields, role="buyer")["ciphertext"],
            nonce="n-seal-again",
            submitter_agent_id="b",
        )


# ─── Gate bypass ──────────────────────────────────────────────────────────


def test_adv_high_risk_forbids_agent_auto():
    dec = agent_auto_verify_decision(
        scene_id="financial_services",
        task_id="t-fin",
        delivery_verified=True,
    )
    assert dec["allowed"] is False
    gates = assert_settle_gates(
        task_id="t-fin",
        scene_id="financial_services",
        delivery_verified=True,
        confirmation_satisfied=True,
        success_receipt=True,
        agent_auto=True,
    )
    assert gates["ok"] is False
    assert any("high_risk" in e or "agent_auto" in e for e in gates["errors"])


def test_adv_physical_settle_without_p7_blocked():
    with pytest.raises(Exception):
        require_verified_for_settle(
            task_id="no-dv-task",
            scene_id="food_delivery",
            allow_missing_session_for_digital=False,
        )
    gates = assert_settle_gates(
        task_id="no-dv-physical",
        scene_id="food_delivery",
        delivery_verified=False,
        confirmation_satisfied=True,
        success_receipt=True,
    )
    assert gates["ok"] is False


def test_adv_confirmation_replay_used_blocked():
    sess = create_confirmation_session(
        scene_id="hotel_booking",
        role="buyer",
        step="buyer_accept_settle",
        owner_agent_id="owner-h",
        context={"amount": 200.0, "currency": "USDC"},
        interaction_ref="settle:task-h",
        policy_auto_allowed=False,
    )
    sid = sess["session_id"]
    decide_confirmation_session(sid, confirm=True, actor_agent_id="owner-h")
    assert_step_allowed(
        scene_id="hotel_booking",
        role="buyer",
        step="buyer_accept_settle",
        confirmation_session_id=sid,
        policy_auto_allowed=False,
        expected_owner_agent_id="owner-h",
        amount=200.0,
        consume=True,
    )
    with pytest.raises(ConfirmationPolicyError):
        assert_step_allowed(
            scene_id="hotel_booking",
            role="buyer",
            step="buyer_accept_settle",
            confirmation_session_id=sid,
            policy_auto_allowed=False,
            expected_owner_agent_id="owner-h",
            amount=200.0,
            consume=True,
        )


def test_adv_wrong_actor_decide_blocked():
    sess = create_confirmation_session(
        scene_id="b2b_procurement",
        role="buyer",
        step="accept_order",
        owner_agent_id="real-owner",
        context={"amount": 1000.0, "po_number": "PO-1"},
        interaction_ref="a2a:b2b-1",
        policy_auto_allowed=False,
    )
    with pytest.raises(ConfirmationPolicyError):
        decide_confirmation_session(
            sess["session_id"],
            confirm=True,
            actor_agent_id="attacker",
        )


def test_adv_auto_complete_forbidden_outside_demo(monkeypatch):
    from config import settings as settings_mod
    from services.human_confirmation_policy import allow_demo_confirmation_bypass

    monkeypatch.setattr(settings_mod.settings, "app_env", "production")
    assert allow_demo_confirmation_bypass() is False


# ─── Race / stress ────────────────────────────────────────────────────────


def test_adv_nonce_parallel_double_submit():
    fields = example_for_scene("ride_hailing")["fields"]
    cid = capture_from_interaction(
        scene_id="ride_hailing",
        interaction_ref="a2a:adv-race-n",
        extracted_fields=fields,
        buyer_agent_id="b",
        seller_agent_id="s",
    )["capture_id"]
    ct = encrypt_for_capture(cid, fields, role="buyer")["ciphertext"]
    results: list[str] = []
    lock = threading.Lock()

    def _try():
        try:
            submit_encrypted(
                capture_id=cid,
                role="buyer",
                ciphertext=ct,
                nonce="shared-nonce",
                submitter_agent_id="b",
            )
            with lock:
                results.append("ok")
        except CaptureError as exc:
            with lock:
                results.append(f"err:{exc}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_try) for _ in range(8)]
        for f in as_completed(futs):
            f.result()
    assert results.count("ok") == 1
    assert sum(1 for r in results if r.startswith("err:")) == 7


def test_adv_expire_idempotent_single_non_confirm():
    sess = create_confirmation_session(
        scene_id="b2b_procurement",
        role="seller",
        step="accept_order",
        owner_agent_id="seller-race",
        context={"amount": 1500.0, "po_number": "PO-RACE"},
        interaction_ref="a2a:race-ttl",
        policy_auto_allowed=False,
        ttl_seconds=60,
    )
    sid = sess["session_id"]
    with hcp._LOCK:  # noqa: SLF001
        obj = hcp._SESSIONS[sid]  # noqa: SLF001
        obj.expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=5)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    first = process_expired_seller_session(sid, apply_cancel=True)
    assert first is not None
    second = process_expired_seller_session(sid, apply_cancel=True)
    assert second is not None
    assert second.get("idempotent") is True
    profile = seller_risk_profile("seller-race", scene_id="b2b_procurement")
    assert int(profile.get("non_confirm_count") or 0) == 1


def test_adv_attempt_budget_storm_fails_capture():
    fields = example_for_scene("food_delivery")["fields"]
    cid = capture_from_interaction(
        scene_id="food_delivery",
        interaction_ref="a2a:adv-storm",
        extracted_fields=fields,
        buyer_agent_id="b",
        seller_agent_id="s",
    )["capture_id"]
    bad_ct = "karma2." + ("A" * 80)
    for i in range(12):
        try:
            submit_encrypted(
                capture_id=cid,
                role="buyer",
                ciphertext=bad_ct,
                nonce=f"storm-{i:02d}",
                submitter_agent_id="b",
            )
        except CaptureError:
            pass
    pub = capmod.get_capture_public(cid)
    assert pub["status"] == "FAILED"
    with pytest.raises(CaptureError, match="attempt|FAILED|cannot|limit|sealed"):
        submit_encrypted(
            capture_id=cid,
            role="buyer",
            ciphertext=encrypt_for_capture(cid, fields, role="buyer")["ciphertext"],
            nonce="after-storm",
            submitter_agent_id="b",
        )


# ─── Privacy ──────────────────────────────────────────────────────────────


def test_adv_p8_disk_store_no_plaintext_parties_or_amount():
    pub = seal_settlement_attestation(
        task_id="task-priv-1",
        scene_id="food_delivery",
        buyer_agent_id="buyer-secret-xyz",
        seller_agent_id="seller-secret-xyz",
        amount=12345.67,
    )
    store_path = sr._STORE_PATH  # noqa: SLF001
    assert store_path.is_file()
    raw = store_path.read_text(encoding="utf-8")
    assert "buyer-secret-xyz" not in raw
    assert "seller-secret-xyz" not in raw
    assert "12345.67" not in raw
    assert "12345.670000" not in raw
    detail = decrypt_attestation(pub["attestation_id"], role="parties")["detail"]
    assert detail["amount"] == 12345.67
    assert detail["buyer_agent_id"] == "buyer-secret-xyz"


def test_adv_public_reputation_omits_raw_agent_id_by_default():
    seal_settlement_attestation(
        task_id="t-rep-priv",
        scene_id="food_delivery",
        buyer_agent_id="b",
        seller_agent_id="merchant-hidden",
        amount=10.0,
    )
    pub = public_agent_reputation("merchant-hidden")
    assert "agent_id" not in pub
    assert pub["agent_commitment"]
    opt_in = public_agent_reputation("merchant-hidden", include_agent_id=True)
    assert opt_in["agent_id"] == "merchant-hidden"


def test_adv_forged_outcome_commitment_invalid():
    pub = seal_settlement_attestation(
        task_id="t-forge",
        scene_id="ride_hailing",
        buyer_agent_id="b",
        seller_agent_id="s",
        amount=40.0,
    )
    bad = verify_outcome_commitment(
        attestation_id=pub["attestation_id"],
        expected_commitment="f" * 64,
    )
    assert bad["valid"] is False


# ─── TTL / silent abuse ───────────────────────────────────────────────────


def test_adv_silent_without_pod_blocked():
    sess = create_verification_session(
        task_id="t-silent-early",
        scene_id="food_delivery",
        buyer_agent_id="b1",
        seller_agent_id="s1",
        logistics_agent_id="l1",
        amount=25.0,
    )
    out = apply_silent_buyer_default(sess["verification_id"])
    assert out is None or out.get("status") != "VERIFIED"


def test_adv_silent_high_risk_never_defaults():
    sess = create_verification_session(
        task_id="t-silent-hr",
        scene_id="financial_services",
        buyer_agent_id="b1",
        seller_agent_id="s1",
        amount=10000.0,
    )
    vid = sess["verification_id"]
    with dv._LOCK:  # noqa: SLF001
        s = dv._SESSIONS[vid]  # noqa: SLF001
        s["status"] = "AWAITING_BUYER_RECEIPT"
        s["buyer_silent_deadline"] = (
            datetime.now(timezone.utc) - timedelta(seconds=5)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out = apply_silent_buyer_default(vid)
    assert out is None or out.get("status") != "VERIFIED"


def test_adv_challenge_tag_hmac_mismatch():
    sess = create_verification_session(
        task_id="t-tag",
        scene_id="food_delivery",
        buyer_agent_id="b1",
        seller_agent_id="s1",
        logistics_agent_id="l1",
        amount=22.0,
    )
    vid = sess["verification_id"]
    seller_ship(vid, actor_agent_id="s1")
    logistics_intake(vid, actor_agent_id="l1", item_matches=True)
    ch = issue_capture_challenge(vid, party_role="logistics", geo_hash="gh1")
    with pytest.raises(DeliveryVerificationError, match="HMAC"):
        logistics_deliver(
            vid,
            actor_agent_id="l1",
            content_hash="pod_" + "b" * 20,
            nonce=ch["nonce"],
            captured_at=ch["captured_at"],
            geo_hash="gh1",
            tag_hmac="0" * 64,
        )


# ─── Discovery demote ─────────────────────────────────────────────────────


def test_adv_demoted_seller_sorts_after_clean_peer():
    for i in range(15):
        record_seller_non_confirm(
            seller_id="bad-seller",
            scene_id="food_delivery",
            interaction_ref=f"a2a:nc-{i}",
            reason="timeout",
            session_id=f"cfm-nc-{i}",
            amount=10.0,
        )
    profile = seller_risk_profile("bad-seller", scene_id="food_delivery")
    assert profile.get("discovery_demote") is True

    stats = {
        "bad-seller": AgentTrustStats(
            agent_id="bad-seller",
            reputation_score=500,
            settled_count=100,
            settled_volume=10000,
            total_tasks=100,
            successful_tasks=99,
            success_rate=0.99,
            cold_start=False,
        ),
        "clean-seller": AgentTrustStats(
            agent_id="clean-seller",
            reputation_score=50,
            settled_count=5,
            settled_volume=100,
            total_tasks=5,
            successful_tasks=5,
            success_rate=1.0,
            cold_start=False,
        ),
    }
    ranked = apply_priority_ranking(
        [
            {
                "agent_id": "bad-seller",
                "p1_ready": True,
                "boundary_complete": True,
                "score": 0.99,
                "scene_ids": ["food_delivery"],
            },
            {
                "agent_id": "clean-seller",
                "p1_ready": True,
                "boundary_complete": True,
                "score": 0.50,
                "scene_ids": ["food_delivery"],
            },
        ],
        stats,
        scene_id="food_delivery",
        enforce_scene_policy=False,
        drop_ineligible=False,
    )
    ids = [c["agent_id"] for c in ranked]
    assert "clean-seller" in ids and "bad-seller" in ids
    assert ids.index("clean-seller") < ids.index("bad-seller")


def test_adv_client_forged_flags_do_not_invent_eligibility():
    for i in range(15):
        record_seller_non_confirm(
            seller_id="forge-flag",
            scene_id="ride_hailing",
            interaction_ref=f"a2a:ff-{i}",
            reason="timeout",
            session_id=f"cfm-ff-{i}",
        )
    ranked = apply_priority_ranking(
        [
            {
                "agent_id": "forge-flag",
                "p1_ready": True,
                "boundary_complete": True,
                "score": 1.0,
                "scene_ids": ["ride_hailing"],
                "accept_risk": {"discovery_demote": False, "non_confirm_count": 0},
            }
        ],
        {"forge-flag": AgentTrustStats(agent_id="forge-flag")},
        scene_id="ride_hailing",
        enforce_scene_policy=False,
        drop_ineligible=False,
    )
    assert ranked
    risk = ranked[0].get("accept_risk") or {}
    assert int(risk.get("non_confirm_count") or 0) >= 15
    assert risk.get("discovery_demote") is True


# ─── Source-level hardenings (static) ──────────────────────────────────────


def test_adv_static_buyer_accept_uses_settle_scene_hint():
    text = Path("api/routes/settlement.py").read_text(encoding="utf-8")
    assert "settle_scene = (settle_scene_hint" in text
    assert "Omitting scene_id must not bypass" in text


def test_adv_static_decrypt_requires_auth():
    text = Path("api/routes/settlement_reputation.py").read_text(encoding="utf-8")
    assert "get_current_agent_id" in text
    assert "Depends(get_current_agent_id)" in text


def test_adv_static_session_key_requires_auth():
    text = Path("api/routes/standards.py").read_text(encoding="utf-8")
    assert "get_capture_session_key" in text
    assert "get_current_agent_id" in text


def test_adv_static_auto_complete_prod_killswitch():
    text = Path("services/intent_fulfillment.py").read_text(encoding="utf-8")
    assert "auto_complete_forbidden" in text
    assert "allow_demo_confirmation_bypass()" in text
