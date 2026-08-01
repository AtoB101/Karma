from services.intent_discovery import (
    build_discovery_plan,
    parse_intent_for_discovery,
    rank_candidates,
)
from services.requirement_decomposer import decompose_buyer_requirement


def test_parse_intent_food():
    q = parse_intent_for_discovery("帮我点外卖 披萨")
    assert "order_food" in q.capabilities
    assert q.task_type == "commerce.food"


def test_rank_prefers_matching_skill():
    q = parse_intent_for_discovery("book a flight please")
    cards = [
        {
            "agent_id": "hotel",
            "name": "Hotel",
            "capabilities": ["book_hotel", "karma_settle"],
            "skills": [{"id": "book_hotel"}],
            "karma": {"supports_voucher": True},
            "endpoint": "http://h",
        },
        {
            "agent_id": "flight",
            "name": "Flight",
            "capabilities": ["book_flight", "karma_settle"],
            "skills": [{"id": "book_flight"}],
            "karma": {"supports_voucher": True, "supports_attestation": True},
            "endpoint": "http://f",
        },
    ]
    ranked = rank_candidates(cards, q, limit=5)
    assert ranked[0]["agent_id"] == "flight"
    plan = build_discovery_plan(query=q, candidates=ranked, buyer_identity_id="buyer1")
    assert plan["trade_launch_hint"]["seller_identity_id"] == "flight"
    assert plan["trade_launch_hint"]["a2a_skill"] == "book_flight"


def test_decomposer_includes_discovery_tags():
    spec = decompose_buyer_requirement(
        requirement_text="translate this document",
        seller_identity_id="seller",
        buyer_identity_id="buyer",
    )
    assert "discovery_capabilities" in spec
    assert "karma_settle" in spec["discovery_capabilities"]
    assert spec["task_type"] == "api.translate"
