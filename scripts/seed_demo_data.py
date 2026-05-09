#!/usr/bin/env python3
"""
Seed the database with demo agents, contracts, and receipts.
Safe to run multiple times (idempotent).

Usage:
    python scripts/seed_demo_data.py
"""
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def seed() -> None:
    from db.session import AsyncSessionLocal, init_db
    from db.models.orm import AgentModel, TaskContractModel, SettlementModel, ReputationModel
    from services.signing import signing_service, sha256_of
    from sqlalchemy import select

    await init_db()

    async with AsyncSessionLocal() as session:

        # ---- Agents ----
        agents_data = [
            dict(agent_id="demo-client-001",    name="Demo Client Agent",    role="client",    capabilities=["task-creation"]),
            dict(agent_id="demo-worker-001",    name="Demo Worker Agent",    role="worker",    capabilities=["captioning", "ocr", "labeling"]),
            dict(agent_id="demo-worker-002",    name="Demo Worker Agent 2",  role="worker",    capabilities=["captioning"]),
            dict(agent_id="demo-arbitrator-001",name="Demo Arbitrator",      role="arbitrator",capabilities=["dispute-resolution"]),
        ]

        pub_key = signing_service.get_public_key_b64()
        for a in agents_data:
            existing = await session.get(AgentModel, a["agent_id"])
            if not existing:
                session.add(AgentModel(
                    agent_id=a["agent_id"],
                    name=a["name"],
                    role=a["role"],
                    public_key=pub_key,
                    capabilities=a["capabilities"],
                    is_active=True,
                    registered_at=datetime.utcnow(),
                ))
                print(f"[seed] Agent: {a['name']}")

        # ---- Task Contract (completed) ----
        contract_id = "demo-task-001"
        existing = await session.get(TaskContractModel, contract_id)
        if not existing:
            session.add(TaskContractModel(
                task_id=contract_id,
                client_agent_id="demo-client-001",
                worker_agent_id="demo-worker-001",
                title="Caption 10 Product Images",
                description="Generate accurate English captions for 10 product images.",
                expected_output_schema={"type": "object", "properties": {"caption": {"type": "string"}}},
                expected_step_count=20,
                escrow_amount=50.0,
                currency="USD",
                deadline_at=datetime.utcnow() + timedelta(hours=2),
                contract_hash="a" * 64,
                created_at=datetime.utcnow() - timedelta(hours=1),
            ))
            print(f"[seed] Contract: {contract_id}")

        # ---- Settlement (released) ----
        existing_s = await session.execute(
            select(SettlementModel).where(SettlementModel.task_id == contract_id)
        )
        if not existing_s.scalar_one_or_none():
            session.add(SettlementModel(
                settlement_id="demo-settlement-001",
                task_id=contract_id,
                escrow_amount=50.0,
                currency="USD",
                status="released",
                client_agent_id="demo-client-001",
                worker_agent_id="demo-worker-001",
                released_amount=50.0,
                created_at=datetime.utcnow() - timedelta(hours=1),
                updated_at=datetime.utcnow(),
                released_at=datetime.utcnow(),
            ))
            print(f"[seed] Settlement: demo-settlement-001 (released)")

        # ---- Reputation ----
        rep_data = [
            dict(agent_id="demo-client-001",    role="client",    score=120.0, total=5,  success=5, disputed=0),
            dict(agent_id="demo-worker-001",    role="worker",    score=247.5, total=42, success=39,disputed=1),
            dict(agent_id="demo-worker-002",    role="worker",    score=95.0,  total=8,  success=7, disputed=0),
            dict(agent_id="demo-arbitrator-001",role="arbitrator",score=300.0, total=3,  success=3, disputed=0),
        ]
        for r in rep_data:
            existing_r = await session.get(ReputationModel, r["agent_id"])
            if not existing_r:
                session.add(ReputationModel(
                    agent_id=r["agent_id"],
                    role=r["role"],
                    score=r["score"],
                    total_tasks=r["total"],
                    successful_tasks=r["success"],
                    disputed_tasks=r["disputed"],
                    arbitration_wins=0,
                    arbitration_losses=0,
                    consecutive_successes=0,
                    wash_trade_flags=0,
                    last_updated=datetime.utcnow(),
                ))
                print(f"[seed] Reputation: {r['agent_id']} score={r['score']}")

        await session.commit()
        print("[seed] Done.")


if __name__ == "__main__":
    asyncio.run(seed())
