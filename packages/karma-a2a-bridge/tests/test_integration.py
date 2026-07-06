"""
Integration test: Full A2A discover → negotiate → Karma settlement flow
Run: pytest tests/test_integration.py -v
"""
import sys, os, json, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from card_builder import build_agent_card, build_from_karma_agent
from handoff_bridge import a2a_task_to_voucher, a2a_task_to_handoff
from models import AgentCard, A2ATaskRequest
from agent_sdk import build_card, search_agents, A2AClient


class TestIntegration:
    """Full flow: discover agents → negotiate task → create voucher → generate handoff"""

    def test_01_discover_agents(self):
        """Step 1: Agent Card discovery via Registry search (mocked)"""
        food_card = build_card(
            agent_id="food_agent_001",
            name="Karma Food Agent",
            description="Food delivery with Karma settlement",
            capabilities=["order_food", "karma_settle"],
            endpoint="http://localhost:8080",
            skills=[{
                "id": "order_food",
                "name": "Order Food",
                "description": "Place a food order",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "restaurant": {"type": "string"},
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["restaurant", "items"],
                },
                "output_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
            }],
        )
        assert food_card["agent_id"] == "food_agent_001"
        assert "karma_settle" in food_card["capabilities"]
        assert food_card["karma"]["contract_address"] != ""

        # Simulate registry search result
        results = [food_card]
        assert len(results) == 1
        assert results[0]["agent_id"] == "food_agent_001"

    def test_02_negotiate_task(self):
        """Step 2: A2A task negotiation between agents"""
        task = A2ATaskRequest(
            task_id=f"int_test_{uuid.uuid4().hex[:8]}",
            skill="order_food",
            params={"restaurant": "Sushi Bar", "items": ["Salmon Roll"]},
            requester_id="user_agent_demo",
        )
        assert task.skill == "order_food"
        assert "restaurant" in task.params

        # Agent verifies skill is supported
        supported_skills = ["order_food", "track_delivery"]
        assert task.skill in supported_skills, f"Skill {task.skill} not supported"

    def test_03_create_karma_voucher(self):
        """Step 3: A2A negotiated task → Karma Voucher"""
        task = A2ATaskRequest(
            task_id="voucher_test_001",
            skill="order_food",
            params={"restaurant": "Pizza Place", "items": ["Margherita"]},
            requester_id="user_agent_demo",
        )
        voucher = a2a_task_to_voucher(
            task,
            seller_id="food_agent_001",
            amount=24.50,
            buyer_id="user_agent_demo",
        )
        assert voucher["voucher_id"].startswith("a2a_")
        assert voucher["amount"] == 24.50
        assert voucher["currency"] == "USDC"
        assert voucher["seller_id"] == "food_agent_001"
        assert voucher["buyer_id"] == "user_agent_demo"
        assert voucher["metadata"]["task_id"] == "voucher_test_001"
        assert voucher["metadata"]["source"] == "a2a_bridge"

    def test_04_generate_handoff(self):
        """Step 4: A2A task → Karma handoff.json"""
        task = A2ATaskRequest(
            task_id="handoff_test_001",
            skill="book_flight",
            params={"from": "NYC", "to": "LAX", "date": "2026-08-15"},
        )
        handoff = a2a_task_to_handoff(
            task,
            buyer_id="user_agent_demo",
            seller_id="flight_agent_001",
        )
        assert handoff["trace_id"] == "handoff_test_001"
        assert handoff["buyer_identity_id"] == "user_agent_demo"
        assert handoff["seller_identity_id"] == "flight_agent_001"
        assert handoff["authorization"]["a2a_negotiated"] is True
        assert handoff["voucher_id"].startswith("vcr_")
        assert handoff["skill"] == "book_flight"

    def test_05_full_flow_food_ordering(self):
        """End-to-end: discover → negotiate → voucher → handoff"""
        # 1. Discover
        food_card = build_card(
            agent_id="food_agent_001",
            name="Karma Food Agent",
            description="Food delivery",
            capabilities=["order_food", "karma_settle"],
            endpoint="http://localhost:8080",
        )
        assert "karma_settle" in food_card["capabilities"]

        # 2. Negotiate
        params = {"restaurant": "Burger Place", "items": ["Cheeseburger", "Fries"]}
        skill = "order_food"
        task = A2ATaskRequest(
            task_id=f"full_{uuid.uuid4().hex[:8]}",
            skill=skill,
            params=params,
            requester_id="user_demo",
        )
        assert task.skill in food_card["capabilities"]

        # 3. Create voucher
        voucher = a2a_task_to_voucher(task, seller_id="food_agent_001", amount=15.50)
        assert voucher["amount"] == 15.50

        # 4. Generate handoff
        handoff = a2a_task_to_handoff(task, buyer_id="user_demo", seller_id="food_agent_001")
        assert handoff["voucher_id"] is not None

        # 5. Verify complete flow data
        flow = {
            "discovery": {"agent": food_card["name"], "capabilities": food_card["capabilities"]},
            "negotiation": {"skill": skill, "params": params},
            "voucher": {"id": voucher["voucher_id"], "amount": voucher["amount"]},
            "handoff": handoff,
        }
        assert flow["voucher"]["amount"] == 15.50
        assert flow["handoff"]["seller_identity_id"] == "food_agent_001"

    def test_06_agent_card_from_karma_api(self):
        """Agent Card built from existing Karma API agent data"""
        karma_agent = {
            "agent_id": "karma_worker_001",
            "name": "Karma Worker",
            "role": "worker",
            "endpoint_url": "https://karma-network.ai/a2a/worker",
            "capabilities": ["data_processing", "karma_settle"],
            "is_active": True,
        }
        card = build_from_karma_agent(karma_agent)
        assert card.agent_id == "karma_worker_001"
        assert "data_processing" in card.capabilities
        assert card.endpoint == "https://karma-network.ai/a2a/worker"
        assert "a2a" in card.protocols
        assert "karma" in card.protocols

    def test_07_multi_agent_discovery(self):
        """Multiple agents across different domains"""
        agents = [
            build_card("food_01", "Food A", "Food delivery", ["order_food", "karma_settle"], "http://food:8080"),
            build_card("flight_01", "Flight A", "Flight booking", ["book_flight", "karma_settle"], "http://flight:8081"),
            build_card("hotel_01", "Hotel A", "Hotel booking", ["book_hotel", "karma_settle"], "http://hotel:8082"),
        ]
        assert len(agents) == 3

        # Search for food agents
        food_agents = [a for a in agents if "order_food" in a["capabilities"]]
        assert len(food_agents) == 1
        assert food_agents[0]["agent_id"] == "food_01"

        # Search for karma_settle agents
        karma_agents = [a for a in agents if "karma_settle" in a["capabilities"]]
        assert len(karma_agents) == 3
