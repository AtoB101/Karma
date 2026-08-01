"""Agent boundary standard — capability / responsibility / confirmation."""
from __future__ import annotations

import pytest

from services import agent_boundary as ab
from services.agent_boundary import (
    boundary_digest,
    load_boundary_catalog,
    materialize_agent_boundary,
    materialize_from_onboarding_result,
    scenes_from_capabilities,
)
from services.agent_onboarding_template import materialize_onboarding


@pytest.fixture(autouse=True)
def _reset():
    ab.load_boundary_catalog.cache_clear()
    ab.clear_agent_boundaries()
    yield
    ab.clear_agent_boundaries()
    ab.load_boundary_catalog.cache_clear()


def test_catalog_loads():
    cat = load_boundary_catalog()
    assert cat["schema_version"] == "karma-agent-boundary-v1"
    assert "capability_boundary" in cat["boundary_parts"]
    assert "responsibility_boundary" in cat["boundary_parts"]
    assert "confirmation_boundary" in cat["boundary_parts"]


def test_scenes_from_capabilities():
    assert "food_delivery" in scenes_from_capabilities(["order_food", "karma_settle"])
    assert "ride_hailing" in scenes_from_capabilities(["industry:ride_hailing"])


def test_merchant_template_boundary_complete():
    mat = materialize_onboarding(
        profile_id="merchant",
        answers={
            "display_name": "面馆Bot",
            "industry_ids": ["food_delivery"],
            "use_example_service_specs": True,
            "service_targets": ["consumer"],
            "service_area": {"mode": "local", "regions": ["上海"]},
            "capability_summary": "简餐外卖",
            "boundaries": "不做跨境冷链",
        },
        agent_id="merchant-food-bound",
    )
    boundary = materialize_from_onboarding_result(mat, agent_id="merchant-food-bound")
    assert boundary["boundary_complete"] is True
    assert boundary["scene_ids"] == ["food_delivery"]
    assert boundary["capability_boundary"]["service_specs"]["food_delivery"]
    assert boundary["capability_boundary"]["do_not"]
    assert boundary["responsibility_boundary"]["compliance_flags"]["no_fund_custody"] is True
    # acknowledged defaults false until P1 ack is recorded
    assert boundary["responsibility_boundary"]["acknowledged"] is False
    conf = boundary["confirmation_boundary"]
    assert conf["role"] == "seller"
    assert "accept_order" in (conf["must_confirm_steps"] + conf["policy_auto_steps"] + conf["auto_ok_steps"])
    assert "execute_service" in conf["auto_ok_steps"]
    digest = boundary_digest(boundary)
    assert digest["boundary_complete"] is True
    assert digest["primary_scene_id"] == "food_delivery"


def test_user_boundary_is_buyer_confirm():
    mat = materialize_onboarding(
        profile_id="user",
        answers={"display_name": "AliceBot"},
        agent_id="user-bound-1",
    )
    boundary = materialize_from_onboarding_result(mat, agent_id="user-bound-1")
    assert boundary["boundary_complete"] is True
    assert boundary["confirmation_boundary"]["role"] == "buyer"


def test_plain_connect_incomplete_but_readable():
    boundary = materialize_agent_boundary(
        agent_id="plain-1",
        name="Plain Worker",
        karma_role="worker",
        capabilities=["order_food", "karma_settle"],
    )
    assert boundary["boundary_complete"] is False
    assert "service_specs" in boundary["completeness_gaps"]
    assert "food_delivery" in boundary["scene_ids"]
    assert boundary["confirmation_boundary"]["must_confirm_steps"]


def test_save_and_get_boundary():
    b = materialize_agent_boundary(
        agent_id="store-1",
        karma_role="worker",
        capabilities=["book_ride"],
        profile_id="merchant",
        profile_card={
            "profile_id": "merchant",
            "industry_ids": ["ride_hailing"],
            "service_specs": {
                "ride_hailing": {
                    "service_content": ["网约车"],
                    "boundaries": "不做跨城拼车",
                }
            },
            "boundaries": "不做跨城拼车",
        },
    )
    # Still may miss full required_service_spec fields — completeness uses presence
    ab.save_agent_boundary("store-1", b)
    loaded = ab.get_agent_boundary("store-1")
    assert loaded is not None
    assert loaded["agent_id"] == "store-1"
    assert loaded["scene_ids"] == ["ride_hailing"]


def test_save_rejects_forged_complete_flag():
    forged = {
        "schema_version": "karma-agent-boundary-v1",
        "agent_id": "forge-1",
        "profile_id": "merchant",
        "karma_role": "worker",
        "scene_ids": [],
        "boundary_complete": True,
        "completeness_gaps": [],
        "capability_boundary": {
            "capabilities": ["karma_settle"],
            "service_specs": {},
            "do_not": "",
        },
        "responsibility_boundary": {"acknowledged": True},
        "confirmation_boundary": {"role": "seller"},
    }
    ab.save_agent_boundary("forge-1", forged)
    loaded = ab.get_agent_boundary("forge-1")
    assert loaded is not None
    assert loaded["boundary_complete"] is False
    assert "scene_ids" in loaded["completeness_gaps"]
