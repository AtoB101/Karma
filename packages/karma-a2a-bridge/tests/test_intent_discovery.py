import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intent_discovery import discover_for_intent, parse_intent
from fastapi import FastAPI
from fastapi.testclient import TestClient
import a2a_server
from task_store import reset_task_store_for_tests


def test_parse_food_intent():
    intent = parse_intent("帮我点一份披萨外卖 25 USDC")
    assert "order_food" in intent["capabilities"]
    assert "order_food" in intent["skills"]
    assert intent["amount"] == 25.0


def test_discover_food_from_local_catalog():
    plan = discover_for_intent("I want to order food from a sushi place", amount=20)
    assert plan["recommended"] is not None
    assert "order_food" in plan["recommended"]["capabilities"]
    assert plan["negotiate"]["skill"] == "order_food"
    assert plan["flow"].startswith("intent")


def test_discover_endpoint(tmp_path):
    reset_task_store_for_tests(str(tmp_path / "t.sqlite3"))
    a2a_server._agent_card = None
    app = FastAPI()
    app.include_router(a2a_server.router)
    client = TestClient(app)
    r = client.post("/a2a/discover", json={"requirement_text": "book a flight to LAX"})
    assert r.status_code == 200
    body = r.json()
    assert body["recommended"]["agent_id"]
    assert "book_flight" in body["intent"]["skills"]
