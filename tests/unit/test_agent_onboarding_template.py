"""Agent onboarding template — hard service specs + materialize."""
from __future__ import annotations

import pytest

from services import agent_onboarding_template as obt
from services.agent_onboarding_template import (
    OnboardingError,
    get_industry,
    list_industries,
    list_profiles,
    load_onboarding_catalog,
    materialize_onboarding,
    suggest_industries_for_text,
)
from services.agent_profile_store import clear_profile_cards, get_profile_card, save_profile_card


@pytest.fixture(autouse=True)
def _reload():
    obt.load_onboarding_catalog.cache_clear()
    clear_profile_cards()
    yield
    obt.load_onboarding_catalog.cache_clear()
    clear_profile_cards()


def test_catalog_has_hard_specs_for_all_industries():
    cat = load_onboarding_catalog()
    assert cat["schema_version"] == "karma-agent-onboarding-v1"
    assert {p["profile_id"] for p in list_profiles()} == {"user", "merchant", "enterprise"}
    inds = list_industries()
    assert len(inds) == 18
    for ind in inds:
        assert ind.get("required_service_spec"), ind["industry_id"]
        assert ind.get("example_service_spec"), ind["industry_id"]
        paths = {r["path"] for r in ind["required_service_spec"]}
        assert "service_content" in paths
        joined = " ".join(paths)
        assert "pricing" in joined
        assert "business_hours" in paths


def test_daily_commerce_hard_metrics_present():
    ride = get_industry("ride_hailing")
    paths = {r["path"] for r in ride["required_service_spec"]}
    assert "sla.pickup_eta_max_minutes" in paths
    assert "pricing.base_fare" in paths
    assert "service_area.cities" in paths
    food = get_industry("food_delivery")
    fpaths = {r["path"] for r in food["required_service_spec"]}
    assert "service_area.radius_km" in fpaths
    assert "sla.deliver_max_minutes" in fpaths
    assert "pricing.min_order_amount" in fpaths


def test_user_materialize_minimal():
    out = materialize_onboarding(profile_id="user", answers={"display_name": "AliceBot"})
    assert out["agent_connect"]["role"] == "client"
    assert out["profile_card"]["service_specs"] == {}


def test_merchant_bootstraps_example_hard_specs():
    out = materialize_onboarding(
        profile_id="merchant",
        answers={
            "display_name": "NoonBowl",
            "industry_ids": ["food_delivery"],
            "service_targets": ["consumer", "agent"],
            "capability_summary": "同城外卖",
            "use_example_service_specs": True,
        },
    )
    spec = out["profile_card"]["service_specs"]["food_delivery"]
    assert spec["sla"]["deliver_max_minutes"] == 45
    assert spec["pricing"]["delivery_fee"] == "5.00"
    assert "boundaries" in spec


def test_incomplete_hard_spec_rejected():
    with pytest.raises(OnboardingError, match="service_specs.food_delivery"):
        materialize_onboarding(
            profile_id="merchant",
            answers={
                "display_name": "BadShop",
                "industry_ids": ["food_delivery"],
                "service_targets": ["consumer"],
                "capability_summary": "x",
                "boundaries": "y",
                "use_example_service_specs": False,
                "service_specs": {
                    "food_delivery": {
                        "service_content": ["外卖"],
                        # missing pricing/sla/area/hours on purpose
                    }
                },
            },
        )


def test_enterprise_financial_requires_no_custody():
    with pytest.raises(OnboardingError, match="no_fund_custody"):
        materialize_onboarding(
            profile_id="enterprise",
            answers={
                "display_name": "Acme Finance Ops",
                "enterprise_type": "other",
                "trade_side": ["sell"],
                "industry_ids": ["financial_services"],
                "service_targets": ["business"],
                "capability_summary": "对账",
                "boundaries": "不做托管",
                "compliance_flags": {"no_fund_custody": False},
                "use_example_service_specs": True,
            },
        )


def test_suggest_industries_from_chinese_text():
    rows = suggest_industries_for_text("我是酒店预订助手，也能订机票", limit=5)
    ids = {r["industry_id"] for r in rows}
    assert "hotel_booking" in ids
    assert "flight_booking" in ids


def test_profile_card_store():
    save_profile_card("agent-1", {"profile_id": "merchant", "description": "x"})
    assert get_profile_card("agent-1")["description"] == "x"
