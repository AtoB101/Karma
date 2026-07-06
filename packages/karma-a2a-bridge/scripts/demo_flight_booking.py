"""
Flight Booking Demo — A2A Discovery + Karma Settlement
Run: python scripts/demo_flight_booking.py
"""
import sys, os, json, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agent_sdk import search_agents, build_card

USER_AGENT_ID = "user_agent_demo"
FLIGHT_AGENT_CARD = build_card(
    agent_id="flight_agent_001",
    name="Karma Flight Booking Agent",
    description="Book flights with Karma-secured payments",
    capabilities=["book_flight", "cancel_flight", "karma_settle"],
    endpoint="http://localhost:8081",
    skills=[{
        "id": "book_flight",
        "name": "Book Flight",
        "description": "Search and book a flight",
        "input_schema": {
            "type": "object",
            "properties": {
                "from": {"type": "string"},
                "to": {"type": "string"},
                "date": {"type": "string"},
                "passengers": {"type": "integer"},
            },
            "required": ["from", "to", "date"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "booking_ref": {"type": "string"},
                "total": {"type": "number"},
                "flight_info": {"type": "object"},
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
    step("1. User Agent searches Registry for flight booking agents")
    results = search_agents(capabilities=["karma_settle", "book_flight"])
    if results:
        print(f"  Found {len(results)} agent(s) via Registry")
    else:
        print(f"  Registry returned no results — using local demo card")
    print(f"  Target: {FLIGHT_AGENT_CARD['name']}")

    step("2. Read Flight Agent's card")
    card = FLIGHT_AGENT_CARD
    print(f"  Capabilities: {card['capabilities']}")
    for s in card["skills"]:
        print(f"  Skill: {s['id']} — {s['description']}")
        print(f"    Input: {json.dumps(s['input_schema']['properties'], indent=4)}")

    step("3. User sends A2A task to book a flight")
    task_id = f"flight_{uuid.uuid4().hex[:8]}"
    params = {
        "from": "NYC",
        "to": "LAX",
        "date": "2026-08-15",
        "passengers": 1,
    }
    print(f"  Task: {task_id}")
    print(f"  Params: {json.dumps(params)}")

    step("4. Flight Agent confirms and creates Karma Voucher")
    voucher = {
        "voucher_id": f"a2a_{uuid.uuid4().hex[:12]}",
        "buyer_id": USER_AGENT_ID,
        "seller_id": "flight_agent_001",
        "amount": 349.00,
        "currency": "USDC",
        "skill": "book_flight",
        "metadata": {"source": "a2a_bridge", "task_id": task_id},
    }
    print(f"  Voucher: {voucher['voucher_id']}")
    print(f"  Amount: {voucher['amount']} {voucher['currency']}")

    step("5. Handoff generated for Karma settlement")
    handoff = {
        "trace_id": task_id,
        "task_id": task_id,
        "buyer_identity_id": USER_AGENT_ID,
        "seller_identity_id": "flight_agent_001",
        "voucher_id": voucher["voucher_id"],
        "skill": "book_flight",
        "params": params,
        "authorization": {"manual_console_steps_completed": True, "a2a_negotiated": True},
        "karma_contract": card["karma"]["contract_address"],
    }
    print(json.dumps(handoff, indent=2))

    step("6. Booking confirmed")
    booking = {
        "booking_ref": f"BK-{uuid.uuid4().hex[:6].upper()}",
        "total": 349.00,
        "flight_info": {
            "airline": "Karma Air",
            "flight": "KA-2026",
            "from": "NYC",
            "to": "LAX",
            "date": "2026-08-15",
            "departure": "08:30",
            "arrival": "11:45",
        },
        "voucher_id": voucher["voucher_id"],
        "settlement_status": "karma_voucher_issued",
    }
    print(json.dumps(booking, indent=2))
    print(f"\n  [OK] Demo complete: Flight booked via A2A discovery, secured by Karma settlement")


if __name__ == "__main__":
    main()
