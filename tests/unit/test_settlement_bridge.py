"""Settlement bridge + economy surface unit tests."""
from __future__ import annotations

import os

from services.economy_surface import surface_payload
from services.settlement_bridge import fee_bridge_settle_plan, order_id_bytes32


def test_order_id_bytes32():
    assert order_id_bytes32(7) == "0x" + (7).to_bytes(32, "big").hex()
    assert len(order_id_bytes32(1)) == 66


def test_fee_bridge_settle_plan_self_deal_and_builder():
    plan = fee_bridge_settle_plan(
        binding_id=42,
        buyer="0xAAAAaaaaAAAAaaaaAAAAaaaaAAAAaaaaAAAAaaaa",
        seller="0xAAAAaaaaAAAAaaaaAAAAaaaaAAAAaaaaAAAAaaaa",
        builder_address="0xBBBBbbbbBBBBbbbbBBBBbbbbBBBBbbbbBBBBbbbb",
        amount_usdc="100",
    )
    assert plan["self_deal"] is True
    assert plan["developer"] == "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert plan["orderId"] == order_id_bytes32(42)
    assert plan["fee_bridge"]["collectAndRecord"]["feeUsdc"] == "MUST_EQUAL_quoteFee_RESULT"
    assert plan["steps"][0]["required"] is True


def test_economy_surface_shape(monkeypatch):
    monkeypatch.setenv("KARMA8_ECONOMY_HOST", "https://economy.example.com")
    monkeypatch.setenv("FEE_BRIDGE", "0xfee")
    monkeypatch.setenv("KARMA_BILATERAL", "0xbil")
    body = surface_payload("0xAbC")
    assert body["embed_url"] == "https://economy.example.com/?view=miniapp"
    assert "tab=rewards" in body["embed_rewards_url"]
    assert body["contracts"]["feeBridge"] == "0xfee"
    assert body["contracts"]["karmaBilateral"] == "0xbil"
    assert body["embed"]["includesVerificationEngine"] is False
    assert "https://web.telegram.org" in body["miniapp_origin_for_karma8"]
