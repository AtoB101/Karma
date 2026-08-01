"""Human confirmation policy — real-scene AUTO vs OWNER_CONFIRM split."""
from __future__ import annotations

import pytest

from services import human_confirmation_policy as hcp
from services.human_confirmation_policy import (
    ConfirmationPolicyError,
    assert_step_allowed,
    create_confirmation_session,
    decide_confirmation_session,
    load_policy_catalog,
    plan_confirmations,
    resolve_gate,
    task_type_to_scene_id,
)


@pytest.fixture(autouse=True)
def _reset():
    hcp.load_policy_catalog.cache_clear()
    hcp.reset_confirmation_sessions()
    yield
    hcp.reset_confirmation_sessions()
    hcp.load_policy_catalog.cache_clear()


def test_catalog_has_daily_and_b2b_scenes():
    cat = load_policy_catalog()
    assert cat["schema_version"] == "karma-human-confirmation-v1"
    scenes = cat["scenes"]
    for sid in (
        "ride_hailing",
        "food_delivery",
        "hotel_booking",
        "flight_booking",
        "b2b_procurement",
        "data_api_billing",
        "api_tool_call",
    ):
        assert sid in scenes


def test_task_type_mapping():
    assert task_type_to_scene_id("commerce.food") == "food_delivery"
    assert task_type_to_scene_id("commerce.ride") == "ride_hailing"
    assert task_type_to_scene_id("commerce.hotel") == "hotel_booking"
    assert task_type_to_scene_id("commerce.flight") == "flight_booking"
    assert task_type_to_scene_id("api.translate") == "api_tool_call"


def test_food_buyer_must_confirm_order_not_tracking():
    plan = plan_confirmations(scene_id="food_delivery", role="buyer")
    must = {x["step"] for x in plan["must_confirm"]}
    auto = {x["step"] for x in plan["auto_ok"]}
    assert "accept_order" in must
    assert "select_offer" in must
    assert "discover" in auto
    assert "execute_service" in auto
    assert "submit_delivery_proof" in auto


def test_food_seller_accept_is_policy_auto():
    gate = resolve_gate(scene_id="food_delivery", role="seller", step="accept_order")
    assert gate["mode"] == "POLICY_AUTO"
    assert gate["needs_owner_confirmation"] is True
    gate2 = resolve_gate(
        scene_id="food_delivery",
        role="seller",
        step="accept_order",
        policy_auto_allowed=True,
    )
    assert gate2["effective_mode"] == "AUTO"
    assert gate2["needs_owner_confirmation"] is False


def test_b2b_seller_accept_always_owner():
    gate = resolve_gate(scene_id="b2b_procurement", role="seller", step="accept_order")
    assert gate["mode"] == "OWNER_CONFIRM"
    assert gate["needs_owner_confirmation"] is True


def test_session_decide_and_assert():
    created = create_confirmation_session(
        scene_id="ride_hailing",
        role="buyer",
        step="accept_order",
        owner_agent_id="owner-1",
        context={"pickup": "A", "dropoff": "B", "amount": 28, "currency": "USDC", "eta": 5},
    )
    assert created["skipped"] is False
    assert created["status"] == "PENDING"
    assert created["max_amount"] == 28.0
    assert "是否确认" in created["prompt_zh"]

    with pytest.raises(ConfirmationPolicyError):
        assert_step_allowed(
            scene_id="ride_hailing",
            role="buyer",
            step="accept_order",
            confirmation_session_id=created["session_id"],
            expected_owner_agent_id="owner-1",
            amount=28.0,
        )

    decided = decide_confirmation_session(
        created["session_id"], confirm=True, actor_agent_id="owner-1"
    )
    assert decided["status"] == "CONFIRMED"
    assert decided["can_proceed"] is True

    ok = assert_step_allowed(
        scene_id="ride_hailing",
        role="buyer",
        step="accept_order",
        confirmation_session_id=created["session_id"],
        expected_owner_agent_id="owner-1",
        amount=28.0,
        consume=True,
    )
    assert ok["allowed"] is True
    assert ok["consumed"] is True

    # Single-use: cannot replay
    with pytest.raises(ConfirmationPolicyError, match="USED"):
        assert_step_allowed(
            scene_id="ride_hailing",
            role="buyer",
            step="accept_order",
            confirmation_session_id=created["session_id"],
            expected_owner_agent_id="owner-1",
            amount=28.0,
        )


def test_auto_step_skips_session():
    out = create_confirmation_session(
        scene_id="food_delivery",
        role="buyer",
        step="discover",
        owner_agent_id="owner-1",
    )
    assert out["skipped"] is True
    assert out["can_proceed"] is True


def test_wrong_actor_cannot_decide():
    created = create_confirmation_session(
        scene_id="hotel_booking",
        role="buyer",
        step="cancel",
        owner_agent_id="owner-a",
    )
    with pytest.raises(ConfirmationPolicyError, match="owner_agent_id"):
        decide_confirmation_session(
            created["session_id"], confirm=True, actor_agent_id="intruder"
        )


def test_decide_requires_actor_agent_id():
    created = create_confirmation_session(
        scene_id="food_delivery",
        role="buyer",
        step="accept_order",
        owner_agent_id="owner-b",
        context={"amount": 10},
    )
    with pytest.raises(ConfirmationPolicyError, match="actor_agent_id is required"):
        decide_confirmation_session(created["session_id"], confirm=True)


def test_assert_binds_owner_and_amount():
    created = create_confirmation_session(
        scene_id="food_delivery",
        role="buyer",
        step="accept_order",
        owner_agent_id="buyer-x",
        context={"amount": 12},
    )
    decide_confirmation_session(created["session_id"], confirm=True, actor_agent_id="buyer-x")
    with pytest.raises(ConfirmationPolicyError, match="owner"):
        assert_step_allowed(
            scene_id="food_delivery",
            role="buyer",
            step="accept_order",
            confirmation_session_id=created["session_id"],
            expected_owner_agent_id="buyer-other",
            amount=12.0,
            consume=False,
        )
    with pytest.raises(ConfirmationPolicyError, match="exceeds confirmed"):
        assert_step_allowed(
            scene_id="food_delivery",
            role="buyer",
            step="accept_order",
            confirmation_session_id=created["session_id"],
            expected_owner_agent_id="buyer-x",
            amount=50.0,
            consume=False,
        )
    ok = assert_step_allowed(
        scene_id="food_delivery",
        role="buyer",
        step="accept_order",
        confirmation_session_id=created["session_id"],
        expected_owner_agent_id="buyer-x",
        amount=12.0,
        consume=True,
    )
    assert ok["allowed"] is True
