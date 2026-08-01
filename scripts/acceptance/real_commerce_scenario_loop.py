#!/usr/bin/env python3
"""Runnable real-commerce scenario loop (no Docker required).

Exercises the intentional closed spine for daily/B2B scenes:

  connect-from-template (boundary) → discover → owner Yes/No →
  Important Fields triple MATCHED → voucher → settlement SETTLED

Usage:
  python3 scripts/acceptance/real_commerce_scenario_loop.py
  python3 scripts/acceptance/real_commerce_scenario_loop.py --scenes food_delivery,ride_hailing

Exit 0 only when all selected scenes settle successfully.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "1")
os.environ.setdefault("A2A_REGISTRY_URL", "")

SCENARIOS: dict[str, dict] = {
    "food_delivery": {
        "requirement": "帮我点一份简餐外卖送到静安，预算 28 USDC",
        "amount": 28.0,
        "merchant_name": "面馆Bot",
        "self_description": "上海简餐外卖配送",
        "industry_id": "food_delivery",
        "capability": "order_food",
    },
    "ride_hailing": {
        "requirement": "帮我叫一辆车从陆家嘴到虹桥，预算 45 USDC",
        "amount": 45.0,
        "merchant_name": "出行Bot",
        "self_description": "上海网约车接驾",
        "industry_id": "ride_hailing",
        "capability": "book_ride",
    },
    "hotel_booking": {
        "requirement": "帮我订一晚酒店，预算 320 USDC",
        "amount": 320.0,
        "merchant_name": "酒店Bot",
        "self_description": "上海商务酒店预订",
        "industry_id": "hotel_booking",
        "capability": "book_hotel",
    },
    "flight_booking": {
        "requirement": "帮我订一张机票，预算 680 USDC",
        "amount": 680.0,
        "merchant_name": "票务Bot",
        "self_description": "国内机票出票",
        "industry_id": "flight_booking",
        "capability": "book_flight",
    },
    "b2b_procurement": {
        "requirement": "企业采购一批耗材，预算 1500 USDC",
        "amount": 1500.0,
        "merchant_name": "供应Bot",
        "self_description": "企业办公耗材采购供应",
        "industry_id": "b2b_procurement",
        "capability": "b2b_procurement",
    },
}


async def _run_scene(scene_id: str, spec: dict) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from db.models.orm import Base
    from services.agent_boundary import clear_agent_boundaries, get_agent_boundary
    from services.agent_directory import connect_agent
    from services.agent_onboarding_template import materialize_onboarding
    from services.agent_profile_store import clear_profile_cards
    from services.human_confirmation_policy import (
        decide_confirmation_session,
        reset_confirmation_sessions,
    )
    from services.important_fields_capture import reset_capture_store
    from services.intent_fulfillment import fulfill_intent

    reset_confirmation_sessions()
    reset_capture_store()
    clear_agent_boundaries()
    clear_profile_cards()

    tmp = tempfile.mkdtemp(prefix=f"karma_scene_{scene_id}_")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp}/scene.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    buyer_id = f"buyer-{scene_id}"
    merchant_id = f"merchant-{scene_id}"

    async with Session() as db:
        from services.agent_directory import refresh_p1_ready
        from services.agent_p1_readiness import (
            attest_responsibility_ack,
            boundary_content_hash,
            canonical_responsibility_ack,
            ensure_owner_identity,
        )

        owner_merchant = f"owner-{merchant_id}"
        owner_buyer = f"owner-{buyer_id}"
        await ensure_owner_identity(db, owner_merchant, display_hint=spec["merchant_name"])
        await ensure_owner_identity(db, owner_buyer, display_hint=f"用户-{scene_id}")

        # --- 1) Merchant P1 connect ---
        mat = materialize_onboarding(
            profile_id="merchant",
            answers={
                "display_name": spec["merchant_name"],
                "industry_ids": [spec["industry_id"]],
                "use_example_service_specs": True,
                "service_targets": ["consumer", "agent"],
                "service_area": {"mode": "local", "regions": ["上海"]},
                "capability_summary": spec["self_description"],
                "boundaries": "按模板 boundaries；超范围不接单",
            },
            agent_id=merchant_id,
            extra_capabilities=[spec["capability"], "karma_settle"],
        )
        connect = mat["agent_connect"]
        card = mat["profile_card"]
        caps = list(connect.get("capabilities") or [])
        caps.append("onboarding:merchant")
        caps.append(f"industry:{spec['industry_id']}")
        row = await connect_agent(
            db,
            agent_id=merchant_id,
            name=connect["name"],
            role="worker",
            capabilities=caps,
            profile_card=card,
            ensure_boundary=True,
            identity_class="merchant",
            owner_identity_id=owner_merchant,
            responsibility_acknowledged=True,
        )
        bhash = boundary_content_hash(get_agent_boundary(row.agent_id)) or ""
        ack = attest_responsibility_ack(
            {
                **canonical_responsibility_ack(
                    agent_id=row.agent_id,
                    owner_identity_id=owner_merchant,
                    identity_class="merchant",
                    boundary_hash=bhash,
                    acknowledged_at="2026-08-01T00:00:00Z",
                ),
                "acknowledged": True,
            }
        )
        meta = dict(row.onboarding_meta or {})
        meta.update(
            {
                "responsibility_ack": ack,
                "boundary_hash": bhash,
                "used_example_service_specs": True,
                "owner_identity_id": owner_merchant,
            }
        )
        row.onboarding_meta = meta
        row.boundary_hash = bhash
        await db.flush()
        p1 = await refresh_p1_ready(db, row.agent_id)
        boundary = get_agent_boundary(row.agent_id)
        assert boundary and boundary.get("boundary_complete") is True, boundary
        assert p1.get("p1_ready") is True, p1

        # --- 2) Buyer user agent (P1) ---
        buyer_mat = materialize_onboarding(
            profile_id="user",
            answers={"display_name": f"用户-{scene_id}"},
            agent_id=buyer_id,
        )
        buyer_row = await connect_agent(
            db,
            agent_id=buyer_id,
            name=buyer_mat["agent_connect"]["name"],
            role="client",
            capabilities=list(buyer_mat["agent_connect"].get("capabilities") or []),
            profile_card=buyer_mat["profile_card"],
            ensure_boundary=True,
            identity_class="user",
            owner_identity_id=owner_buyer,
            responsibility_acknowledged=True,
        )
        bb = boundary_content_hash(get_agent_boundary(buyer_row.agent_id)) or ""
        back = attest_responsibility_ack(
            {
                **canonical_responsibility_ack(
                    agent_id=buyer_row.agent_id,
                    owner_identity_id=owner_buyer,
                    identity_class="user",
                    boundary_hash=bb,
                    acknowledged_at="2026-08-01T00:00:00Z",
                ),
                "acknowledged": True,
            }
        )
        bmeta = dict(buyer_row.onboarding_meta or {})
        bmeta.update(
            {
                "responsibility_ack": back,
                "boundary_hash": bb,
                "owner_identity_id": owner_buyer,
            }
        )
        buyer_row.onboarding_meta = bmeta
        buyer_row.boundary_hash = bb
        await db.flush()
        await refresh_p1_ready(db, buyer_row.agent_id)

        # --- 3) Fulfill → awaiting owner confirmation ---
        paused = await fulfill_intent(
            db,
            requirement_text=spec["requirement"],
            buyer_identity_id=buyer_id,
            amount=spec["amount"],
            seller_identity_id=merchant_id,
            negotiate_a2a=False,
            auto_complete=False,
            require_owner_confirmation=True,
            auto_lock_important_fields=True,
        )
        if paused.get("status") != "awaiting_owner_confirmation":
            raise AssertionError(f"{scene_id}: expected awaiting_owner_confirmation, got {paused.get('status')}")
        sid = paused["confirmation"]["session_id"]
        decide_confirmation_session(sid, confirm=True, actor_agent_id=buyer_id)

        # --- 4) Resume → IF auto-lock (demo) → settle ---
        settled = await fulfill_intent(
            db,
            requirement_text=spec["requirement"],
            buyer_identity_id=buyer_id,
            amount=spec["amount"],
            seller_identity_id=merchant_id,
            negotiate_a2a=False,
            auto_complete=True,
            require_owner_confirmation=True,
            confirmation_session_id=sid,
            auto_lock_important_fields=True,
        )
        await db.commit()

        if settled.get("status") != "settled":
            raise AssertionError(f"{scene_id}: expected settled, got {settled.get('status')} timeline={settled.get('timeline')}")
        stages = [t["stage"] for t in settled.get("timeline") or []]
        for need in ("discover", "owner_confirmation", "important_fields_lock", "voucher_accepted", "settled"):
            if need not in stages:
                raise AssertionError(f"{scene_id}: missing stage {need} in {stages}")

        out = {
            "scene_id": scene_id,
            "status": "PASS",
            "task_id": settled["task_id"],
            "voucher_id": settled["voucher_id"],
            "capture_id": settled.get("important_fields_capture_id"),
            "fields_hash": settled.get("important_fields_hash"),
            "boundary_complete": boundary.get("boundary_complete"),
            "p1_ready": p1.get("p1_ready"),
            "must_confirm_steps": (boundary.get("confirmation_boundary") or {}).get("must_confirm_steps"),
            "auto_ok_steps": (boundary.get("confirmation_boundary") or {}).get("auto_ok_steps"),
        }
    await engine.dispose()
    return out


async def main_async(scenes: list[str]) -> int:
    print("=" * 64)
    print(" Karma real-commerce scenario loop")
    print("=" * 64)
    results = []
    failed = 0
    for sid in scenes:
        spec = SCENARIOS[sid]
        print(f"\n→ {sid}: {spec['requirement']}")
        try:
            r = await _run_scene(sid, spec)
            results.append(r)
            print(
                f"  PASS  task={r['task_id'][:8]}… voucher={r['voucher_id'][:8]}… "
                f"if={str(r['capture_id'] or '')[:10]}… boundary_complete={r['boundary_complete']}"
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            results.append({"scene_id": sid, "status": "FAIL", "error": str(exc)})
            print(f"  FAIL  {exc}")

    print("\n" + "=" * 64)
    print(f" Result: {len(scenes) - failed}/{len(scenes)} passed")
    print("=" * 64)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenes",
        default=",".join(SCENARIOS.keys()),
        help="Comma-separated scene_ids",
    )
    args = parser.parse_args()
    scenes = [s.strip() for s in args.scenes.split(",") if s.strip()]
    unknown = [s for s in scenes if s not in SCENARIOS]
    if unknown:
        print(f"Unknown scenes: {unknown}. Known: {list(SCENARIOS)}", file=sys.stderr)
        return 2
    return asyncio.run(main_async(scenes))


if __name__ == "__main__":
    raise SystemExit(main())
