"""P7 delivery verification — physical triple, silent default, tags, tickets."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services import delivery_verification as dv
from services.delivery_verification import (
    DeliveryVerificationError,
    apply_silent_buyer_default,
    buyer_confirm,
    create_verification_session,
    demo_complete_physical_flow,
    issue_capture_challenge,
    logistics_deliver,
    logistics_intake,
    mark_execution_receipt,
    seller_ship,
    submit_proof,
    try_verify,
)


@pytest.fixture(autouse=True)
def _clean():
    dv.reset_delivery_sessions()
    yield
    dv.reset_delivery_sessions()


def test_physical_triple_happy_path_food():
    out = demo_complete_physical_flow(
        task_id="task-food-1",
        scene_id="food_delivery",
        seller_agent_id="merchant-1",
        buyer_agent_id="buyer-1",
        logistics_agent_id="rider-1",
        amount=28.0,
    )
    assert out["status"] == "VERIFIED"
    assert out["verified_at"]
    kinds = {e["kind"] for e in out["events"]}
    assert "seller_shipped" in kinds
    assert "logistics_intake_ok" in kinds
    assert "logistics_delivered" in kinds
    assert "buyer_confirmed" in kinds
    assert "delivery_photo_tagged" in out["proofs"]


def test_wrong_item_loss_share():
    sess = create_verification_session(
        task_id="task-wrong",
        scene_id="logistics_delivery",
        seller_agent_id="s1",
        buyer_agent_id="b1",
        logistics_agent_id="l1",
        amount=100.0,
    )
    vid = sess["verification_id"]
    seller_ship(vid, actor_agent_id="s1", ship_proof_hash="shiphash1234567890")
    out = logistics_intake(
        vid, actor_agent_id="l1", item_matches=False, note="货不对版"
    )
    assert out["status"] == "WRONG_ITEM"
    assert out["loss_share"]["logistics_bps"] == 5000
    assert out["loss_share"]["seller_bps"] == 5000
    assert out["liability"] is not None


def test_anti_forge_tag_required_and_validates():
    sess = create_verification_session(
        task_id="task-tag",
        scene_id="food_delivery",
        seller_agent_id="s1",
        buyer_agent_id="b1",
        logistics_agent_id="l1",
        amount=20.0,
    )
    vid = sess["verification_id"]
    seller_ship(vid, actor_agent_id="s1")
    logistics_intake(vid, actor_agent_id="l1", item_matches=True)
    with pytest.raises(DeliveryVerificationError, match="tagged photo"):
        logistics_deliver(
            vid,
            actor_agent_id="l1",
            content_hash="pod_" + "a" * 20,
        )
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
    out = logistics_deliver(
        vid,
        actor_agent_id="l1",
        content_hash="pod_" + "c" * 20,
        nonce=ch["nonce"],
        captured_at=ch["captured_at"],
        geo_hash="gh1",
        tag_hmac=ch["tag_hmac"],
    )
    assert out["status"] == "AWAITING_BUYER_RECEIPT"
    assert out["buyer_silent_deadline"]


def test_buyer_silent_default_after_deadline():
    sess = create_verification_session(
        task_id="task-silent",
        scene_id="food_delivery",
        seller_agent_id="s1",
        buyer_agent_id="b1",
        logistics_agent_id="l1",
        amount=30.0,
    )
    vid = sess["verification_id"]
    seller_ship(vid, actor_agent_id="s1")
    logistics_intake(vid, actor_agent_id="l1", item_matches=True)
    ch = issue_capture_challenge(vid, party_role="logistics")
    logistics_deliver(
        vid,
        actor_agent_id="l1",
        content_hash="pod_" + "d" * 20,
        nonce=ch["nonce"],
        captured_at=ch["captured_at"],
        geo_hash=None,
        tag_hmac=ch["tag_hmac"],
    )
    # Force deadline into the past
    with dv._LOCK:  # noqa: SLF001
        s = dv._SESSIONS[vid]  # noqa: SLF001
        s["buyer_silent_deadline"] = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    out = apply_silent_buyer_default(vid)
    assert out is not None
    assert out["status"] == "VERIFIED"
    kinds = {e["kind"] for e in out["events"]}
    assert "buyer_silent_default" in kinds


def test_silent_blocked_if_chain_incomplete():
    sess = create_verification_session(
        task_id="task-nochain",
        scene_id="food_delivery",
        seller_agent_id="s1",
        buyer_agent_id="b1",
        logistics_agent_id="l1",
    )
    vid = sess["verification_id"]
    seller_ship(vid, actor_agent_id="s1")
    with dv._LOCK:  # noqa: SLF001
        s = dv._SESSIONS[vid]  # noqa: SLF001
        s["status"] = "AWAITING_BUYER_RECEIPT"
        s["buyer_silent_deadline"] = (
            datetime.now(timezone.utc) - timedelta(seconds=5)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out = apply_silent_buyer_default(vid)
    assert out is not None
    assert out["status"] != "VERIFIED"
    assert "不默认确认" in (out.get("note_zh") or "")


def test_ticket_stub_hotel():
    sess = create_verification_session(
        task_id="task-hotel",
        scene_id="hotel_booking",
        seller_agent_id="hotel-1",
        buyer_agent_id="guest-1",
        amount=320.0,
    )
    vid = sess["verification_id"]
    seller_ship(
        vid,
        actor_agent_id="hotel-1",
        meta={"confirmation_code": "HTL-9981"},
    )
    submit_proof(
        vid,
        proof_type="confirmation_code",
        content_hash="conf_" + "e" * 20,
        actor_agent_id="hotel-1",
        party_role="seller",
        meta={"code": "HTL-9981", "stub": True},
    )
    submit_proof(
        vid,
        proof_type="email_receipt",
        content_hash="mail_" + "f" * 20,
        actor_agent_id="hotel-1",
        party_role="seller",
    )
    out = buyer_confirm(vid, actor_agent_id="guest-1", confirm=True)
    assert out["status"] == "VERIFIED"


def test_digital_light_api():
    sess = create_verification_session(
        task_id="task-api",
        scene_id="api_tool_call",
        seller_agent_id="tool-1",
        buyer_agent_id="user-1",
    )
    vid = sess["verification_id"]
    mark_execution_receipt(vid, ok=True)
    submit_proof(
        vid,
        proof_type="request_hash",
        content_hash="req_" + "1" * 20,
        actor_agent_id="tool-1",
        party_role="seller",
    )
    submit_proof(
        vid,
        proof_type="response_hash",
        content_hash="res_" + "2" * 20,
        actor_agent_id="tool-1",
        party_role="seller",
    )
    submit_proof(
        vid,
        proof_type="http_or_tool_status",
        content_hash="st_" + "3" * 20,
        actor_agent_id="tool-1",
        party_role="seller",
    )
    submit_proof(
        vid,
        proof_type="latency_ms",
        content_hash="lat_" + "4" * 20,
        actor_agent_id="tool-1",
        party_role="seller",
    )
    out = try_verify(vid)
    assert out["status"] == "VERIFIED"


def test_logistics_must_be_distinct():
    with pytest.raises(DeliveryVerificationError, match="distinct"):
        create_verification_session(
            task_id="t",
            scene_id="food_delivery",
            seller_agent_id="same",
            buyer_agent_id="b",
            logistics_agent_id="same",
        )


def test_physical_requires_logistics():
    with pytest.raises(DeliveryVerificationError, match="logistics"):
        create_verification_session(
            task_id="t2",
            scene_id="food_delivery",
            seller_agent_id="s",
            buyer_agent_id="b",
        )
