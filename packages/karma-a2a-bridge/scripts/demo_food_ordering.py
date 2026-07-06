"""
Food Ordering Demo — A2A Discovery + Karma Settlement
Run: python scripts/demo_food_ordering.py
"""
import sys, os, json, time, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agent_sdk import A2AClient, search_agents, build_card

USER_AGENT_ID = "user_agent_demo"
FOOD_AGENT_CARD = build_card(
    agent_id="food_agent_001",
    name="Karma Food Delivery Agent",
    description="Order food from local restaurants with Karma settlement",
    capabilities=["order_food", "track_delivery", "karma_settle"],
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
                "delivery_address": {"type": "string"},
            },
            "required": ["restaurant", "items"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "total": {"type": "number"},
                "estimated_time": {"type": "string"},
            },
        },
    }],
    contract_address="0x496d178a5D32E9410E52bD5800602BDEe81B2A91",
)


def step(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def main():
    step("1. User Agent searches Registry for food delivery agents")
    results = search_agents(capabilities=["karma_settle", "order_food"])
    if results:
        print(f"  Found {len(results)} agent(s) via Registry")
    else:
        print(f"  Registry returned no results (expected — using local demo card)")
    print(f"  Target: {FOOD_AGENT_CARD['name']}")
    print(f"  Skills: {[s['id'] for s in FOOD_AGENT_CARD['skills']]}")
    print(f"  Karma contract: {FOOD_AGENT_CARD['karma']['contract_address']}")

    step("2. User Agent reads Food Agent's Agent Card")
    card = FOOD_AGENT_CARD
    print(f"  Agent: {card['name']}")
    print(f"  Capabilities: {card['capabilities']}")
    skill_names = [s['name'] for s in card['skills']]
    print(f"  Available skills: {skill_names}")

    step("3. User Agent sends A2A task to Food Agent")
    task_id = f"food_{uuid.uuid4().hex[:8]}"
    client = A2AClient(base_url=FOOD_AGENT_CARD["endpoint"])
    result = client.send_task(
        task_id=task_id,
        skill="order_food",
        params={
            "restaurant": "Pizza Place",
            "items": ["Margherita", "Coke"],
            "delivery_address": "123 Karma St",
        },
        requester_id=USER_AGENT_ID,
    )
    if result:
        print(f"  Task {task_id}: status={result['status']}")
    else:
        print(f"  Task failed (A2A Bridge not running — expected in demo mode)")
        result = {"status": "negotiating", "task_id": task_id}

    step("4. Food Agent confirms and generates Karma Voucher")
    voucher = {
        "voucher_id": f"a2a_{uuid.uuid4().hex[:12]}",
        "buyer_id": USER_AGENT_ID,
        "seller_id": "food_agent_001",
        "amount": 24.50,
        "currency": "USDC",
        "skill": "order_food",
        "metadata": {"source": "a2a_bridge", "task_id": task_id},
    }
    print(f"  Voucher created: {voucher['voucher_id']}")
    print(f"  Amount: {voucher['amount']} {voucher['currency']}")
    print(f"  Task: {task_id}")

    step("5. Handoff generated for Karma settlement")
    handoff = {
        "trace_id": task_id,
        "task_id": task_id,
        "buyer_identity_id": USER_AGENT_ID,
        "seller_identity_id": "food_agent_001",
        "voucher_id": voucher["voucher_id"],
        "skill": "order_food",
        "params": {"restaurant": "Pizza Place", "items": ["Margherita", "Coke"]},
        "authorization": {"manual_console_steps_completed": True, "a2a_negotiated": True},
    }
    print(json.dumps(handoff, indent=2))

    step("6. Result — User places order")
    order_result = {
        "order_id": f"ORD_{uuid.uuid4().hex[:8].upper()}",
        "total": 24.50,
        "estimated_time": "25-35 min",
        "voucher_id": voucher["voucher_id"],
        "settlement_status": "karma_voucher_issued",
    }
    print(json.dumps(order_result, indent=2))
    print(f"\n  [OK] Demo complete: Food ordered via A2A discovery, secured by Karma settlement")


if __name__ == "__main__":
    main()
