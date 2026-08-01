"""Agent onboarding template — materialize + suggest industries."""
from __future__ import annotations

import pytest

from services import agent_onboarding_template as obt
from services.agent_onboarding_template import (
    OnboardingError,
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


def test_catalog_has_three_profiles_and_industries():
    cat = load_onboarding_catalog()
    assert cat["schema_version"] == "karma-agent-onboarding-v1"
    ids = {p["profile_id"] for p in list_profiles()}
    assert ids == {"user", "merchant", "enterprise"}
    assert len(list_industries()) == 18
    daily = list_industries(group="daily_commerce")
    assert {d["industry_id"] for d in daily} >= {
        "ride_hailing",
        "hotel_booking",
        "food_delivery",
        "flight_booking",
    }


def test_user_materialize_minimal():
    out = materialize_onboarding(
        profile_id="user",
        answers={"display_name": "AliceBot"},
    )
    assert out["agent_connect"]["role"] == "client"
    assert "karma_discover_for_intent" in out["agent_connect"]["capabilities"]
    assert out["profile_card"]["description"]


def test_merchant_food_delivery_materialize():
    out = materialize_onboarding(
        profile_id="merchant",
        answers={
            "display_name": "NoonBowl",
            "industry_ids": ["food_delivery"],
            "service_targets": ["consumer", "agent"],
            "business_hours": {"timezone": "Asia/Shanghai", "weekly": "Mon-Sun 10:00-22:00"},
            "service_area": {"mode": "physical", "regions": ["CN-SH"]},
            "capability_summary": "同城外卖配送",
            "boundaries": "不做跨境",
        },
    )
    caps = out["agent_connect"]["capabilities"]
    assert "food_delivery" in caps
    assert "karma_settle" in caps
    assert "外卖" in out["profile_card"]["description"] or "food" in out["profile_card"]["description"].lower()


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
                "business_hours": {"24_7": True, "timezone": "UTC"},
                "service_area": {"mode": "digital"},
                "capability_summary": "对账",
                "boundaries": "不做托管",
                "compliance_flags": {"no_fund_custody": False},
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
