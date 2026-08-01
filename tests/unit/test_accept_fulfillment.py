"""P6 accept fulfillment — TTL cancel, non-confirm ledger, liability, tiers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services import accept_fulfillment as af
from services import human_confirmation_policy as hcp
from services.accept_fulfillment import (
    arm_post_confirm_liability,
    check_interaction_seller_timeout,
    compute_breach_compensation,
    process_expired_seller_session,
    record_seller_confirm,
    record_seller_non_confirm,
    scene_accept_ttl_seconds,
    seller_requires_forced_confirm,
    seller_risk_profile,
)
from services.human_confirmation_policy import create_confirmation_session


@pytest.fixture(autouse=True)
def _clean():
    af.reset_accept_ledger()
    hcp.reset_confirmation_sessions()
    yield
    af.reset_accept_ledger()
    hcp.reset_confirmation_sessions()


def test_scene_ttl_food_vs_b2b():
    assert scene_accept_ttl_seconds("food_delivery") == 300
    assert scene_accept_ttl_seconds("ride_hailing") == 120
    assert scene_accept_ttl_seconds("b2b_procurement") == 86400


def test_timeout_records_and_elevates_after_three():
    seller = "seller-slow"
    for i in range(3):
        record_seller_non_confirm(
            seller_id=seller,
            scene_id="b2b_procurement",
            interaction_ref=f"po:{i}",
            reason="timeout",
            session_id=f"cfm_timeout_{i}",
            amount=100.0,
        )
    profile = seller_risk_profile(seller, scene_id="b2b_procurement")
    assert profile["non_confirm_count"] == 3
    assert profile["verification_tier"] == "elevated"
    assert profile["bond_multiplier"] == 1.5
    assert profile["force_owner_confirm"] is True
    assert seller_requires_forced_confirm(seller, "food_delivery") is True


def test_reputation_delta_is_slight():
    out = record_seller_non_confirm(
        seller_id="s1",
        scene_id="ride_hailing",
        interaction_ref="r1",
        reason="timeout",
        session_id="cfm_r1",
    )
    assert -5.0 <= out["reputation_delta"] <= -1.0
    assert out["profile"]["reputation_delta_total"] == out["reputation_delta"]


def test_post_confirm_liability_scales_with_bond_multiplier():
    seller = "seller-bad"
    for i in range(7):
        record_seller_non_confirm(
            seller_id=seller,
            scene_id="manufacturing",
            interaction_ref=f"m:{i}",
            reason="timeout",
            session_id=f"cfm_m_{i}",
        )
    base = arm_post_confirm_liability(
        seller_id="clean-seller",
        scene_id="manufacturing",
        amount=1000.0,
    )
    scaled = arm_post_confirm_liability(
        seller_id=seller,
        scene_id="manufacturing",
        amount=1000.0,
    )
    assert scaled["bond_multiplier"] == 2.5
    assert scaled["effective_bond_bps"] > base["effective_bond_bps"]
    assert scaled["compensation_amount"] > base["compensation_amount"]
    assert scaled["liability_armed"] is True


def test_confirm_arms_liability():
    out = record_seller_confirm(
        seller_id="seller-ok",
        scene_id="hotel_booking",
        interaction_ref="h1",
        session_id="cfm_h1",
        amount=320.0,
    )
    assert out["breach_liability"]["liability_armed"] is True
    assert out["breach_liability"]["compensation_amount"] > 0


def test_expired_seller_session_cancels():
    sess = create_confirmation_session(
        scene_id="b2b_procurement",
        role="seller",
        step="accept_order",
        owner_agent_id="seller-x",
        context={"amount": 1500, "title": "PO"},
        interaction_ref="po:ttl",
        ttl_seconds=60,
    )
    sid = sess["session_id"]
    # Force expiry
    with hcp._LOCK:  # noqa: SLF001
        obj = hcp._SESSIONS[sid]  # noqa: SLF001
        obj.expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=5)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    cancelled = process_expired_seller_session(sid)
    assert cancelled is not None
    assert cancelled["status"] == "cancelled_seller_timeout"
    assert cancelled["recorded"]["profile"]["timeout_count"] == 1

    # fulfill-style check
    hit = check_interaction_seller_timeout(
        seller_id="seller-x",
        interaction_ref="po:ttl",
        scene_id="b2b_procurement",
        session_id=sid,
    )
    assert hit is not None
    assert hit["status"] == "cancelled_seller_timeout"


def test_idempotent_timeout_record():
    a = record_seller_non_confirm(
        seller_id="s",
        scene_id="api_tool_call",
        interaction_ref="i",
        reason="timeout",
        session_id="same-session",
    )
    b = record_seller_non_confirm(
        seller_id="s",
        scene_id="api_tool_call",
        interaction_ref="i",
        reason="timeout",
        session_id="same-session",
    )
    assert a["idempotent"] is False
    assert b["idempotent"] is True
    assert seller_risk_profile("s")["non_confirm_count"] == 1


def test_breach_quote_fraction():
    q = compute_breach_compensation(
        seller_id="s",
        scene_id="flight_booking",
        amount=500.0,
        breach_fraction=0.5,
    )
    full = compute_breach_compensation(
        seller_id="s",
        scene_id="flight_booking",
        amount=500.0,
        breach_fraction=1.0,
    )
    assert q["compensation_due"] == pytest.approx(full["compensation_due"] * 0.5)


def test_elevated_shortens_ttl():
    seller = "seller-elev"
    for i in range(3):
        record_seller_non_confirm(
            seller_id=seller,
            scene_id="food_delivery",
            interaction_ref=f"f{i}",
            reason="reject",
            session_id=f"cfm_f{i}",
        )
    base = scene_accept_ttl_seconds("food_delivery")
    scaled = scene_accept_ttl_seconds("food_delivery", seller_id=seller)
    assert scaled < base
    assert scaled >= 60
