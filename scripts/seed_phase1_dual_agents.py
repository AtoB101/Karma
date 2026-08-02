#!/usr/bin/env python3
"""
Seed two trade-ready agents (buyer + seller) for agent↔agent Phase-1 launch.

Creates:
  - Agent rows
  - Automation policies (preauth + auto_execute_pipeline)
  - Active Runtime Key metadata rows (wallet mint not required for local land)
  - Buyer capacity credits
  - Seller trusts buyer
  - Bootstrap API keys (karma_{id}_{secret}) for HTTP / MCP

Writes ``.env.phase1.local`` (gitignored pattern) with IDs + keys.

Usage:
    # Same DATABASE_URL as the API you will start
    set -a && source deploy/.env.local-openclaw.example && set +a
    python3 scripts/seed_phase1_dual_agents.py

    # Then:
    uvicorn api.app:app --host 127.0.0.1 --port 8000
    set -a && source .env.phase1.local && set +a
    python3 scripts/acceptance/phase1_claw_manus_smoke.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def _seed_into_session(
    db,
    *,
    buyer_id: str,
    seller_id: str,
    capacity: float,
    task_types: list[str],
) -> None:
    from db.models.orm import (
        AgentAutomationPolicyModel,
        CapacityModel,
        RuntimeKeyModel,
    )
    from services.agent_automation_policy import upsert_automation_policy
    from services.identity_agents import ensure_agent_for_identity

    await ensure_agent_for_identity(db, buyer_id, role="buyer", name="Phase1 Buyer Agent")
    await ensure_agent_for_identity(db, seller_id, role="seller", name="Phase1 Seller Agent")

    for identity, is_seller in ((buyer_id, False), (seller_id, True)):
        await upsert_automation_policy(
            db,
            karma_identity_id=identity,
            auto_enabled=True,
            single_limit=100.0,
            daily_limit=500.0,
            permissions=["submit_receipt", "verify_voucher", "update_progress"],
            high_risk_mode="always",
            responsibility_acknowledged=True,
            preauth_enabled=True,
            auto_accept_incoming=is_seller,
            auto_execute_pipeline=True,
            allowed_task_types=list(task_types),
            task_precision_min=0.5,
            task_precision_max=5.0,
            trusted_counterparty_ids=[buyer_id] if is_seller else [],
            responsibility_boundary_id="scene-phase1-a2a",
            updated_by_actor="seed_phase1_dual_agents",
        )

        key_id = f"rt-{identity}"
        existing_key = await db.get(RuntimeKeyModel, key_id)
        if existing_key is None:
            db.add(
                RuntimeKeyModel(
                    key_id=key_id,
                    secret_hash="$2b$12$phase1localruntimekeyplaceholderhash000000000",
                    wallet_address="0x" + ("ab" if not is_seller else "cd") * 20,
                    karma_identity_id=identity,
                    permissions=["submit_receipt", "verify_voucher", "update_progress"],
                    single_limit=100.0,
                    daily_limit=500.0,
                    expire_at=datetime.utcnow() + timedelta(days=30),
                    agent_name=f"phase1-{identity}",
                    status="active",
                )
            )
        else:
            existing_key.status = "active"
            existing_key.expire_at = datetime.utcnow() + timedelta(days=30)

    cap = await db.get(CapacityModel, buyer_id)
    if cap is None:
        db.add(
            CapacityModel(
                identity_id=buyer_id,
                total_locked_usdc=float(capacity),
                total_bill_credits=float(capacity),
                available_credits=float(capacity),
            )
        )
    else:
        if float(cap.available_credits or 0) < 50.0:
            top_up = max(0.0, float(capacity) - float(cap.available_credits or 0))
            cap.available_credits = float(cap.available_credits or 0) + top_up
            cap.total_bill_credits = float(cap.total_bill_credits or 0) + top_up
            cap.total_locked_usdc = float(cap.total_locked_usdc or 0) + top_up

    seller_pol = await db.get(AgentAutomationPolicyModel, seller_id)
    if seller_pol is not None:
        trusted = list(seller_pol.trusted_counterparty_ids or [])
        if buyer_id not in trusted:
            trusted.append(buyer_id)
        seller_pol.trusted_counterparty_ids = trusted
        seller_pol.auto_accept_incoming = True
        seller_pol.auto_execute_pipeline = True


async def seed_dual_agents(
    *,
    buyer_id: str,
    seller_id: str,
    capacity: float = 500.0,
    task_types: list[str] | None = None,
    db=None,
) -> dict[str, str]:
    """Idempotent seed; returns env mapping including API keys.

    Pass ``db`` (AsyncSession) to reuse the caller's session (pytest / ASGI).
    When omitted, opens ``AsyncSessionLocal`` after ``init_db()``.
    """
    from services.agent_bootstrap_credentials import mint_agent_api_key

    types = task_types or ["api.caption"]

    if db is not None:
        await _seed_into_session(
            db, buyer_id=buyer_id, seller_id=seller_id, capacity=capacity, task_types=types
        )
        await db.commit()
    else:
        from db.session import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as session:
            await _seed_into_session(
                session,
                buyer_id=buyer_id,
                seller_id=seller_id,
                capacity=capacity,
                task_types=types,
            )
            await session.commit()

    buyer_creds = mint_agent_api_key(buyer_id)
    seller_creds = mint_agent_api_key(seller_id)

    return {
        "KARMA_RUNTIME_URL": os.environ.get("KARMA_RUNTIME_URL", "http://127.0.0.1:8000"),
        "KARMA_BUYER_IDENTITY_ID": buyer_id,
        "KARMA_SELLER_IDENTITY_ID": seller_id,
        "KARMA_BUYER_API_KEY": buyer_creds["api_key"],
        "KARMA_SELLER_API_KEY": seller_creds["api_key"],
        "KARMA_API_KEY": buyer_creds["api_key"],
        "SETTLEMENT_MODE": os.environ.get("SETTLEMENT_MODE", "offchain"),
        "TRADE_LAUNCH_REQUIRE_EIP712": os.environ.get("TRADE_LAUNCH_REQUIRE_EIP712", "false"),
    }


def write_env_file(path: Path, env: dict[str, str]) -> None:
    lines = [
        "# Generated by scripts/seed_phase1_dual_agents.py — do not commit secrets",
        f"# {datetime.utcnow().isoformat()}Z",
        "",
    ]
    for k in (
        "KARMA_RUNTIME_URL",
        "KARMA_BUYER_IDENTITY_ID",
        "KARMA_SELLER_IDENTITY_ID",
        "KARMA_BUYER_API_KEY",
        "KARMA_SELLER_API_KEY",
        "KARMA_API_KEY",
        "SETTLEMENT_MODE",
        "TRADE_LAUNCH_REQUIRE_EIP712",
    ):
        lines.append(f"{k}={env[k]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _amain(args: argparse.Namespace) -> int:
    env = await seed_dual_agents(
        buyer_id=args.buyer_id,
        seller_id=args.seller_id,
        capacity=args.capacity,
        task_types=[t.strip() for t in args.task_types.split(",") if t.strip()],
    )
    out = Path(args.env_out)
    write_env_file(out, env)
    print(f"[seed] buyer={env['KARMA_BUYER_IDENTITY_ID']}")
    print(f"[seed] seller={env['KARMA_SELLER_IDENTITY_ID']}")
    print(f"[seed] wrote {out.resolve()}")
    print("[seed] next:")
    print("  uvicorn api.app:app --host 127.0.0.1 --port 8000")
    print(f"  set -a && source {out} && set +a")
    print("  bash scripts/acceptance/local_dual_agent_gate.sh")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Seed Phase-1 buyer/seller for A2A trade launch")
    p.add_argument("--buyer-id", default=os.environ.get("KARMA_BUYER_IDENTITY_ID", "a2a-buyer"))
    p.add_argument("--seller-id", default=os.environ.get("KARMA_SELLER_IDENTITY_ID", "a2a-seller"))
    p.add_argument("--capacity", type=float, default=500.0)
    p.add_argument("--task-types", default="api.caption")
    p.add_argument("--env-out", default=".env.phase1.local")
    return asyncio.run(_amain(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
