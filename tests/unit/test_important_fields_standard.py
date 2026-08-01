"""Important Fields Standard — catalog, hash, bilateral match."""
from __future__ import annotations

import copy

import pytest

from services.important_fields_standard import (
    ImportantFieldsError,
    example_for_scene,
    fields_hash,
    get_scene,
    list_scenes,
    load_catalog,
    match_submissions,
    validate_fields,
)


def test_catalog_has_eleven_market_scenes():
    cat = load_catalog()
    scenes = list_scenes(include_extensions=False)
    assert cat["schema_version"] == "karma-important-fields-v1"
    assert len(scenes) == 11
    ids = [s["scene_id"] for s in scenes]
    assert ids[0] == "software_development"
    assert ids[-1] == "healthcare_medical"
    assert "legal_compliance" not in ids


def test_extensions_include_legal_and_custom():
    scenes = list_scenes(include_extensions=True)
    ids = {s["scene_id"] for s in scenes}
    assert "legal_compliance" in ids
    assert "custom_service" in ids
    assert len(scenes) == 13


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
