"""Important Fields Standard — catalog, hash, bilateral match."""
from __future__ import annotations

import copy

import pytest

from services import important_fields_standard as ifs
from services.important_fields_standard import (
    ImportantFieldsError,
    example_for_scene,
    fields_hash,
    get_scene,
    list_scene_groups,
    list_scenes,
    load_catalog,
    match_submissions,
    validate_fields,
)


@pytest.fixture(autouse=True)
def _reload_catalog():
    ifs.load_catalog.cache_clear()
    yield
    ifs.load_catalog.cache_clear()


def test_catalog_groups_cover_market_daily_b2b():
    cat = load_catalog()
    assert cat["schema_version"] == "karma-important-fields-v1"
    groups = list_scene_groups()["counts"]
    assert groups["market_vertical"] == 11
    assert groups["daily_commerce"] == 4
    assert groups["b2b_digital"] == 3
    assert groups["all_primary"] == 18

    market = [s["scene_id"] for s in list_scenes(group="market_vertical")]
    assert market[0] == "software_development"
    assert market[-1] == "healthcare_medical"

    daily = {s["scene_id"] for s in list_scenes(group="daily_commerce")}
    assert daily == {"ride_hailing", "hotel_booking", "food_delivery", "flight_booking"}

    b2b = {s["scene_id"] for s in list_scenes(group="b2b_digital")}
    assert b2b == {"b2b_procurement", "data_api_billing", "api_tool_call"}


def test_extensions_include_legal_and_custom():
    scenes = list_scenes(include_extensions=True, group="extension")
    ids = {s["scene_id"] for s in scenes}
    assert ids == {"legal_compliance", "custom_service"}


def test_daily_examples_validate_and_match():
    for scene_id in ("ride_hailing", "hotel_booking", "food_delivery", "flight_booking"):
        fields = example_for_scene(scene_id)["fields"]
        assert validate_fields(scene_id, fields) == []
        result = match_submissions(scene_id, fields, copy.deepcopy(fields))
        assert result["status"] == "MATCHED", scene_id


def test_b2b_api_billing_and_procurement():
    for scene_id in ("b2b_procurement", "data_api_billing", "api_tool_call"):
        ex = example_for_scene(scene_id)
        assert validate_fields(scene_id, ex["fields"]) == []
        assert len(ex["fields_hash"]) == 64


def test_example_validates_and_stable_hash():
    ex = example_for_scene("content_creation")
    fields = ex["fields"]
    assert validate_fields("content_creation", fields) == []
    h1 = fields_hash(fields)
    h2 = fields_hash(copy.deepcopy(fields))
    assert h1 == h2 == ex["fields_hash"]
    assert len(h1) == 64


def test_match_when_both_sides_identical():
    fields = example_for_scene("logistics_delivery")["fields"]
    result = match_submissions("logistics_delivery", fields, copy.deepcopy(fields))
    assert result["status"] == "MATCHED"
    assert result["buyer_fields_hash"] == result["seller_fields_hash"]
    assert result["diff"] == []
    assert "commitment_hint" in result


def test_countered_with_diff_on_mismatch():
    buyer = example_for_scene("design_creative")["fields"]
    seller = copy.deepcopy(buyer)
    seller["amount"] = "99.00"
    result = match_submissions("design_creative", buyer, seller)
    assert result["status"] == "COUNTERED"
    paths = {d["path"] for d in result["diff"]}
    assert "amount" in paths


def test_amount_must_be_string():
    fields = example_for_scene("education_training")["fields"]
    fields["amount"] = 120.0  # type: ignore[assignment]
    errors = validate_fields("education_training", fields)
    assert any("decimal string" in e for e in errors)


def test_unknown_scene():
    with pytest.raises(ImportantFieldsError):
        get_scene("not_a_real_scene")


def test_financial_requires_no_custody_ack():
    fields = example_for_scene("financial_services")["fields"]
    fields["scene"]["no_custody_ack"] = False
    errors = validate_fields("financial_services", fields)
    assert any("no_custody_ack" in e for e in errors)


def test_flight_aligns_verifier_proof_fields():
    scene = get_scene("flight_booking")
    assert scene.get("service_type") == "flight_booking"
    proofs = set(scene["default_required_proof_fields"])
    assert {"flight_number", "departure_time", "arrival_time"} <= proofs
