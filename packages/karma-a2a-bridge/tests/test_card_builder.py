import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from card_builder import build_agent_card, build_from_karma_agent
from models import AgentCard


class TestBuildAgentCard:
    def test_build_minimal(self):
        card = build_agent_card(
            agent_id="test_agent_001",
            name="Test Agent",
            description="A test agent",
            capabilities=["karma_settle"],
            endpoint="http://localhost:8080",
        )
        assert isinstance(card, AgentCard)
        assert card.agent_id == "test_agent_001"
        assert card.a2a_version == "1.0"
        assert "karma_settle" in card.capabilities
        assert card.karma.contract_address != ""

    def test_build_with_skills(self):
        card = build_agent_card(
            agent_id="food_agent",
            name="Food Agent",
            description="Order food",
            capabilities=["order_food", "karma_settle"],
            endpoint="http://localhost:8080",
            skills=[{
                "id": "order_food",
                "name": "Order Food",
                "description": "Place food order",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "restaurant": {"type": "string"},
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["restaurant", "items"],
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "total": {"type": "number"},
                    },
                },
            }],
        )
        assert len(card.skills) == 1
        assert card.skills[0].id == "order_food"

    def test_build_from_karma_agent_with_minimal_data(self):
        agent_data = {
            "agent_id": "external_agent_001",
            "name": "External Agent",
            "role": "worker",
            "endpoint_url": "https://external.example.com/a2a",
            "capabilities": ["data_processing"],
        }
        card = build_from_karma_agent(agent_data)
        assert card.agent_id == "external_agent_001"
        assert "data_processing" in card.capabilities
        assert card.endpoint == "https://external.example.com/a2a"
