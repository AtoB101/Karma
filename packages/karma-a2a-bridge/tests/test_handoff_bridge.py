import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from handoff_bridge import a2a_task_to_voucher, a2a_task_to_handoff
from models import A2ATaskRequest


class TestHandoffBridge:
    def test_a2a_task_to_voucher(self):
        task = A2ATaskRequest(
            task_id="task_food_001",
            skill="order_food",
            params={"restaurant": "Pizza Place", "items": ["Margherita"]},
        )
        voucher = a2a_task_to_voucher(task, seller_id="agent_food_001", amount=25.0)
        assert voucher["voucher_id"].startswith("a2a_")
        assert voucher["seller_id"] == "agent_food_001"
        assert voucher["amount"] == 25.0
        assert "task_id" in voucher["metadata"]

    def test_a2a_task_to_handoff(self):
        task = A2ATaskRequest(task_id="task_002", skill="book_flight", params={"from": "NYC", "to": "LAX"})
        handoff = a2a_task_to_handoff(task, buyer_id="user_agent_001", seller_id="flight_agent_001")
        assert handoff["trace_id"] == "task_002"
        assert handoff["buyer_identity_id"] == "user_agent_001"
        assert handoff["seller_identity_id"] == "flight_agent_001"
        assert "authorization" in handoff
